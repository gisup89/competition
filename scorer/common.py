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
# 제출 파일 암호화 (학생 → 교수자): RSA-OAEP(SHA-256) 로 감싼 AES-256-GCM 키
# ---------------------------------------------------------------------------
SUBMISSION_MAGIC = "HNUENC1"
SUBMISSION_PRIVATE_FILE = ROOT / ".submission_private.pem"
SUBMISSION_PRIVATE_ENC_FILE = ROOT / "submission_private.pem.enc"   # COMPETITION_KEY 로 암호화해 커밋
SUBMISSION_PUBLIC_FILE = SITE_SRC / "assets" / "submission_public.pem"


def is_encrypted_submission(data: bytes) -> bool:
    return data.lstrip()[: len(SUBMISSION_MAGIC)] == SUBMISSION_MAGIC.encode()


def load_submission_private_key():
    from cryptography.hazmat.primitives import serialization

    pem = os.environ.get("SUBMISSION_PRIVATE_KEY", "").strip()
    if not pem and SUBMISSION_PRIVATE_FILE.exists():
        pem = SUBMISSION_PRIVATE_FILE.read_text(encoding="utf-8").strip()
    if not pem and SUBMISSION_PRIVATE_ENC_FILE.exists():
        pem = decrypt_bytes(SUBMISSION_PRIVATE_ENC_FILE.read_bytes()).decode("utf-8").strip()
    if not pem:
        raise RuntimeError(
            "제출 파일 복호화 키가 없습니다. submission_private.pem.enc 가 저장소에 있어야 합니다 "
            "(python -m scorer.crypto_tool keygen-submission 으로 생성)."
        )
    return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)


def decrypt_submission(data: bytes) -> bytes:
    """HNUENC1 형식(4줄: 매직, RSA 로 감싼 AES 키, IV, 암호문)을 복호화해 CSV 바이트를 돌려준다."""
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    lines = [ln.strip() for ln in data.decode("ascii", errors="ignore").splitlines() if ln.strip()]
    if len(lines) < 4 or lines[0] != SUBMISSION_MAGIC:
        raise SubmissionError("암호화된 제출 파일의 형식이 올바르지 않습니다. 사이트의 '제출 파일 암호화' 페이지에서 다시 만들어 주세요.")
    try:
        wrapped, iv, ct = (base64.b64decode(x) for x in lines[1:4])
        key = load_submission_private_key().decrypt(
            wrapped, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
        )
        return AESGCM(key).decrypt(iv, ct, None)
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SubmissionError(
            "암호화된 제출 파일을 풀 수 없습니다. 파일이 손상되었거나 다른 대회 사이트의 키로 암호화된 파일입니다. "
            "사이트의 '제출 파일 암호화' 페이지에서 다시 만들어 주세요."
        ) from exc


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
        "require_encrypted": False,
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
    extra_team_cols = [c for c in df.columns if c.startswith("team_") or c.startswith("team:")]
    roster: dict[str, dict] = {}
    for _, row in df.iterrows():
        login = str(row["github"]).strip().lstrip("@")
        if not login:
            continue
        rec = {c: str(row[c]).strip() for c in ROSTER_COLUMNS + extra_team_cols}
        rec["github"] = login
        if not rec["display_name"]:
            rec["display_name"] = rec["name"] or login
        roster[login.lower()] = rec
    return roster


def team_of(row: dict | None, cfg: dict | None = None) -> str:
    """참가자의 팀 이름. 대회별 열(team_<slug>)이 있으면 우선, 없으면 공통 team 열."""
    if not row:
        return ""
    if cfg and cfg.get("slug"):
        for key in (f"team_{cfg['slug']}", f"team:{cfg['slug']}"):
            if key in row:
                return (row.get(key) or "").strip()
    return (row.get("team") or "").strip()


def team_members(roster: dict[str, dict], team: str, cfg: dict | None = None) -> list[dict]:
    return [r for r in roster.values() if team and team_of(r, cfg) == team]


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
