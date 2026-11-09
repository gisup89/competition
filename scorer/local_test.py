"""로컬에서 채점 흐름을 시험하는 도구 (GitHub 없이).

  # 가짜 이슈 제출을 만들어 채점 → leaderboard.json 갱신, 댓글은 화면에 출력
  python -m scorer.local_test submit --competition demo-house-price --file my_pred.csv --login hong

  # 시험 후 리더보드 초기화 (실제 운영 전 반드시 실행)
  python -m scorer.local_test reset --competition demo-house-price
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

from .common import load_config, now_utc
from .leaderboard import empty_leaderboard, lb_path, save_leaderboard
from . import process_submission


def fake_issue_event(number: int, login: str, competition: str, note: str, created_at: str | None) -> dict:
    cfg = load_config(competition)
    body = (
        f"### 대회\n\n{cfg['title']} ({competition})\n\n"
        f"### 제출 파일\n\n[submission.csv](https://github.com/user-attachments/files/0/submission.csv)\n\n"
        f"### 메모 (선택)\n\n{note or '_No response_'}\n"
    )
    return {
        "action": "opened",
        "issue": {
            "number": number,
            "html_url": f"https://github.com/example/repo/issues/{number}",
            "user": {"login": login},
            "title": "[제출] 로컬 테스트",
            "body": body,
            "created_at": created_at or now_utc().isoformat(timespec="seconds"),
            "labels": [{"name": "submission"}],
        },
        "repository": {"full_name": "example/repo"},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--competition", required=True)
    s.add_argument("--file", required=True)
    s.add_argument("--login", required=True, help="참가자 명단의 GitHub 아이디")
    s.add_argument("--note", default="")
    s.add_argument("--number", type=int, default=None, help="가짜 이슈 번호")
    s.add_argument("--created-at", default=None, help="ISO 시각 (기간·일일 한도 시험용)")
    r = sub.add_parser("reset")
    r.add_argument("--competition", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "reset":
        cfg = load_config(args.competition)
        save_leaderboard(cfg, empty_leaderboard(cfg))
        for name in ("private_leaderboard.json", "final_results.csv.enc", "final_results.csv"):
            p = lb_path(args.competition).parent / name
            if p.exists():
                p.unlink()
        print(f"{args.competition} 리더보드를 초기화했습니다.")
        return 0

    number = args.number or int(datetime.now(timezone.utc).timestamp()) % 100000
    event = fake_issue_event(number, args.login, args.competition, args.note, args.created_at)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(event, fh, ensure_ascii=False)
        path = fh.name
    os.environ["DRY_RUN"] = "1"
    os.environ["LOCAL_SUBMISSION_FILE"] = args.file
    os.environ.pop("GITHUB_TOKEN", None)
    return process_submission.main(["--event", path, "--dry-run"])


if __name__ == "__main__":
    sys.exit(main())
