"""leaderboard.json 입출력과 Public/Private 리더보드 계산."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import yaml

from .common import (
    comp_dir,
    decrypt_text,
    now_utc,
    parse_dt,
    team_members,
    to_local,
)
from .metrics import get_metric


def lb_path(slug: str) -> Path:
    return comp_dir(slug) / "leaderboard.json"


def empty_leaderboard(cfg: dict) -> dict:
    metric = get_metric(cfg["metric"])
    return {
        "competition": cfg["slug"],
        "metric": metric.key,
        "metric_name": metric.name,
        "higher_is_better": metric.higher_is_better,
        "updated_at": now_utc().isoformat(timespec="seconds"),
        "finalized": False,
        "next_id": 1,
        "submissions": [],
        "public_leaderboard": [],
    }


def load_leaderboard(cfg: dict) -> dict:
    path = lb_path(cfg["slug"])
    if path.exists():
        lb = json.loads(path.read_text(encoding="utf-8"))
        base = empty_leaderboard(cfg)
        for k, v in base.items():
            lb.setdefault(k, v)
        return lb
    return empty_leaderboard(cfg)


def save_leaderboard(cfg: dict, lb: dict) -> None:
    lb["updated_at"] = now_utc().isoformat(timespec="seconds")
    path = lb_path(cfg["slug"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lb, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# 참가 단위
# ---------------------------------------------------------------------------
def participant_info(login: str, roster_row: dict | None, roster: dict, cfg: dict) -> dict:
    """리더보드 집계 단위(팀 또는 개인)를 결정."""
    if roster_row and cfg.get("teams", True) and roster_row.get("team"):
        team = roster_row["team"]
        members = team_members(roster, team)
        return {
            "key": f"team:{team}",
            "type": "team",
            "display": team,
            "members": [m["display_name"] for m in members] or [roster_row["display_name"]],
            "member_logins": [m["github"] for m in members] or [login],
        }
    display = roster_row["display_name"] if roster_row else login
    return {
        "key": f"user:{login.lower()}",
        "type": "user",
        "display": display,
        "members": [display],
        "member_logins": [login],
    }


def scored(lb: dict) -> list[dict]:
    return [s for s in lb["submissions"] if s.get("status") == "scored"]


def count_today(lb: dict, key: str, when: datetime, cfg: dict) -> int:
    day = to_local(when, cfg).date()
    n = 0
    for s in scored(lb):
        if s["participant_key"] != key:
            continue
        created = parse_dt(s["created_at"], cfg)
        if created and to_local(created, cfg).date() == day:
            n += 1
    return n


def _better(a: float, b: float, higher: bool) -> bool:
    return a > b if higher else a < b


def compute_public_board(lb: dict, cfg: dict) -> list[dict]:
    higher = get_metric(cfg["metric"]).higher_is_better
    best: dict[str, dict] = {}
    for s in scored(lb):
        key = s["participant_key"]
        cur = best.get(key)
        if cur is None:
            best[key] = {
                "key": key,
                "display": s["display"],
                "type": s["participant_type"],
                "members": s.get("members", []),
                "best_public": s["public_score"],
                "best_submission_id": s["id"],
                "best_at": s["created_at"],
                "best_url": s.get("url"),
                "n_submissions": 1,
                "last_at": s["created_at"],
            }
        else:
            cur["n_submissions"] += 1
            cur["display"] = s["display"]  # 최신 표시명 반영
            cur["members"] = s.get("members", cur["members"])
            if s["created_at"] > cur["last_at"]:
                cur["last_at"] = s["created_at"]
            if _better(s["public_score"], cur["best_public"], higher):
                cur["best_public"] = s["public_score"]
                cur["best_submission_id"] = s["id"]
                cur["best_at"] = s["created_at"]
                cur["best_url"] = s.get("url")
    rows = sorted(
        best.values(),
        key=lambda r: ((-r["best_public"] if higher else r["best_public"]), r["best_at"]),
    )
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows


def rank_of(board: list[dict], key: str) -> int | None:
    for r in board:
        if r["key"] == key:
            return r["rank"]
    return None


# ---------------------------------------------------------------------------
# Private (최종) 리더보드
# ---------------------------------------------------------------------------
def load_selections(slug: str) -> dict[str, list[int]]:
    """선택적으로 교수자가 지정한 최종 평가 제출물 (participant_key -> [submission id])."""
    path = comp_dir(slug) / "selections.yml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = {}
    for k, v in data.items():
        if isinstance(v, int):
            v = [v]
        out[str(k)] = [int(x) for x in (v or [])]
    return out


def compute_private_board(lb: dict, cfg: dict) -> list[dict]:
    higher = get_metric(cfg["metric"]).higher_is_better
    k = cfg["max_final_submissions"]
    selections = load_selections(cfg["slug"])
    public_board = compute_public_board(lb, cfg)
    public_rank = {r["key"]: r["rank"] for r in public_board}

    by_key: dict[str, list[dict]] = {}
    for s in scored(lb):
        by_key.setdefault(s["participant_key"], []).append(s)

    rows = []
    for key, subs in by_key.items():
        chosen_ids = selections.get(key)
        if chosen_ids:
            candidates = [s for s in subs if s["id"] in chosen_ids]
        else:
            candidates = sorted(
                subs,
                key=lambda s: ((-s["public_score"] if higher else s["public_score"]), s["created_at"]),
            )[:k]
        if not candidates:
            continue
        best = None
        for s in candidates:
            prv = s.get("private_score")
            if prv is None and s.get("private_enc"):
                prv = float(json.loads(decrypt_text(s["private_enc"]))["private"])
            if prv is None:
                continue
            if best is None or _better(prv, best["private"], higher):
                best = {"private": prv, "sub": s}
        if best is None:
            continue
        latest = subs[-1]
        rows.append(
            {
                "key": key,
                "display": latest["display"],
                "type": latest["participant_type"],
                "members": latest.get("members", []),
                "private_score": best["private"],
                "public_score": best["sub"]["public_score"],
                "submission_id": best["sub"]["id"],
                "submission_url": best["sub"].get("url"),
                "selected_ids": [s["id"] for s in candidates],
                "n_submissions": len(subs),
                "public_rank": public_rank.get(key),
                "best_at": best["sub"]["created_at"],
            }
        )
    rows.sort(key=lambda r: ((-r["private_score"] if higher else r["private_score"]), r["best_at"]))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
        r["delta"] = (r["public_rank"] - i) if r["public_rank"] else None
    return rows
