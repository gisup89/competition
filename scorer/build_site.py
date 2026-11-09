"""GitHub Pages 에 배포할 정적 사이트(_site/)를 조립한다.

  python -m scorer.build_site [--out _site]

site/ 의 HTML·JS·CSS 를 복사하고, 각 대회의 README.md, leaderboard.json, private_leaderboard.json,
data/ 파일을 넣은 뒤 competitions.json(대회 목록)과 site.json(사이트 설정)을 생성한다.
암호화 파일(.enc), 평문 정답(solution.csv), 설정 원본은 포함하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .common import ROOT, SITE_SRC, comp_dir, list_competitions, load_config, load_site_config, now_utc
from .metrics import get_metric

EXCLUDE_NAMES = {"solution.csv", "solution.csv.enc", "final_results.csv", "final_results.csv.enc", "config.yml", "selections.yml"}


def build(out: Path) -> dict:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE_SRC, out)
    (out / ".nojekyll").write_text("", encoding="utf-8")

    site_cfg = load_site_config()
    comps = []
    for slug in list_competitions():
        cfg = load_config(slug)
        if not cfg.get("published", True):
            continue
        src = comp_dir(slug)
        dst = out / "competitions" / slug
        dst.mkdir(parents=True, exist_ok=True)

        for name in ("README.md", "leaderboard.json", "private_leaderboard.json"):
            if (src / name).exists():
                shutil.copy2(src / name, dst / name)
        data_files = []
        if (src / "data").exists():
            (dst / "data").mkdir(exist_ok=True)
            for f in sorted((src / "data").iterdir()):
                if f.is_file() and f.name not in EXCLUDE_NAMES and not f.name.endswith(".enc"):
                    shutil.copy2(f, dst / "data" / f.name)
                    data_files.append({"name": f.name, "size": f.stat().st_size})

        n_test = None
        sample = src / "data" / "sample_submission.csv"
        if sample.exists():
            with open(sample, encoding="utf-8-sig") as fh:
                n_test = max(0, sum(1 for _ in fh) - 1)
        lb = {}
        if (src / "leaderboard.json").exists():
            lb = json.loads((src / "leaderboard.json").read_text(encoding="utf-8"))
        metric = get_metric(cfg["metric"])
        comps.append(
            {
                "slug": slug,
                "title": cfg["title"],
                "subtitle": cfg.get("subtitle", ""),
                "metric": metric.key,
                "metric_name": metric.name,
                "metric_description": metric.description,
                "higher_is_better": metric.higher_is_better,
                "id_column": cfg["id_column"],
                "target_column": cfg["target_column"],
                "start": cfg.get("start"),
                "deadline": cfg.get("deadline"),
                "timezone": cfg.get("timezone"),
                "daily_limit": cfg["daily_limit"],
                "max_final_submissions": cfg["max_final_submissions"],
                "teams": bool(cfg.get("teams", True)),
                "score_decimals": cfg["score_decimals"],
                "finalized": bool(lb.get("finalized", False)),
                "n_participants": len(lb.get("public_leaderboard", [])),
                "n_submissions": len([s for s in lb.get("submissions", []) if s.get("status") == "scored"]),
                "updated_at": lb.get("updated_at"),
                "data_files": data_files,
                "n_test": n_test,
            }
        )

    index = {"generated_at": now_utc().isoformat(timespec="seconds"), "competitions": comps}
    (out / "competitions.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")

    public_site = {
        "title": site_cfg.get("title", "머신러닝 경진대회"),
        "description": site_cfg.get("description", ""),
        "organizer": site_cfg.get("organizer", ""),
        "repo": site_cfg.get("repo", ""),
        "submission_mode": site_cfg.get("submission_mode", "issue"),
        "require_encrypted": bool(site_cfg.get("require_encrypted", False)),
    }
    (out / "site.json").write_text(json.dumps(public_site, ensure_ascii=False, indent=1), encoding="utf-8")
    return index


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "_site"))
    args = ap.parse_args(argv)
    index = build(Path(args.out))
    print(f"사이트 생성 완료: {args.out} (대회 {len(index['competitions'])}개)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
