"""GitHub REST API 최소 클라이언트 (댓글, 라벨, 닫기, PR 파일 목록, 파일 다운로드)."""
from __future__ import annotations

import os
import re

import requests

API = "https://api.github.com"
ATTACHMENT_RE = re.compile(
    r"https://github\.com/(?:user-attachments/files/\d+/[^\s)\]\"'>]+|[\w.-]+/[\w.-]+/files/\d+/[^\s)\]\"'>]+)"
)
CSV_URL_RE = re.compile(r"https?://[^\s)\]\"'>]+\.csv(?:\?[^\s)\]\"'>]*)?", re.IGNORECASE)


class GitHub:
    def __init__(self, repo: str, token: str | None = None, dry_run: bool = False):
        self.repo = repo
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.dry_run = dry_run or not self.token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ml-competition-scorer",
            }
        )
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    # -- 공통 ---------------------------------------------------------------
    def _call(self, method: str, path: str, **kwargs):
        url = path if path.startswith("http") else f"{API}{path}"
        if self.dry_run and method.upper() != "GET":
            print(f"[dry-run] {method} {url} {kwargs.get('json', '')}")
            return None
        resp = self.session.request(method, url, timeout=60, **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(f"GitHub API 오류 {resp.status_code} ({method} {url}): {resp.text[:300]}")
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # -- 이슈 / PR 공통 (PR 도 issue 번호를 공유) ----------------------------
    def comment(self, number: int, body: str) -> None:
        if self.dry_run:
            print(f"\n[dry-run] 댓글 → #{number}\n{body}\n")
            return
        self._call("POST", f"/repos/{self.repo}/issues/{number}/comments", json={"body": body})

    def add_labels(self, number: int, labels: list[str]) -> None:
        self._call("POST", f"/repos/{self.repo}/issues/{number}/labels", json={"labels": labels})

    def close(self, number: int, reason: str = "completed") -> None:
        self._call(
            "PATCH",
            f"/repos/{self.repo}/issues/{number}",
            json={"state": "closed", "state_reason": reason},
        )

    def close_pr(self, number: int) -> None:
        self._call("PATCH", f"/repos/{self.repo}/pulls/{number}", json={"state": "closed"})

    # -- PR 파일 ---------------------------------------------------------------
    def pr_files(self, number: int) -> list[dict]:
        files: list[dict] = []
        page = 1
        while True:
            batch = self._call("GET", f"/repos/{self.repo}/pulls/{number}/files?per_page=100&page={page}")
            if not batch:
                break
            files.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return files

    def fetch_repo_file(self, head_repo: str, path: str, ref: str, max_bytes: int) -> bytes:
        """contents API 로 원본 바이트를 받는다 (비공개 저장소도 토큰 권한 내에서 동작)."""
        url = f"{API}/repos/{head_repo}/contents/{path}?ref={ref}"
        headers = dict(self.session.headers)
        headers["Accept"] = "application/vnd.github.raw+json"
        resp = self.session.get(url, headers=headers, timeout=120, stream=True)
        if resp.status_code >= 400:
            raise RuntimeError(f"PR 파일을 가져오지 못했습니다 ({resp.status_code}): {path}")
        return _read_limited(resp, max_bytes)

    # -- 첨부파일 / 외부 URL --------------------------------------------------
    def download_url(self, url: str, max_bytes: int) -> bytes:
        """이슈 첨부파일 또는 외부 CSV URL 다운로드. 리다이렉트 시 Authorization 은 requests 가 제거."""
        headers = {"User-Agent": "ml-competition-scorer"}
        if self.token and url.startswith("https://github.com/"):
            headers["Authorization"] = f"Bearer {self.token}"
        resp = requests.get(url, headers=headers, timeout=120, stream=True, allow_redirects=True)
        if resp.status_code >= 400:
            raise RuntimeError(f"파일 다운로드 실패 (HTTP {resp.status_code})")
        ctype = resp.headers.get("Content-Type", "")
        data = _read_limited(resp, max_bytes)
        if "text/html" in ctype and data.lstrip()[:1] == b"<":
            raise RuntimeError("다운로드 결과가 CSV 가 아니라 HTML 페이지입니다 (로그인 필요 등).")
        return data


def _read_limited(resp: requests.Response, max_bytes: int) -> bytes:
    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=1 << 16):
        total += len(chunk)
        if total > max_bytes:
            raise RuntimeError(f"파일 크기가 제한({max_bytes // (1 << 20)}MB)을 초과합니다.")
        chunks.append(chunk)
    return b"".join(chunks)


def find_file_urls(text: str) -> list[str]:
    """이슈 본문에서 첨부파일 URL 과 .csv URL 을 찾는다 (첨부 우선)."""
    urls = []
    for m in ATTACHMENT_RE.finditer(text or ""):
        urls.append(m.group(0))
    for m in CSV_URL_RE.finditer(text or ""):
        u = m.group(0)
        if u not in urls:
            urls.append(u)
    return urls
