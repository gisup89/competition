"""재현 검증: 학생이 제출한 노트북을 다시 실행해 얻은 submission.csv 를, 리더보드에 올라간 원래 제출물과 비교.

  python -m scorer.verify_reproduction --competition hnu-digits --id 12 --rerun ./rerun/submission.csv
  python -m scorer.verify_reproduction --competition hnu-digits --id 12 --rerun ./rerun/submission.csv --encfile 내려받은.enc.txt

동작
  1) leaderboard.json 에서 제출 #id 의 이슈(또는 PR) 번호를 찾아 GitHub API 로 첨부파일 URL 을 얻고 내려받는다
     (API 가 막힌 환경이면 이슈에서 직접 내려받은 파일을 --encfile 로 넘긴다).
  2) 암호화 제출이면 로컬 개인키(.submission_private.pem 또는 submission_private.pem.enc)로 복호화한다.
  3) 원 제출물과 재실행 결과를 id 기준으로 맞춰 비교하고, 두 파일의 Public/Private 점수를 함께 계산한다.
판정 기준(참고): 회귀는 두 예측의 RMSE 차이가 제출 점수의 1% 이내, 분류는 예측 일치율 99% 이상이면 재현된 것으로 봅니다.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from .common import (
    decrypt_submission,
    is_encrypted_submission,
    load_config,
    load_site_config,
    load_solution,
    fmt_score,
)
from .github_api import GitHub, find_file_urls
from .leaderboard import load_leaderboard
from .metrics import get_metric, read_submission_csv, score_submission


def fetch_original(gh: GitHub, rec: dict, max_bytes: int) -> bytes:
    number = rec["number"]
    if rec.get("source") == "pr":
        files = gh.pr_files(number)
        cands = [f for f in files if f["filename"].lower().endswith((".csv", ".txt"))]
        if not cands:
            raise RuntimeError("PR 에서 제출 파일을 찾지 못했습니다.")
        return gh.download_url(cands[0]["raw_url"], max_bytes)
    issue = gh._call("GET", f"/repos/{gh.repo}/issues/{number}")
    urls = find_file_urls(issue.get("body") or "")
    if not urls:
        raise RuntimeError("이슈 본문에서 첨부파일 링크를 찾지 못했습니다. --encfile 로 직접 지정하세요.")
    return gh.download_url(urls[0], max_bytes)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--competition", required=True)
    ap.add_argument("--id", type=int, required=True, help="leaderboard.json 의 제출 번호")
    ap.add_argument("--rerun", required=True, help="노트북을 재실행해 얻은 submission.csv")
    ap.add_argument("--encfile", help="이슈에서 직접 내려받은 원 제출 파일(.enc.txt 또는 .csv)")
    args = ap.parse_args(argv)

    cfg = load_config(args.competition)
    metric = get_metric(cfg["metric"])
    lb = load_leaderboard(cfg)
    rec = next((s for s in lb["submissions"] if s["id"] == args.id), None)
    if rec is None:
        print(f"제출 #{args.id} 를 찾을 수 없습니다."); return 1
    print(f"제출 #{rec['id']} | {rec['display']} ({rec['github']}) | {rec['created_at']} | {rec.get('url','')}")

    if args.encfile:
        raw = open(args.encfile, "rb").read()
    else:
        site = load_site_config()
        gh = GitHub(site.get("repo") or "", dry_run=False)
        raw = fetch_original(gh, rec, int(cfg["max_file_mb"]) * (1 << 20))
    if is_encrypted_submission(raw):
        raw = decrypt_submission(raw)
    original = read_submission_csv(raw)
    rerun = read_submission_csv(open(args.rerun, "rb").read())
    solution = load_solution(cfg["slug"])

    id_col, tgt = cfg["id_column"], cfg["target_column"]
    o = original[[id_col, tgt]].copy(); r = rerun[[id_col, tgt]].copy()
    o[id_col] = o[id_col].astype(str); r[id_col] = r[id_col].astype(str)
    m = o.merge(r, on=id_col, suffixes=("_orig", "_rerun"))
    print(f"\n행 수: 원 제출 {len(o)} / 재실행 {len(r)} / 공통 id {len(m)}")

    if metric.kind == "label":
        a = m[f"{tgt}_orig"].astype(str).str.strip(); b = m[f"{tgt}_rerun"].astype(str).str.strip()
        agree = float((a == b).mean())
        print(f"예측 일치율: {agree:.4f} ({int((a == b).sum())}/{len(m)})")
        verdict = agree >= 0.99
    else:
        a = pd.to_numeric(m[f"{tgt}_orig"], errors="coerce").to_numpy(); b = pd.to_numeric(m[f"{tgt}_rerun"], errors="coerce").to_numpy()
        diff = float(np.sqrt(np.nanmean((a - b) ** 2)))
        corr = float(np.corrcoef(a, b)[0, 1]) if np.nanstd(a) > 0 and np.nanstd(b) > 0 else float("nan")
        print(f"두 예측 사이 RMSE: {diff:,.4f} | 최대 절대 차이: {np.nanmax(np.abs(a - b)):,.4f} | 상관계수: {corr:.5f}")
        verdict = None  # 아래 점수 비교로 판단

    print(f"\n{'':10s} {'Public':>14s} {'Private':>14s}")
    scores = {}
    for name, df in (("원 제출", original), ("재실행", rerun)):
        try:
            sc = score_submission(solution, df, cfg)
            scores[name] = sc
            print(f"{name:10s} {fmt_score(sc['public'], cfg):>14s} {fmt_score(sc['private'], cfg):>14s}")
        except Exception as exc:  # noqa: BLE001
            print(f"{name:10s} 채점 실패: {exc}")
    rec_pub = rec.get("public_score")
    if rec_pub is not None and "원 제출" in scores:
        print(f"(리더보드 기록 Public: {fmt_score(rec_pub, cfg)})")
    if metric.kind != "label" and "원 제출" in scores and "재실행" in scores:
        ref = abs(scores["원 제출"]["private"]) or 1.0
        verdict = abs(scores["원 제출"]["private"] - scores["재실행"]["private"]) <= 0.01 * ref and diff <= 0.01 * ref * 10
    print("\n판정(참고):", "재현됨" if verdict else "재현 안 됨 — 코드와 제출물이 다르거나 비결정적 요소가 큼. 학생에게 확인 필요")
    return 0


if __name__ == "__main__":
    sys.exit(main())
