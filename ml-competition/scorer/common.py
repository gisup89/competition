"""공통 유틸리티: 경로, 설정 로딩, 암호화, 참가자 명단, 시간 처리."""
from __future__ import annotations

import hashlib
import io
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yaml
from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parents[1]
COMP_DIR = ROOT / "competitions"
SUBMISSION_DIR = ROOT / "submissions"
SITE_SRC = ROOT / "site"
KEY_FILE = ROOT / ".competition.key"
ISSUE_TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "submission.yml"

CONFIG_DEFAULTS = {
    "title": None,
    "subtitle": "",
    "metric": "rmse",
    "id_column": "id",
    "target_column": "target",
    "pos_label": 1,
    "timezone": "Asia/Seoul",
    "start": None,
    "deadline": None,
    "daily_limit": 5,
    "max_final_submissions": 2,
    "teams": True,
    "score_decimals": 5,
    "max_file_mb": 20,
    "allow_unregistered": False,
    "published": True,
}


class SubmissionError(Exception):
    """학생에게 그대로 보여줄 수 있는 제출 오류."""


# ---------------------------------------------------------------------------
# 암호화
# ---------------------------------------------------------------------------
def load_key(required: bool = True) -> bytes | None:
    key = os.environ.get("COMPETITION_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        if required:
            raise RuntimeError(
                "암호화 키가 없습니다. COMPETITION_KEY 환경변수(Actions Secret) 또는 "
                f"{KEY_FILE.name} 파일이 필요합니다. `python scorer/crypto_tool.py keygen`으로 생성하세요."
            )
        return None
    return key.encode()


def _fernet() -> Fernet:
    return Fernet(load_key())


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    try:
        return _fernet().decrypt(token)
    except InvalidToken as exc:
        raise RuntimeError("복호화 실패: 암호화 키가 파일을 암호화할 때 쓴 키와 다릅니다.") from exc


def encrypt_text(text: str) -> str:
    return encrypt_bytes(text.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str:
    return decrypt_bytes(token.encode("ascii")).decode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# 사이트 / 대회 설정
# ---------------------------------------------------------------------------
def load_site_config() -> dict:
    cfg = {
        "title": "머신러닝 경진대회",
        "description": "",
        "repo": "",
        "submission_mode": "issue",  # issue | pr | both
        "organizer": "",
    }
    path = ROOT / "site.yml"
    if path.exists():
        cfg.update(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    if not cfg.get("repo"):
        cfg["repo"] = os.environ.get("GITHUB_REPOSITORY", "")
    return cfg


def comp_dir(slug: str) -> Path:
    return COMP_DIR / slug


def list_competitions() -> list[str]:
    if not COMP_DIR.exists():
        return []
    return sorted(p.name for p in COMP_DIR.iterdir() if (p / "config.yml").exists())


def load_config(slug: str) -> dict:
    path = comp_dir(slug) / "config.yml"
    if not path.exists():
        raise SubmissionError(f"대회 `{slug}` 의 설정 파일(config.yml)을 찾을 수 없습니다.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = dict(CONFIG_DEFAULTS)
    cfg.update(raw)
    cfg["slug"] = slug
    if not cfg.get("title"):
        cfg["title"] = slug
    cfg["daily_limit"] = int(cfg["daily_limit"])
    cfg["max_final_submissions"] = max(1, int(cfg["max_final_submissions"]))
    cfg["score_decimals"] = int(cfg["score_decimals"])
    return cfg


def find_competition(text: str | None, published_only: bool = True) -> str | None:
    """사용자가 입력한 문자열(슬러그 또는 제목)로 대회 슬러그를 찾는다."""
    if not text:
        return None
    needle = text.strip().lower()
    slugs = list_competitions()
    for slug in slugs:
        if slug.lower() == needle:
            return slug
    for slug in slugs:
        cfg = load_config(slug)
        title = str(cfg.get("title", "")).strip().lower()
        if title and (title == needle or needle.startswith(title) or needle.endswith(f"({slug})")):
            return slug
    # "제목 (slug)" 형태
    if needle.endswith(")") and "(" in needle:
        inner = needle[needle.rfind("(") + 1 : -1].strip()
        if inner in [s.lower() for s in slugs]:
            return next(s for s in slugs if s.lower() == inner)
    return None


def load_solution(slug: str) -> pd.DataFrame:
    """정답 파일을 읽는다. 로컬 평문(solution.csv)이 있으면 우선, 없으면 .enc 복호화."""
    d = comp_dir(slug)
    plain = d / "solution.csv"
    enc = d / "solution.csv.enc"
    if plain.exists():
        return pd.read_csv(plain)
    if enc.exists():
        data = decrypt_bytes(enc.read_bytes())
        return pd.read_csv(io.BytesIO(data))
    raise RuntimeError(f"대회 `{slug}` 의 정답 파일(solution.csv.enc)이 없습니다.")


# ---------------------------------------------------------------------------
# 참가자 명단
# ---------------------------------------------------------------------------
ROSTER_COLUMNS = ["github", "student_id", "name", "display_name", "team"]


def load_roster() -> dict[str, dict]:
    """participants.csv(평문) 또는 participants.csv.enc(암호화)를 읽어 github 로그인 -> 행 dict."""
    plain = ROOT / "participants.csv"
    enc = ROOT / "participants.csv.enc"
    if plain.exists():
        df = pd.read_csv(plain, dtype=str)
    elif enc.exists():
        df = pd.read_csv(io.BytesIO(decrypt_bytes(enc.read_bytes())), dtype=str)
    else:
        return {}
    df.columns = [c.strip().lower() for c in df.columns]
    if "github" not in df.columns:
        raise RuntimeError("participants.csv 에 `github` 열이 없습니다.")
    for col in ROSTER_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df.fillna("")
    roster: dict[str, dict] = {}
    for _, row in df.iterrows():
        login = str(row["github"]).strip().lstrip("@")
        if not login:
            continue
        rec = {c: str(row[c]).strip() for c in ROSTER_COLUMNS}
        rec["github"] = login
        if not rec["display_name"]:
            rec["display_name"] = rec["name"] or login
        roster[login.lower()] = rec
    return roster


def team_members(roster: dict[str, dict], team: str) -> list[dict]:
    return [r for r in roster.values() if r.get("team") and r["team"] == team]


# ---------------------------------------------------------------------------
# 시간
# ---------------------------------------------------------------------------
def tz_of(cfg: dict) -> ZoneInfo:
    return ZoneInfo(cfg.get("timezone") or "Asia/Seoul")


def parse_dt(value, cfg: dict) -> datetime | None:
    """config 의 start/deadline 또는 GitHub ISO 문자열을 aware datetime 으로."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz_of(cfg))
    return dt


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_local(dt: datetime, cfg: dict) -> datetime:
    return dt.astimezone(tz_of(cfg))


def fmt_local(dt: datetime | None, cfg: dict) -> str:
    if dt is None:
        return "-"
    return to_local(dt, cfg).strftime("%Y-%m-%d %H:%M")


def fmt_score(value, cfg: dict) -> str:
    if value is None:
        return "-"
    return f"{value:.{cfg['score_decimals']}f}"
