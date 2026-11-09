"""마감 후 최종(Private) 리더보드 생성.

  python -m scorer.finalize --competition <slug> [--unfinalize]

생성물
  competitions/<slug>/private_leaderboard.json   사이트에 공개되는 최종 순위 (표시명만 포함)
  competitions/<slug>/final_results.csv.enc      교수자용 성적 파일 (학번·이름 포함, 암호화)
  leaderboard.json 의 finalized 플래그 갱신
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys

from .common import comp_dir, encrypt_bytes, fmt_local, load_config, load_roster, now_utc, parse_dt, team_of
from .leaderboard import compute_private_board, load_leaderboard, save_leaderboard
from .metrics import get_metric


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--competition", required=True)
    ap.add_argument("--unfinalize", action="store_true", help="최종 결과 공개를 취소")
    ap.add_argument("--plain-results", action="store_true", help="final_results.csv 를 평문으로도 저장(로컬 전용)")
    ap.add_argument("--force", action="store_true", help="마감 전에도 최종 결과 파일을 생성 (로컬 미리 보기용; 사이트는 마감 전까지 표시하지 않음)")
    args = ap.parse_args(argv)

    cfg = load_config(args.competition)
    lb = load_leaderboard(cfg)
    d = comp_dir(cfg["slug"])

    deadline = parse_dt(cfg.get("deadline"), cfg)
    if not args.unfinalize and deadline and now_utc() < deadline and not args.force:
        print(
            f"아직 마감 전입니다 (마감: {fmt_local(deadline, cfg)}). 최종 결과는 마감 후에 생성하십시오.\n"
            "마감 전 미리 보기는 `python -m scorer.admin private --competition <slug>` 를 쓰거나, "
            "파일까지 만들려면 --force 를 붙이십시오 (커밋하면 안 됩니다).",
            file=sys.stderr,
        )
        return 1

    if args.unfinalize:
        lb["finalized"] = False
        save_leaderboard(cfg, lb)
        p = d / "private_leaderboard.json"
        if p.exists():
            p.unlink()
        print("최종 결과 공개를 취소했습니다.")
        return 0

    metric = get_metric(cfg["metric"])
    board = compute_private_board(lb, cfg)
    roster = load_roster()

    public_rows = []
    for r in board:
        public_rows.append(
            {
                "rank": r["rank"],
                "display": r["display"],
                "type": r["type"],
                "members": r["members"],
                "private_score": round(r["private_score"], 10),
                "public_score": round(r["public_score"], 10),
                "public_rank": r["public_rank"],
                "delta": r["delta"],
                "n_submissions": r["n_submissions"],
                "submission_id": r["submission_id"],
                "submission_url": r["submission_url"],
                "selected_ids": r["selected_ids"],
            }
        )
    (d / "private_leaderboard.json").write_text(
        json.dumps(
            {
                "competition": cfg["slug"],
                "metric": metric.key,
                "metric_name": metric.name,
                "higher_is_better": metric.higher_is_better,
                "finalized_at": now_utc().isoformat(timespec="seconds"),
                "max_final_submissions": cfg["max_final_submissions"],
                "leaderboard": public_rows,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    # 교수자용 성적 파일: 참가 단위별 + 구성원 개인별 행
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["rank", "participant", "type", "github", "student_id", "name", "team",
         "private_score", "public_score", "public_rank", "n_submissions", "submission_id", "submission_url"]
    )
    by_login = {k: v for k, v in roster.items()}
    for r in board:
        logins = []
        if r["type"] == "team":
            team = r["key"].split(":", 1)[1]
            logins = [v["github"] for v in roster.values() if team_of(v, cfg) == team]
        else:
            logins = [r["key"].split(":", 1)[1]]
        if not logins:
            logins = [""]
        for login in logins:
            row = by_login.get(login.lower(), {})
            w.writerow(
                [
                    r["rank"], r["display"], r["type"], login,
                    row.get("student_id", ""), row.get("name", ""), team_of(row, cfg),
                    f"{r['private_score']:.10g}", f"{r['public_score']:.10g}", r["public_rank"],
                    r["n_submissions"], r["submission_id"], r["submission_url"],
                ]
            )
    results = buf.getvalue().encode("utf-8-sig")
    (d / "final_results.csv.enc").write_bytes(encrypt_bytes(results))
    if args.plain_results:
        (d / "final_results.csv").write_bytes(results)

    lb["finalized"] = True
    lb["finalized_at"] = now_utc().isoformat(timespec="seconds")
    save_leaderboard(cfg, lb)

    print(f"최종 리더보드 생성 완료: {len(board)}개 참가 단위")
    for r in board[:10]:
        print(f"  {r['rank']:>3}. {r['display']:<20} private={r['private_score']:.6f} public={r['public_score']:.6f} (Δ{r['delta']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
