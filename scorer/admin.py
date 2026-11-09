"""교수자용 리더보드 관리 도구 (로컬에서 실행 후 커밋·푸시).

  python -m scorer.admin list      --competition house-price              # 제출 목록
  python -m scorer.admin remove    --competition house-price --id 12 [--id 15]   # 제출 삭제
  python -m scorer.admin recompute --competition house-price              # Public 리더보드 재계산
  python -m scorer.admin private   --competition house-price              # Private 리더보드 미리보기 (키 필요, 공개 안 됨)
  python -m scorer.admin refresh-template                                 # 이슈 제출 양식의 대회 목록 다시 생성
"""
from __future__ import annotations

import argparse
import sys

from .common import fmt_local, fmt_score, load_config, parse_dt
from .leaderboard import compute_private_board, compute_public_board, load_leaderboard, save_leaderboard


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "remove", "recompute", "private", "refresh-template"])
    ap.add_argument("--competition")
    ap.add_argument("--id", type=int, action="append", default=[], help="삭제할 제출 번호 (여러 번 지정 가능)")
    args = ap.parse_args(argv)

    if args.cmd == "refresh-template":
        from .new_competition import write_issue_template
        write_issue_template()
        print(".github/ISSUE_TEMPLATE/submission.yml 의 대회 목록을 갱신했습니다. 커밋·푸시하세요.")
        return 0
    if not args.competition:
        print("--competition 을 지정하세요.")
        return 1
    cfg = load_config(args.competition)
    lb = load_leaderboard(cfg)

    if args.cmd == "list":
        print(f"{'id':>4} {'시각':<17} {'참가자':<18} {'Public':>14} {'github':<16} 메모")
        for s in lb["submissions"]:
            when = fmt_local(parse_dt(s["created_at"], cfg), cfg)
            dup = f" [#{s['duplicate_of']}과 동일]" if s.get("duplicate_of") else ""
            print(f"{s['id']:>4} {when:<17} {s['display']:<18} {fmt_score(s['public_score'], cfg):>14} {s['github']:<16} {s.get('note','')}{dup}")
        print(f"총 {len(lb['submissions'])}건, 참가 단위 {len(lb['public_leaderboard'])}")
        return 0

    if args.cmd == "remove":
        if not args.id:
            print("--id 로 삭제할 제출 번호를 지정하세요.")
            return 1
        before = len(lb["submissions"])
        lb["submissions"] = [s for s in lb["submissions"] if s["id"] not in set(args.id)]
        removed = before - len(lb["submissions"])
        lb["public_leaderboard"] = compute_public_board(lb, cfg)
        save_leaderboard(cfg, lb)
        print(f"{removed}건 삭제, 리더보드 재계산 완료. 커밋·푸시하면 다음 배포에 반영됩니다.")
        return 0

    if args.cmd == "recompute":
        lb["public_leaderboard"] = compute_public_board(lb, cfg)
        save_leaderboard(cfg, lb)
        print("Public 리더보드를 재계산했습니다.")
        return 0

    board = compute_private_board(lb, cfg)
    print(f"{'#':>3} {'참가자':<18} {'Private':>14} {'Public':>14} {'Pub순위':>6}  선택 제출")
    for r in board:
        print(f"{r['rank']:>3} {r['display']:<18} {fmt_score(r['private_score'], cfg):>14} {fmt_score(r['public_score'], cfg):>14} {str(r['public_rank']):>6}  {r['selected_ids']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
