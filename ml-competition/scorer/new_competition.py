"""새 대회 생성 도구.

예)
  python -m scorer.new_competition \
      --slug house-price --title "주택 가격 예측" --metric rmse \
      --id-column id --target-column price \
      --solution ./raw/solution_full.csv \
      --data ./raw/train.csv ./raw/test.csv \
      --public-ratio 0.3 \
      --start 2026-11-20T00:00:00+09:00 --deadline 2026-12-14T23:59:59+09:00 \
      --daily-limit 5 --max-final 2

하는 일
  competitions/<slug>/config.yml, README.md, data/*, sample_submission.csv 생성
  정답 파일에 Usage(Public/Private) 열을 추가(없을 때)하고 solution.csv.enc 로 암호화 저장
  (평문 solution.csv 는 로컬에만 남고 .gitignore 로 커밋되지 않음)
  빈 leaderboard.json, submissions/<slug>/.gitkeep 생성
  .github/ISSUE_TEMPLATE/submission.yml 의 대회 선택 목록 갱신
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .common import (
    COMP_DIR,
    ISSUE_TEMPLATE,
    SUBMISSION_DIR,
    comp_dir,
    encrypt_bytes,
    list_competitions,
    load_config,
)
from .leaderboard import empty_leaderboard, save_leaderboard
from .metrics import METRICS, get_metric

README_TEMPLATE = """# {title}

{subtitle}

## 개요

이 대회의 목표와 배경을 설명하세요.

## 데이터

- `train.csv` : 학습 데이터 (입력 변수 + 정답 `{target}`)
- `test.csv` : 테스트 데이터 (입력 변수만 포함)
- `sample_submission.csv` : 제출 파일 형식

## 평가

- 평가지표: **{metric_name}** ({metric_desc})
- Public 리더보드는 테스트 데이터의 일부({public_pct}%)로 계산되며, 최종 순위는 마감 후 나머지(Private) 데이터로 산정합니다.
- 최종 평가에는 각 참가자(팀)의 Public 점수 상위 {max_final}개 제출물 가운데 Private 점수가 가장 좋은 것을 사용합니다.

## 제출 형식

`sample_submission.csv` 와 같은 열 구조의 CSV 파일을 제출합니다.

```
{id},{target}
...
```

## 규칙

- 하루 최대 {daily_limit}회 제출 (한국 시간 기준 자정 초기화)
- 외부 데이터 사용 여부, 팀 구성 규칙 등을 여기에 적으세요.
"""


def write_issue_template() -> None:
    comps = []
    for slug in list_competitions():
        cfg = load_config(slug)
        if cfg.get("published", True):
            comps.append(f"{cfg['title']} ({slug})")
    if not comps:
        comps = ["(진행 중인 대회 없음)"]
    options = "\n".join(f"        - \"{c}\"" for c in comps)
    text = f"""name: "📤 제출 (Submission)"
description: "예측 결과 CSV 파일을 제출합니다. 제출 후 1~3분 뒤 이 이슈에 점수가 댓글로 달립니다."
title: "[제출] "
labels: ["submission"]
body:
  - type: markdown
    attributes:
      value: |
        **제출 방법**
        1. 아래에서 대회를 선택합니다.
        2. '제출 파일' 칸에 CSV 파일을 **끌어다 놓습니다** (업로드가 끝나면 링크가 자동으로 들어갑니다).
        3. 'Create' 버튼을 누르면 자동 채점이 시작됩니다. 결과는 이 이슈의 댓글로 알려 드립니다.
  - type: dropdown
    id: competition
    attributes:
      label: 대회
      description: 제출할 대회를 선택하세요.
      options:
{options}
    validations:
      required: true
  - type: textarea
    id: file
    attributes:
      label: 제출 파일
      description: CSV 파일 하나를 이 칸에 끌어다 놓거나 클립보드에서 붙여넣으세요. 업로드가 완료되어 `[파일명](https://github.com/user-attachments/...)` 링크가 생길 때까지 기다린 뒤 제출하세요.
      placeholder: 여기에 CSV 파일을 끌어다 놓으세요
    validations:
      required: true
  - type: input
    id: note
    attributes:
      label: 메모 (선택)
      description: 사용한 모델·특징 등 간단한 설명 (리더보드 제출 기록에 표시됩니다)
      placeholder: 예) LightGBM, 로그 변환, 5-fold CV
"""
    ISSUE_TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    ISSUE_TEMPLATE.write_text(text, encoding="utf-8")


def add_usage_column(sol: pd.DataFrame, cfg: dict, public_ratio: float, seed: int) -> pd.DataFrame:
    if "Usage" in sol.columns:
        vals = set(sol["Usage"].astype(str).str.strip().str.lower())
        bad = vals - {"public", "private", "ignored"}
        if bad:
            raise SystemExit(f"Usage 열에는 Public/Private/Ignored 만 가능합니다. 발견된 값: {bad}")
        sol["Usage"] = sol["Usage"].astype(str).str.strip().str.capitalize()
        return sol
    rng = np.random.default_rng(seed)
    n = len(sol)
    usage = np.array(["Private"] * n, dtype=object)
    metric = get_metric(cfg["metric"])
    if metric.kind in ("label", "proba"):
        # 클래스별 층화 분할
        target = sol[cfg["target_column"]].astype(str)
        for _, idx in target.groupby(target).groups.items():
            idx = np.array(list(idx))
            rng.shuffle(idx)
            k = int(round(len(idx) * public_ratio))
            usage[idx[:k]] = "Public"
    else:
        idx = rng.permutation(n)
        usage[idx[: int(round(n * public_ratio))]] = "Public"
    sol = sol.copy()
    sol["Usage"] = usage
    return sol


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True, help="URL 에 쓰일 영문 식별자 (예: house-price)")
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--metric", required=True, choices=sorted(METRICS))
    ap.add_argument("--id-column", required=True)
    ap.add_argument("--target-column", required=True)
    ap.add_argument("--solution", required=True, help="정답 CSV (id, target[, Usage])")
    ap.add_argument("--sample", help="sample_submission.csv (없으면 정답 파일로부터 자동 생성)")
    ap.add_argument("--data", nargs="*", default=[], help="학생에게 공개할 파일들 (train.csv test.csv ...)")
    ap.add_argument("--public-ratio", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start", default=None)
    ap.add_argument("--deadline", default=None)
    ap.add_argument("--daily-limit", type=int, default=5)
    ap.add_argument("--max-final", type=int, default=2)
    ap.add_argument("--no-teams", action="store_true")
    ap.add_argument("--pos-label", default=1)
    ap.add_argument("--timezone", default="Asia/Seoul")
    ap.add_argument("--readme", help="개요 마크다운 파일 (없으면 템플릿 생성)")
    ap.add_argument("--force", action="store_true", help="기존 대회 폴더 덮어쓰기")
    args = ap.parse_args(argv)

    if not args.slug.replace("-", "").replace("_", "").isalnum() or not args.slug.isascii():
        raise SystemExit("slug 는 영문·숫자·하이픈(-)·밑줄(_)만 사용할 수 있습니다.")

    d = comp_dir(args.slug)
    if d.exists() and not args.force:
        raise SystemExit(f"{d} 가 이미 있습니다. 덮어쓰려면 --force 를 지정하세요.")
    (d / "data").mkdir(parents=True, exist_ok=True)

    cfg = {
        "title": args.title,
        "subtitle": args.subtitle,
        "metric": args.metric,
        "id_column": args.id_column,
        "target_column": args.target_column,
        "pos_label": args.pos_label,
        "timezone": args.timezone,
        "start": args.start,
        "deadline": args.deadline,
        "daily_limit": args.daily_limit,
        "max_final_submissions": args.max_final,
        "teams": not args.no_teams,
        "score_decimals": 5,
        "max_file_mb": 20,
        "allow_unregistered": False,
        "published": True,
        "public_ratio": args.public_ratio,
    }
    metric = get_metric(args.metric)

    # 정답 파일
    sol = pd.read_csv(args.solution)
    for col in (args.id_column, args.target_column):
        if col not in sol.columns:
            raise SystemExit(f"정답 파일에 `{col}` 열이 없습니다. 열 목록: {list(sol.columns)}")
    if sol[args.id_column].duplicated().any():
        raise SystemExit("정답 파일의 id 가 중복됩니다.")
    sol = add_usage_column(sol, {"metric": args.metric, "target_column": args.target_column}, args.public_ratio, args.seed)
    sol = sol[[args.id_column, args.target_column, "Usage"]]
    sol.to_csv(d / "solution.csv", index=False)
    (d / "solution.csv.enc").write_bytes(encrypt_bytes(sol.to_csv(index=False).encode("utf-8")))

    # 공개 데이터
    for p in args.data:
        src = Path(p)
        if not src.exists():
            raise SystemExit(f"파일이 없습니다: {src}")
        shutil.copy2(src, d / "data" / src.name)

    # 샘플 제출 파일
    sample_dst = d / "data" / "sample_submission.csv"
    if args.sample:
        shutil.copy2(args.sample, sample_dst)
    elif not sample_dst.exists():
        sample = sol[[args.id_column]].copy()
        if metric.kind == "regression":
            fill = pd.to_numeric(sol[args.target_column], errors="coerce").mean()
            sample[args.target_column] = round(float(fill), 4)
        elif metric.kind == "proba":
            sample[args.target_column] = 0.5
        else:
            sample[args.target_column] = sol[args.target_column].mode().iloc[0]
        sample.to_csv(sample_dst, index=False)

    # config / README / leaderboard
    (d / "config.yml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8"
    )
    if args.readme:
        shutil.copy2(args.readme, d / "README.md")
    elif not (d / "README.md").exists():
        n_pub = int((sol["Usage"] == "Public").sum())
        n_all = int((sol["Usage"] != "Ignored").sum())
        (d / "README.md").write_text(
            README_TEMPLATE.format(
                title=args.title,
                subtitle=args.subtitle,
                target=args.target_column,
                id=args.id_column,
                metric_name=metric.name,
                metric_desc=metric.description,
                public_pct=round(100 * n_pub / max(n_all, 1)),
                max_final=args.max_final,
                daily_limit=args.daily_limit,
            ),
            encoding="utf-8",
        )
    full_cfg = load_config(args.slug)
    if not (d / "leaderboard.json").exists():
        save_leaderboard(full_cfg, empty_leaderboard(full_cfg))

    (SUBMISSION_DIR / args.slug).mkdir(parents=True, exist_ok=True)
    (SUBMISSION_DIR / args.slug / ".gitkeep").write_text("", encoding="utf-8")

    write_issue_template()

    print(f"대회 생성 완료: {d}")
    print(f"  - 정답 행 수: {len(sol)} (Public {int((sol['Usage']=='Public').sum())}, Private {int((sol['Usage']=='Private').sum())})")
    print("  - 암호화된 정답: solution.csv.enc (평문 solution.csv 는 커밋되지 않습니다)")
    print("  - README.md 를 열어 대회 설명을 채운 뒤 커밋·푸시하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
