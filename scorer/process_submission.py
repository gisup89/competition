"""GitHub Actions 에서 실행되는 제출 처리기.

이슈(issues: opened) 또는 PR(pull_request_target) 이벤트를 읽어
  1) 대회·참가자·기간·일일 제출 한도 확인
  2) 제출 파일 다운로드 → 검증 → Public/Private 채점
  3) leaderboard.json 갱신 (Private 점수는 암호화 저장)
  4) 이슈/PR 에 결과 댓글, 라벨, 닫기
를 수행한다.

로컬 테스트:
  DRY_RUN=1 LOCAL_SUBMISSION_FILE=sub.csv python -m scorer.process_submission --event event.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from datetime import datetime

from .common import (
    SubmissionError,
    comp_dir,
    decrypt_submission,
    fmt_local,
    is_encrypted_submission,
    fmt_score,
    find_competition,
    list_competitions,
    load_config,
    load_roster,
    load_site_config,
    load_solution,
    now_utc,
    parse_dt,
    sha256_bytes,
    encrypt_text,
)
from .github_api import GitHub, find_file_urls
from .leaderboard import (
    compute_public_board,
    count_today,
    load_leaderboard,
    participant_info,
    rank_of,
    save_leaderboard,
)
from .metrics import get_metric, read_submission_csv, score_submission

FORM_FIELD_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# 이벤트 해석
# ---------------------------------------------------------------------------
def parse_form_body(body: str) -> dict[str, str]:
    """이슈 폼이 렌더링한 마크다운('### 라벨\\n\\n값')을 dict 로."""
    fields: dict[str, str] = {}
    if not body:
        return fields
    parts = FORM_FIELD_RE.split(body)
    # parts: [preamble, label1, value1, label2, value2, ...]
    for i in range(1, len(parts) - 1, 2):
        label = parts[i].strip()
        value = parts[i + 1].strip()
        if value == "_No response_":
            value = ""
        fields[label] = value
    return fields


def field_like(fields: dict[str, str], *keywords: str) -> str:
    for label, value in fields.items():
        low = label.lower()
        if any(k.lower() in low for k in keywords):
            return value
    return ""


def extract_context(event: dict) -> dict:
    """이슈/PR 이벤트에서 공통 정보 추출."""
    if "pull_request" in event:
        pr = event["pull_request"]
        return {
            "source": "pr",
            "number": pr["number"],
            "url": pr["html_url"],
            "login": pr["user"]["login"],
            "title": pr.get("title") or "",
            "body": pr.get("body") or "",
            "created_at": pr["created_at"] if event.get("action") == "opened" else now_utc().isoformat(),
            "head_repo": pr["head"]["repo"]["full_name"] if pr["head"].get("repo") else None,
            "head_sha": pr["head"]["sha"],
        }
    issue = event["issue"]
    return {
        "source": "issue",
        "number": issue["number"],
        "url": issue["html_url"],
        "login": issue["user"]["login"],
        "title": issue.get("title") or "",
        "body": issue.get("body") or "",
        "created_at": issue["created_at"],
        "head_repo": None,
        "head_sha": None,
    }


def determine_slug(ctx: dict, pr_files: list[dict] | None) -> str:
    slugs = [s for s in list_competitions() if load_config(s).get("published", True)]
    if not slugs:
        raise SubmissionError("현재 진행 중인 대회가 없습니다.")

    if ctx["source"] == "issue":
        fields = parse_form_body(ctx["body"])
        picked = field_like(fields, "대회", "competition")
        slug = find_competition(picked)
        if slug:
            return slug
        if picked:
            raise SubmissionError(
                f"선택한 대회 `{picked}` 를 찾을 수 없습니다. 이슈 템플릿의 대회 목록을 확인해 주세요."
            )
    else:
        for f in pr_files or []:
            m = re.match(r"^submissions/([^/]+)/.+\.csv$", f["filename"], re.IGNORECASE)
            if m:
                slug = find_competition(m.group(1))
                if slug:
                    return slug
        for text in (ctx["title"], ctx["body"]):
            for s in slugs:
                if s.lower() in (text or "").lower():
                    return s
    if len(slugs) == 1:
        return slugs[0]
    raise SubmissionError(
        "어느 대회에 제출하는지 알 수 없습니다. 이슈 폼에서 대회를 선택하거나, "
        "PR 은 `submissions/<대회슬러그>/` 폴더에 파일을 넣어 주세요. "
        f"(진행 중인 대회: {', '.join(slugs)})"
    )


# ---------------------------------------------------------------------------
# 파일 획득
# ---------------------------------------------------------------------------
def obtain_file(gh: GitHub, ctx: dict, cfg: dict, pr_files: list[dict] | None) -> tuple[bytes, str]:
    max_bytes = int(cfg["max_file_mb"]) * (1 << 20)
    local = os.environ.get("LOCAL_SUBMISSION_FILE")
    if local:
        with open(local, "rb") as fh:
            return fh.read(), os.path.basename(local)

    if ctx["source"] == "issue":
        urls = find_file_urls(ctx["body"])
        if not urls:
            raise SubmissionError(
                "제출 파일을 찾지 못했습니다. 이슈 본문의 '제출 파일' 칸에 CSV 파일을 끌어다 놓아 "
                "업로드 링크가 생성된 뒤 제출해 주세요. (.csv 로 끝나는 공개 URL 도 사용할 수 있습니다)"
            )
        url = urls[0]
        try:
            data = gh.download_url(url, max_bytes)
        except RuntimeError as exc:
            raise SubmissionError(
                f"첨부파일을 내려받지 못했습니다: {exc}\n\n"
                "첨부 대신 Pull Request 방식(`submissions/<대회>/` 폴더에 CSV 추가)으로 제출하거나, "
                "조교·교수자에게 문의해 주세요."
            ) from exc
        name = url.rsplit("/", 1)[-1].split("?")[0]
        return data, name

    # PR
    csvs = [
        f for f in (pr_files or [])
        if f["filename"].lower().endswith(".csv") and f.get("status") in ("added", "modified", "renamed")
    ]
    if not csvs:
        raise SubmissionError("PR 에 추가·수정된 CSV 파일이 없습니다. `submissions/<대회>/` 폴더에 CSV 하나를 넣어 주세요.")
    if len(csvs) > 1:
        raise SubmissionError(
            f"PR 에 CSV 파일이 {len(csvs)}개 있습니다. 제출은 PR 당 CSV 한 개만 가능합니다: "
            + ", ".join(f["filename"] for f in csvs[:5])
        )
    f = csvs[0]
    if not ctx["head_repo"]:
        raise SubmissionError("PR 의 원본 저장소 정보를 읽을 수 없습니다.")
    try:
        data = gh.fetch_repo_file(ctx["head_repo"], f["filename"], ctx["head_sha"], max_bytes)
    except RuntimeError:
        data = gh.download_url(f["raw_url"], max_bytes)
    return data, os.path.basename(f["filename"])


# ---------------------------------------------------------------------------
# 메시지
# ---------------------------------------------------------------------------
def site_url(site_cfg: dict) -> str:
    explicit = os.environ.get("SITE_URL") or site_cfg.get("site_url")
    if explicit:
        return explicit.rstrip("/") + "/"
    repo = site_cfg.get("repo") or ""
    if "/" in repo:
        owner, name = repo.split("/", 1)
        if name.lower() == f"{owner.lower()}.github.io":
            return f"https://{owner}.github.io/"
        return f"https://{owner}.github.io/{name}/"
    return ""


def success_comment(cfg, part, rec, board, remaining, site, duplicate_of, same_as_own) -> str:
    metric = get_metric(cfg["metric"])
    rank = rank_of(board, part["key"])
    who = part["display"] if part["type"] == "user" else f"팀 {part['display']} ({rec['github']})"
    lines = [
        "✅ **채점이 완료되었습니다.**",
        "",
        "| 항목 | 내용 |",
        "|---|---|",
        f"| 대회 | {cfg['title']} (`{cfg['slug']}`) |",
        f"| 참가자 | {who} |",
        f"| Public 점수 ({metric.name}) | **{fmt_score(rec['public_score'], cfg)}** |",
        f"| 현재 Public 순위 | **{rank}위** / {len(board)} |",
        f"| 제출 번호 | #{rec['id']} |",
    ]
    if cfg["daily_limit"] > 0:
        lines.append(f"| 오늘 남은 제출 | {remaining}회 (하루 {cfg['daily_limit']}회) |")
    lines.append("")
    if duplicate_of:
        lines.append(
            f"⚠️ **주의:** 이 파일은 다른 참가자의 이전 제출(#{duplicate_of})과 내용이 완전히 동일합니다. "
            "리더보드에 중복 표시가 남으며, 교수자가 확인할 수 있습니다."
        )
        lines.append("")
    elif same_as_own:
        lines.append(f"ℹ️ 본인의 이전 제출(#{same_as_own})과 동일한 파일입니다.")
        lines.append("")
    lines.append(
        "최종 순위는 마감 후 Private 데이터로 다시 계산됩니다 "
        f"(Public 점수 상위 {cfg['max_final_submissions']}개 제출물 가운데 Private 최고 점수)."
    )
    if site:
        lines.append("")
        lines.append(f"📊 리더보드: {site}competition.html?c={cfg['slug']}#leaderboard")
    return "\n".join(lines)


def failure_comment(reason: str, counts_against_limit: bool = False) -> str:
    lines = ["❌ **채점에 실패했습니다.**", "", f"**사유:** {reason}", ""]
    if counts_against_limit:
        lines.append("이 제출은 일일 제출 횟수에 포함되지 않았습니다.")
    else:
        lines.append("파일을 수정한 뒤 **새 이슈**로 다시 제출해 주세요. 실패한 제출은 일일 제출 횟수에 포함되지 않습니다.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def write_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")
    print(f"::output {key}={value}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", default=os.environ.get("GITHUB_EVENT_PATH"), help="이벤트 JSON 경로")
    ap.add_argument("--dry-run", action="store_true", default=bool(os.environ.get("DRY_RUN")))
    args = ap.parse_args(argv)
    if not args.event:
        print("이벤트 파일 경로가 필요합니다 (--event 또는 GITHUB_EVENT_PATH).", file=sys.stderr)
        return 2

    with open(args.event, encoding="utf-8") as fh:
        event = json.load(fh)

    site_cfg = load_site_config()
    repo = site_cfg.get("repo") or event.get("repository", {}).get("full_name", "")
    gh = GitHub(repo, dry_run=args.dry_run)
    ctx = extract_context(event)
    number = ctx["number"]
    write_output("changed", "false")

    pr_files = None
    cfg = None
    try:
        if ctx["source"] == "pr":
            local = os.environ.get("LOCAL_SUBMISSION_FILE")
            if local:
                pr_files = [{"filename": local, "status": "added", "raw_url": ""}]
            elif gh.dry_run:
                pr_files = []
            else:
                pr_files = gh.pr_files(number)

        slug = determine_slug(ctx, pr_files)
        cfg = load_config(slug)
        write_output("competition", slug)
        metric = get_metric(cfg["metric"])

        # 기간 확인
        created = parse_dt(ctx["created_at"], cfg)
        start = parse_dt(cfg.get("start"), cfg)
        deadline = parse_dt(cfg.get("deadline"), cfg)
        if not cfg.get("published", True):
            raise SubmissionError("이 대회는 아직 공개되지 않았습니다.")
        if start and created < start:
            raise SubmissionError(f"대회 시작 전입니다. 시작: {fmt_local(start, cfg)}")
        if deadline and created > deadline:
            raise SubmissionError(f"제출 마감이 지났습니다. 마감: {fmt_local(deadline, cfg)}")

        # 참가자 확인
        roster = load_roster()
        row = roster.get(ctx["login"].lower())
        if row is None and not cfg.get("allow_unregistered", False):
            if not roster:
                raise SubmissionError(
                    "참가자 명단(participants.csv 또는 participants.csv.enc)이 저장소에 없습니다. 교수자에게 문의해 주세요."
                )
            raise SubmissionError(
                f"GitHub 계정 `{ctx['login']}` 이(가) 참가자 명단에 없습니다. "
                "수강생 명단에 GitHub 아이디를 등록했는지 확인하고 교수자에게 문의해 주세요."
            )
        part = participant_info(ctx["login"], row, roster, cfg)

        # 파일 획득 (+ 암호화 제출이면 복호화)
        lb = load_leaderboard(cfg)
        data, filename = obtain_file(gh, ctx, cfg, pr_files)
        if is_encrypted_submission(data):
            data = decrypt_submission(data)
            filename = re.sub(r"(\.enc)?\.txt$", "", filename) + ".csv"
        elif site_cfg.get("require_encrypted", False):
            site = site_url(site_cfg)
            raise SubmissionError(
                "이 대회는 **암호화된 제출 파일**만 받습니다. 다른 참가자가 제출 내용을 볼 수 없게 하기 위한 조치입니다. "
                f"사이트의 '제출 파일 암호화' 페이지({site}encrypt.html?c={slug})에서 CSV 를 변환해 내려받은 "
                "`.enc.txt` 파일을 첨부해 주세요."
            )
        digest = sha256_bytes(data)

        # 같은 이슈(또는 같은 PR 의 같은 파일)를 다시 채점하는 경우(워크플로 재실행) 기존 기록을 교체
        reuse_id = None
        kept = []
        for s in lb["submissions"]:
            same = s.get("source") == ctx["source"] and s.get("number") == number
            if ctx["source"] == "pr":
                same = same and s.get("sha256") == digest
            if same:
                reuse_id = reuse_id or s["id"]
            else:
                kept.append(s)
        lb["submissions"] = kept

        # 일일 제출 한도
        used = count_today(lb, part["key"], created, cfg)
        if cfg["daily_limit"] > 0 and used >= cfg["daily_limit"]:
            raise SubmissionError(
                f"오늘({fmt_local(created, cfg)[:10]}, {cfg['timezone']}) 제출 한도 {cfg['daily_limit']}회를 "
                f"모두 사용했습니다. 자정 이후 다시 제출할 수 있습니다."
            )

        # 채점
        submission = read_submission_csv(data)
        solution = load_solution(slug)
        result = score_submission(solution, submission, cfg)

        # 중복 확인 (sample_submission.csv 와 같은 파일은 누구나 낼 수 있으므로 제외)
        duplicate_of = None
        same_as_own = None
        sample_path = comp_dir(slug) / "data" / "sample_submission.csv"
        is_sample = sample_path.exists() and sha256_bytes(sample_path.read_bytes()) == digest
        for s in lb["submissions"]:
            if is_sample or s.get("status") != "scored" or s.get("sha256") != digest:
                continue
            if s["participant_key"] != part["key"]:
                duplicate_of = duplicate_of or s["id"]
            else:
                same_as_own = same_as_own or s["id"]

        fields = parse_form_body(ctx["body"]) if ctx["source"] == "issue" else {}
        note = field_like(fields, "메모", "note", "설명", "description") if fields else ctx["title"]
        note = (note or "")[:200]

        new_id = reuse_id or lb["next_id"]
        rec = {
            "id": new_id,
            "source": ctx["source"],
            "number": number,
            "url": ctx["url"],
            "github": ctx["login"],
            "participant_key": part["key"],
            "participant_type": part["type"],
            "display": part["display"],
            "members": part["members"],
            "created_at": created.isoformat(timespec="seconds"),
            "filename": filename,
            "sha256": digest,
            "public_score": round(result["public"], 10),
            "private_enc": encrypt_text(json.dumps({"private": result["private"], "id": new_id})),
            "note": note,
            "status": "scored",
            "duplicate_of": duplicate_of,
        }
        if reuse_id is None:
            lb["next_id"] += 1
        lb["submissions"].append(rec)
        lb["submissions"].sort(key=lambda s: s["id"])
        lb["public_leaderboard"] = compute_public_board(lb, cfg)
        lb["metric"] = metric.key
        lb["metric_name"] = metric.name
        lb["higher_is_better"] = metric.higher_is_better
        save_leaderboard(cfg, lb)
        write_output("changed", "true")

        remaining = max(0, cfg["daily_limit"] - used - 1)
        gh.comment(
            number,
            success_comment(cfg, part, rec, lb["public_leaderboard"], remaining, site_url(site_cfg), duplicate_of, same_as_own),
        )
        labels = ["scored"] + (["duplicate"] if duplicate_of else [])
        gh.add_labels(number, labels)
        if ctx["source"] == "pr":
            gh.close_pr(number)
        else:
            gh.close(number, "completed")
        print(f"[ok] #{number} {part['display']} public={result['public']:.6f}")  # Private 점수는 로그에 남기지 않음(공개 저장소의 Actions 로그는 누구나 볼 수 있음)
        return 0

    except SubmissionError as exc:
        print(f"[rejected] #{number}: {exc}")
        gh.comment(number, failure_comment(str(exc)))
        gh.add_labels(number, ["rejected"])
        if ctx["source"] == "pr":
            gh.close_pr(number)
        else:
            gh.close(number, "not_planned")
        return 0
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        msg = (
            "채점 시스템 내부 오류가 발생했습니다. 교수자에게 알려 주세요.\n\n"
            f"```\n{type(exc).__name__}: {str(exc)[:500]}\n```"
        )
        gh.comment(number, failure_comment(msg))
        gh.add_labels(number, ["error"])
        return 1


if __name__ == "__main__":
    sys.exit(main())
