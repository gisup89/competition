/* 경진대회 사이트 프런트엔드 (정적, JSON 읽기 전용) */
const App = (() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const qs = (sel) => document.querySelector(sel);
  const bust = () => `?v=${Math.floor(Date.now() / 30000)}`; // 30초 단위 캐시 무효화

  async function getJSON(path, optional = false) {
    try {
      const r = await fetch(path + bust(), { cache: "no-store" });
      if (!r.ok) throw new Error(`${r.status} ${path}`);
      return await r.json();
    } catch (e) {
      if (optional) return null;
      throw e;
    }
  }
  async function getText(path) {
    const r = await fetch(path + bust(), { cache: "no-store" });
    if (!r.ok) return null;
    return await r.text();
  }

  // ---------- 날짜/상태 ----------
  function fmtDate(iso, tz, withTime = true) {
    if (!iso) return "-";
    const d = new Date(iso);
    if (isNaN(d)) return String(iso);
    const opt = { timeZone: tz || "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" };
    if (withTime) Object.assign(opt, { hour: "2-digit", minute: "2-digit", hour12: false });
    return d.toLocaleString("ko-KR", opt).replace(/\. /g, "-").replace(/\.$/, "").replace(/-(\d{2}:\d{2})/, " $1").replace(/\s+/g, " ").trim();
  }
  // 마감 시각이 지났는지 (마감이 없으면 지난 것으로 간주)
  function deadlinePassed(c) {
    return !c.deadline || new Date(c.deadline).getTime() < Date.now();
  }
  function statusOf(c) {
    const now = Date.now();
    // finalized 플래그가 켜져 있어도 마감 전에는 최종 결과를 공개하지 않습니다 (실수로 미리 확정한 경우 보호)
    if (c.finalized && deadlinePassed(c)) return { key: "final", label: "최종 결과 공개" };
    if (c.deadline && new Date(c.deadline).getTime() < now) return { key: "closed", label: "제출 마감" };
    if (c.start && new Date(c.start).getTime() > now) return { key: "soon", label: "시작 예정" };
    return { key: "live", label: "진행 중" };
  }
  function remaining(deadline) {
    if (!deadline) return "";
    let ms = new Date(deadline).getTime() - Date.now();
    if (ms <= 0) return "마감됨";
    const d = Math.floor(ms / 86400000); ms -= d * 86400000;
    const h = Math.floor(ms / 3600000); ms -= h * 3600000;
    const m = Math.floor(ms / 60000); ms -= m * 60000;
    const s = Math.floor(ms / 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return d > 0 ? `${d}일 ${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(h)}:${pad(m)}:${pad(s)}`;
  }
  const fmtScore = (v, dec) => (v === null || v === undefined ? "-" : Number(v).toFixed(dec ?? 5));
  const fmtSize = (b) => (b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : b >= 1024 ? (b / 1024).toFixed(0) + " KB" : b + " B");

  // ---------- 마크다운 ----------
  function renderMarkdown(md) {
    if (window.marked) {
      try { return marked.parse(md, { gfm: true, breaks: false }); } catch (e) { /* fallthrough */ }
    }
    // 최소 폴백: 제목, 목록, 코드블록, 굵게, 링크
    let html = esc(md);
    html = html.replace(/```([\s\S]*?)```/g, (_, c) => `<pre><code>${c.trim()}</code></pre>`);
    html = html.replace(/^### (.*)$/gm, "<h3>$1</h3>").replace(/^## (.*)$/gm, "<h2>$1</h2>").replace(/^# (.*)$/gm, "<h1>$1</h1>");
    html = html.replace(/^\s*[-*] (.*)$/gm, "<li>$1</li>").replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, "<ul>$1</ul>");
    html = html.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    return html.split(/\n{2,}/).map((p) => (/^<(h\d|ul|pre)/.test(p.trim()) ? p : `<p>${p.replace(/\n/g, "<br>")}</p>`)).join("\n");
  }

  function applySite(site) {
    if (!site) return;
    document.querySelectorAll("#brand-title").forEach((el) => (el.textContent = site.title || "머신러닝 경진대회"));
    const repo = qs("#nav-repo");
    if (repo) {
      if (site.repo) repo.href = `https://github.com/${site.repo}`; else repo.style.display = "none";
    }
    const footer = qs("#footer");
    if (footer) footer.textContent = [site.organizer, site.title].filter(Boolean).join(" · ");
  }

  // ---------- 대회 목록 ----------
  async function renderIndex() {
    const [site, index] = await Promise.all([getJSON("site.json", true), getJSON("competitions.json")]);
    applySite(site);
    if (site) {
      document.title = site.title;
      qs("#site-title").textContent = site.title;
      qs("#site-desc").textContent = site.description || "";
    }
    const comps = index.competitions || [];
    const order = { live: 0, soon: 1, closed: 2, final: 3 };
    comps.sort((a, b) => order[statusOf(a).key] - order[statusOf(b).key] || String(a.deadline).localeCompare(String(b.deadline)));
    const el = qs("#competitions");
    if (!comps.length) { el.innerHTML = '<div class="empty">아직 공개된 대회가 없습니다.</div>'; return; }
    el.innerHTML = comps.map((c) => {
      const st = statusOf(c);
      return `<a class="card" href="competition.html?c=${encodeURIComponent(c.slug)}">
        <div><span class="badge ${st.key}">${st.label}</span></div>
        <h3>${esc(c.title)}</h3>
        <div class="sub">${esc(c.subtitle || "")}</div>
        <div class="meta">
          <span>지표 <b>${esc(c.metric_name)}</b></span>
          <span>마감 <b>${fmtDate(c.deadline, c.timezone, false)}</b></span>
          <span>참가 <b>${c.n_participants}</b>${c.teams ? "팀/명" : "명"}</span>
          <span>제출 <b>${c.n_submissions}</b>회</span>
        </div></a>`;
    }).join("");
  }

  // ---------- 대회 페이지 ----------
  async function renderCompetition() {
    const slug = new URLSearchParams(location.search).get("c");
    const [site, index] = await Promise.all([getJSON("site.json", true), getJSON("competitions.json")]);
    applySite(site);
    const c = (index.competitions || []).find((x) => x.slug === slug);
    if (!c) { qs("#title").textContent = "대회를 찾을 수 없습니다"; return; }
    document.title = `${c.title} · ${site?.title || "경진대회"}`;
    const base = `competitions/${slug}/`;
    const [lb, readme, priv] = await Promise.all([
      getJSON(base + "leaderboard.json", true),
      getText(base + "README.md"),
      getJSON(base + "private_leaderboard.json", true),
    ]);
    const board = lb || { submissions: [], public_leaderboard: [], finalized: false };
    const st = statusOf({ ...c, finalized: board.finalized || c.finalized });

    // 헤더
    qs("#title").textContent = c.title;
    qs("#subtitle").textContent = c.subtitle || "";
    const badge = qs("#status-badge"); badge.textContent = st.label; badge.className = `badge ${st.key}`;
    const kv = qs("#kv");
    const renderKV = () => {
      kv.innerHTML = `
        <span>평가지표</span><b>${esc(c.metric_name)} (${c.higher_is_better ? "높을수록 좋음" : "낮을수록 좋음"})</b>
        <span>시작</span><b>${fmtDate(c.start, c.timezone)}</b>
        <span>마감</span><b>${fmtDate(c.deadline, c.timezone)}</b>
        <span>남은 시간</span><b class="countdown">${remaining(c.deadline)}</b>
        <span>하루 제출</span><b>${c.daily_limit > 0 ? c.daily_limit + "회" : "제한 없음"}</b>
        <span>참가 / 제출</span><b>${board.public_leaderboard.length}${c.teams ? "팀·명" : "명"} / ${board.submissions.filter((s) => s.status === "scored").length}회</b>`;
    };
    renderKV();
    setInterval(() => { const el = kv.querySelector(".countdown"); if (el) el.textContent = remaining(c.deadline); }, 1000);

    // 개요
    qs("#overview").innerHTML = readme ? renderMarkdown(readme) : "<p>대회 설명이 아직 없습니다.</p>";

    // 데이터
    const files = c.data_files || [];
    qs("#files").innerHTML = files.length
      ? files.map((f) => `<li><a href="${base}data/${encodeURIComponent(f.name)}" download>${esc(f.name)}</a><span class="size">${fmtSize(f.size)}</span></li>`).join("")
      : '<li class="empty">데이터 파일이 없습니다.</li>';
    qs("#data-hint").textContent = `제출 파일은 sample_submission.csv 와 같은 형식이어야 합니다 (열: ${c.id_column}, ${c.target_column}).`;

    // 리더보드
    renderLeaderboard(c, board, priv);

    // 제출 기록
    renderSubmissions(c, board);

    // 규칙 / 제출 방법
    renderRules(c, board, site);

    // 탭
    const tabs = [...document.querySelectorAll("#tabs a")];
    const show = (name) => {
      if (!tabs.some((t) => t.dataset.tab === name)) name = "overview";
      tabs.forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
    };
    window.addEventListener("hashchange", () => show(location.hash.slice(1)));
    show(location.hash.slice(1) || "overview");
  }

  function renderLeaderboard(c, board, priv) {
    const dec = c.score_decimals ?? 5;
    const btnPriv = qs("#btn-private");
    const hint = qs("#lb-hint");
    const search = qs("#lb-search");
    let mode = "public";
    const canPrivate = !!(board.finalized && priv && priv.leaderboard && deadlinePassed(c));
    btnPriv.disabled = !canPrivate;
    if (canPrivate) mode = "private";
    document.querySelectorAll("#lb-seg button").forEach((b) => {
      b.classList.toggle("active", b.dataset.board === mode);
      b.onclick = () => { if (b.disabled) return; mode = b.dataset.board; document.querySelectorAll("#lb-seg button").forEach((x) => x.classList.toggle("active", x === b)); draw(); };
    });
    search.oninput = draw;

    function draw() {
      const q = search.value.trim().toLowerCase();
      const updated = board.updated_at ? `갱신 ${fmtDate(board.updated_at, c.timezone)}` : "";
      if (mode === "public") {
        hint.textContent = `테스트 데이터 일부로 계산한 점수 · 참가자별 최고 점수 · ${updated}`;
        const rows = board.public_leaderboard.filter((r) => !q || r.display.toLowerCase().includes(q) || (r.members || []).join(" ").toLowerCase().includes(q));
        qs("#lb-table").innerHTML = rows.length ? `<table class="lb"><thead><tr>
            <th class="rank">#</th><th>참가자</th><th class="num">${esc(c.metric_name)}</th><th class="num">제출</th><th>최고 점수 시각</th></tr></thead><tbody>
          ${rows.map((r) => `<tr>
            <td class="rank r${r.rank}">${r.rank}</td>
            <td class="name">${nameCell(r)}</td>
            <td class="num score">${fmtScore(r.best_public, dec)}</td>
            <td class="num">${r.n_submissions}</td>
            <td>${fmtDate(r.best_at, c.timezone)}</td></tr>`).join("")}
          </tbody></table>` : '<div class="empty">아직 제출이 없습니다.</div>';
      } else {
        hint.textContent = `마감 후 Private 데이터로 계산한 최종 순위 (Public 상위 ${priv.max_final_submissions}개 제출물 중 최고) · 확정 ${fmtDate(priv.finalized_at, c.timezone)}`;
        const rows = priv.leaderboard.filter((r) => !q || r.display.toLowerCase().includes(q) || (r.members || []).join(" ").toLowerCase().includes(q));
        qs("#lb-table").innerHTML = rows.length ? `<table class="lb"><thead><tr>
            <th class="rank">#</th><th>변동</th><th>참가자</th><th class="num">Private</th><th class="num">Public</th><th class="num">제출</th></tr></thead><tbody>
          ${rows.map((r) => `<tr>
            <td class="rank r${r.rank}">${r.rank}</td>
            <td class="delta ${r.delta > 0 ? "up" : r.delta < 0 ? "down" : "same"}">${r.delta > 0 ? "▲" + r.delta : r.delta < 0 ? "▼" + (-r.delta) : "–"}</td>
            <td class="name">${nameCell(r)}</td>
            <td class="num score">${fmtScore(r.private_score, dec)}</td>
            <td class="num">${fmtScore(r.public_score, dec)}</td>
            <td class="num">${r.n_submissions}</td></tr>`).join("")}
          </tbody></table>` : '<div class="empty">최종 결과가 없습니다.</div>';
      }
    }
    draw();
  }

  function nameCell(r) {
    const team = r.type === "team";
    const members = team && r.members && r.members.length ? `<div class="members">${esc(r.members.join(", "))}</div>` : "";
    return `${team ? '<span class="badge team">팀</span> ' : ""}${esc(r.display)}${members}`;
  }

  function renderSubmissions(c, board) {
    const dec = c.score_decimals ?? 5;
    const subs = board.submissions.filter((s) => s.status === "scored").slice().reverse();
    const sel = qs("#sub-filter");
    const names = [...new Map(subs.map((s) => [s.participant_key, s.display])).entries()].sort((a, b) => a[1].localeCompare(b[1], "ko"));
    sel.innerHTML = '<option value="">전체 참가자</option>' + names.map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("");
    qs("#sub-hint").textContent = `채점된 제출 ${subs.length}건 · 최신순`;
    const draw = () => {
      const rows = sel.value ? subs.filter((s) => s.participant_key === sel.value) : subs;
      qs("#sub-table").innerHTML = rows.length ? `<table class="lb"><thead><tr>
          <th class="num">#</th><th>제출 시각</th><th>참가자</th><th class="num">${esc(c.metric_name)} (Public)</th><th>메모</th><th>링크</th></tr></thead><tbody>
        ${rows.map((s) => `<tr>
          <td class="num">${s.id}</td>
          <td>${fmtDate(s.created_at, c.timezone)}</td>
          <td class="name">${s.participant_type === "team" ? '<span class="badge team">팀</span> ' : ""}${esc(s.display)}${s.participant_type === "team" && s.submitter ? `<div class="members">${esc(s.submitter)}</div>` : ""}</td>
          <td class="num score">${fmtScore(s.public_score, dec)}</td>
          <td class="note">${esc(s.note || "")}${s.duplicate_of ? ` <span class="badge dup">#${s.duplicate_of}과 동일 파일</span>` : ""}</td>
          <td>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${s.source === "pr" ? "PR" : "이슈"} #${s.number}</a>` : ""}</td></tr>`).join("")}
        </tbody></table>` : '<div class="empty">제출 기록이 없습니다.</div>';
    };
    sel.onchange = draw;
    draw();
  }

  function renderRules(c, board, site) {
    const repo = site?.repo || "";
    const mode = site?.submission_mode || "issue";
    const st = statusOf({ ...c, finalized: board.finalized });
    const open = st.key === "live";
    const issueUrl = repo ? `https://github.com/${repo}/issues/new?template=submission.yml&competition=${encodeURIComponent(`${c.title} (${c.slug})`)}` : "#";
    const prUrl = repo ? `https://github.com/${repo}/tree/main/submissions/${c.slug}` : "#";

    qs("#rules").innerHTML = `
      <h2>규칙</h2>
      <ul>
        <li>평가지표: <b>${esc(c.metric_name)}</b> — ${esc(c.metric_description || "")} (${c.higher_is_better ? "높을수록" : "낮을수록"} 좋음)</li>
        <li>Public 리더보드는 테스트 데이터의 일부로, 최종(Private) 순위는 마감 후 나머지 데이터로 계산합니다.</li>
        <li>최종 평가에는 참가자(팀)별 Public 점수 상위 <b>${c.max_final_submissions}</b>개 제출물 가운데 Private 점수가 가장 좋은 것을 사용합니다.</li>
        <li>하루 제출 한도: <b>${c.daily_limit > 0 ? c.daily_limit + "회" : "제한 없음"}</b> (${esc(c.timezone || "Asia/Seoul")} 기준 자정 초기화${c.teams ? ", 팀은 팀 전체가 공유" : ""}). 채점에 실패한 제출은 횟수에 포함되지 않습니다.</li>
        <li>제출 기간: ${fmtDate(c.start, c.timezone)} ~ <b>${fmtDate(c.deadline, c.timezone)}</b></li>
        ${c.teams ? "<li>팀은 참가자 명단에 등록된 팀 기준으로 집계됩니다. 팀 변경은 교수자에게 요청하세요.</li>" : ""}
        <li>다른 참가자의 제출 파일과 내용이 동일한 파일은 자동으로 표시됩니다.</li>
      </ul>`;

    const enc = !!site?.require_encrypted;
    const encUrl = `encrypt.html?c=${encodeURIComponent(c.slug)}`;
    const issueSteps = enc ? `
      <ol class="steps">
        <li><a href="${encUrl}"><b>제출 파일 암호화</b></a> 페이지에서 CSV 를 선택해 <code>.enc.txt</code> 파일을 내려받습니다 (형식 검사도 함께 해 줍니다).</li>
        <li>GitHub 에 로그인한 상태에서 아래 <b>제출하기</b> 버튼을 누릅니다 (제출 이슈 양식이 열립니다). <b>대회</b>에 <code>${esc(c.title)} (${esc(c.slug)})</code> 가 선택되어 있는지 확인합니다.</li>
        <li><b>제출 파일</b> 칸에 1번에서 받은 <code>.enc.txt</code> 파일을 끌어다 놓고, 업로드 링크가 생길 때까지 기다립니다. (암호화하지 않은 CSV 는 채점되지 않습니다)</li>
        <li>메모(선택)를 적고 <b>Create</b> 를 누릅니다. 1~3분 뒤 이슈에 점수 댓글이 달리고 리더보드가 갱신됩니다.</li>
      </ol>` : `
      <ol class="steps">
        <li>GitHub 에 로그인한 상태에서 아래 <b>제출하기</b> 버튼을 누릅니다 (제출 이슈 양식이 열립니다).</li>
        <li><b>대회</b>에서 <code>${esc(c.title)} (${esc(c.slug)})</code> 가 선택되어 있는지 확인합니다.</li>
        <li><b>제출 파일</b> 칸에 CSV 파일을 끌어다 놓고, 업로드가 끝나 <code>[파일명](https://github.com/user-attachments/…)</code> 링크가 생길 때까지 기다립니다.</li>
        <li>메모(선택)를 적고 <b>Create</b> 를 누릅니다. 1~3분 뒤 이슈에 점수 댓글이 달리고 리더보드가 갱신됩니다.</li>
      </ol>`;
    const prSteps = `
      <ol class="steps">
        <li>저장소를 <b>Fork</b> 합니다 (처음 한 번).</li>
        <li>내 Fork 의 <code>submissions/${esc(c.slug)}/</code> 폴더에서 <b>Add file → Upload files</b> 로 ${enc ? "암호화한 <code>.enc.txt</code>" : "CSV"} 파일 하나를 올리고 커밋합니다.</li>
        <li><b>Contribute → Open pull request</b> 로 PR 을 엽니다. 1~3분 뒤 PR 에 점수 댓글이 달리고 PR 은 자동으로 닫힙니다.</li>
      </ol>`;
    qs("#howto").innerHTML = `
      <h2>제출 방법</h2>
      <p class="hint">GitHub 계정이 필요하며, 교수자가 등록한 참가자 명단에 있는 계정만 채점됩니다.</p>
      ${mode !== "pr" ? `<h3>${mode === "both" ? "방법 1 · " : ""}이슈로 제출</h3>${issueSteps}
        <p>${enc ? `<a class="btn secondary ${open ? "" : "disabled"}" href="${encUrl}">🔒 제출 파일 암호화</a> ` : ""}<a class="btn ${open && repo ? "" : "disabled"}" href="${issueUrl}" target="_blank" rel="noopener">📤 제출하기 (새 이슈 열기)</a></p>` : ""}
      ${mode !== "issue" ? `<h3>${mode === "both" ? "방법 2 · " : ""}Pull Request 로 제출</h3>${prSteps}
        <p><a class="btn secondary ${open && repo ? "" : "disabled"}" href="${prUrl}" target="_blank" rel="noopener">submissions/${esc(c.slug)}/ 폴더 열기</a></p>` : ""}
      ${open ? "" : `<div class="callout warn">현재 제출 기간이 아닙니다 (${st.label}).</div>`}
      <div class="callout">제출 파일 형식: <code>${esc(c.id_column)},${esc(c.target_column)}</code> 두 열을 가진 CSV. 행 수(${c.n_test ?? "?"}행)와 <code>${esc(c.id_column)}</code> 값은 test.csv 와 정확히 일치해야 합니다.</div>`;
  }

  // ---------- 제출 파일 암호화 페이지 ----------
  function pemToDer(pem) {
    const b64 = pem.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "");
    const bin = atob(b64); const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out.buffer;
  }
  function bytesToB64(bytes) {
    const u8 = new Uint8Array(bytes); let s = "";
    for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    return btoa(s);
  }
  async function encryptBytes(plain, pemText) {
    const pub = await crypto.subtle.importKey("spki", pemToDer(pemText), { name: "RSA-OAEP", hash: "SHA-256" }, false, ["encrypt"]);
    const aes = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, ["encrypt"]);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, aes, plain);
    const raw = await crypto.subtle.exportKey("raw", aes);
    const wrapped = await crypto.subtle.encrypt({ name: "RSA-OAEP" }, pub, raw);
    return `HNUENC1\n${bytesToB64(wrapped)}\n${bytesToB64(iv)}\n${bytesToB64(ct)}\n`;
  }
  function inspectCsv(text, c) {
    const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.trim().length);
    const header = (lines[0] || "").split(",").map((h) => h.trim().replace(/^"|"$/g, ""));
    const lower = header.map((h) => h.toLowerCase());
    const hasId = lower.includes(c.id_column.toLowerCase());
    const hasTarget = lower.includes(c.target_column.toLowerCase());
    const nRows = Math.max(0, lines.length - 1);
    const checks = [
      { ok: hasId, text: hasId ? `\`${c.id_column}\` 열 있음` : `\`${c.id_column}\` 열이 없습니다 (현재 열: ${header.slice(0, 6).join(", ")})` },
      { ok: hasTarget, text: hasTarget ? `\`${c.target_column}\` 열 있음` : `\`${c.target_column}\` 열이 없습니다` },
      { ok: c.n_test == null || nRows === c.n_test, text: c.n_test == null ? `${nRows}행` : (nRows === c.n_test ? `${nRows}행 (test.csv 와 일치)` : `${nRows}행 — test.csv 는 ${c.n_test}행입니다`) },
    ];
    return { checks, pass: checks.every((k) => k.ok) };
  }
  async function renderEncrypt() {
    const [site, index, pem] = await Promise.all([getJSON("site.json", true), getJSON("competitions.json"), getText("assets/submission_public.pem")]);
    applySite(site);
    const comps = (index.competitions || []);
    const sel = qs("#comp-select");
    sel.innerHTML = comps.map((c) => `<option value="${esc(c.slug)}">${esc(c.title)} (${esc(c.slug)})</option>`).join("");
    const want = new URLSearchParams(location.search).get("c");
    if (want && comps.some((c) => c.slug === want)) sel.value = want;
    if (!pem) { qs("#comp-hint").textContent = "공개키(assets/submission_public.pem)를 찾을 수 없습니다. 교수자에게 문의하세요."; return; }
    if (!window.isSecureContext || !crypto.subtle) { qs("#comp-hint").textContent = "이 브라우저에서는 암호화를 사용할 수 없습니다 (HTTPS 필요)."; return; }
    let file = null, text = null;
    const cur = () => comps.find((c) => c.slug === sel.value);
    const updateHint = () => { const c = cur(); qs("#comp-hint").textContent = c ? `제출 형식: ${c.id_column}, ${c.target_column} 두 열 · ${c.n_test ?? "?"}행` : ""; };
    const drop = qs("#drop"), input = qs("#file"), checks = qs("#checks"), btn = qs("#btn-encrypt"), result = qs("#result");
    const review = () => {
      checks.innerHTML = ""; btn.disabled = true; result.innerHTML = "";
      const c = cur(); if (!c || !text) return;
      const r = inspectCsv(text, c);
      checks.innerHTML = [{ ok: true, text: `파일: ${esc(file.name)} (${fmtSize(file.size)})` }, ...r.checks]
        .map((k) => `<li><span class="${k.ok ? "ok" : "bad"}">${k.ok ? "✓" : "✗"}</span><span>${k.text.replace(/`([^`]+)`/g, "<code>$1</code>")}</span></li>`).join("");
      btn.disabled = !r.pass;
    };
    const load = (f) => { file = f; const rd = new FileReader(); rd.onload = () => { text = rd.result; review(); }; rd.readAsText(f); };
    input.onchange = () => input.files[0] && load(input.files[0]);
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) load(f); });
    sel.onchange = () => { updateHint(); review(); };
    updateHint();
    btn.onclick = async () => {
      const c = cur(); if (!c || !text) return;
      btn.disabled = true; btn.textContent = "암호화 중…";
      try {
        const plain = new TextEncoder().encode(text);
        const out = await encryptBytes(plain, pem);
        const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "").slice(0, 12);
        const name = `submission_${c.slug}_${stamp}.enc.txt`;
        const blob = new Blob([out], { type: "text/plain" });
        const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove();
        const repo = site?.repo || "";
        const issueUrl = repo ? `https://github.com/${repo}/issues/new?template=submission.yml&competition=${encodeURIComponent(`${c.title} (${c.slug})`)}` : "#";
        result.innerHTML = `<div class="callout">암호화된 파일 <b class="mono">${esc(name)}</b> 을(를) 내려받았습니다. 이제 아래 버튼으로 제출 이슈를 열고 이 파일을 '제출 파일' 칸에 첨부하세요.</div>
          <p><a class="btn ${repo ? "" : "disabled"}" href="${issueUrl}" target="_blank" rel="noopener">📤 제출하기 (새 이슈 열기)</a></p>`;
      } catch (e) {
        result.innerHTML = `<div class="callout warn">암호화 중 오류가 발생했습니다: ${esc(e.message || e)}</div>`;
      } finally {
        btn.disabled = false; btn.textContent = "🔒 암호화해서 내려받기";
      }
    };
  }

  return { renderIndex, renderCompetition, renderEncrypt };
})();
