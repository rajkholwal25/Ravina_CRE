"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const STORE = "dq_state_v1";

let CHAPTERS = [];
let S = null;            // active quiz/session state (persisted)
let tickTimer = null;

// ---------- persistence ----------
function save() { try { localStorage.setItem(STORE, JSON.stringify(S)); } catch (e) {} }
function load() { try { return JSON.parse(localStorage.getItem(STORE)); } catch (e) { return null; } }
function clearState() { S = null; localStorage.removeItem(STORE); }

// ---------- boot ----------
async function boot() {
  const me = await fetch("/api/me").then((r) => r.json()).catch(() => ({ user: null }));
  if (!me.user) { window.location.href = "/login"; return; }
  $("#userEmail").textContent = me.user.name ? `${me.user.name} · ${me.user.email}` : me.user.email;
  if (me.user.is_admin) $("#adminLink").classList.remove("hidden");

  await loadChapters();

  S = load();
  if (S && S.phase === "quiz" && S.queue && S.queue.length) {
    show("quiz"); startTicking(); renderQuestion();
  } else if (S && S.phase === "result" && S.result) {
    renderResult(S.result); show("result");
  } else {
    S = null; show("setup");
  }
}

async function loadChapters() {
  const data = await fetch("/api/chapters").then((r) => r.json());
  CHAPTERS = data.chapters;
  $("#totalQ").textContent = data.total;
  const list = $("#chapterList");
  list.innerHTML = "";
  let lastPart = null;
  for (const c of CHAPTERS) {
    if (c.part !== lastPart) {
      lastPart = c.part;
      const p = document.createElement("div");
      p.className = "partlabel";
      p.textContent = "Part " + c.part;
      list.appendChild(p);
    }
    const row = document.createElement("label");
    row.className = "chapline";
    row.innerHTML =
      `<input type="checkbox" class="chk" value="${c.num}" ${c.n ? "" : "disabled"}>
       <span class="cn">${c.num}</span>
       <span class="ct">${c.title}</span>
       <span class="cq">${c.n} Q</span>`;
    const cb = row.querySelector("input");
    cb.addEventListener("change", () => { row.classList.toggle("on", cb.checked); updateSelCount(); });
    list.appendChild(row);
  }
  updateSelCount();
}

const selectedChapters = () => [...$$(".chk:checked")].map((c) => c.value);
function updateSelCount() { $("#selCount").textContent = $$(".chk:checked").length; }
function syncRows() {
  $$(".chapline").forEach((r) => { const cb = r.querySelector("input"); if (cb) r.classList.toggle("on", cb.checked); });
  updateSelCount();
}
$("#selAll").onclick = () => { $$(".chk:not(:disabled)").forEach((c) => (c.checked = true)); syncRows(); };
$("#selNone").onclick = () => { $$(".chk").forEach((c) => (c.checked = false)); syncRows(); };

// ---------- start ----------
$("#startBtn").onclick = async () => {
  const chosen = selectedChapters();
  const chParam = chosen.length ? chosen.join(",") : "all";
  const limit = $("#limit").value;
  const data = await fetch(`/api/quiz?chapters=${chParam}&limit=${limit}`).then((r) => r.json());
  if (!data.count) { alert("No questions available for that selection."); return; }
  S = {
    phase: "quiz", queue: data.questions, idx: 0, answers: [],
    chapters: chParam, totalStart: Date.now(), qStart: Date.now(), pending: null, result: null,
  };
  save();
  show("quiz"); startTicking(); renderQuestion();
};

// ---------- timers ----------
function fmt(sec) { const m = Math.floor(sec / 60), s = sec % 60; return `${m}:${String(s).padStart(2, "0")}`; }
function tick() {
  if (!S) return;
  $("#totalTimer").textContent = fmt(Math.floor((Date.now() - S.totalStart) / 1000));
  $("#qTimer").textContent = fmt(Math.floor((Date.now() - S.qStart) / 1000));
}
function startTicking() { stopTicking(); tick(); tickTimer = setInterval(tick, 1000); }
function stopTicking() { if (tickTimer) { clearInterval(tickTimer); tickTimer = null; } }

// ---------- quiz ----------
function setScore() {
  const ok = S.answers.filter((a) => a.is_correct).length;
  const no = S.answers.filter((a) => !a.is_correct).length;
  $("#score").innerHTML = `<span class="s-ok">✓ ${ok}</span> &nbsp; <span class="s-no">✗ ${no}</span>`;
}

function renderQuestion() {
  const q = S.queue[S.idx];
  $("#counter").textContent = `Question ${S.idx + 1} of ${S.queue.length}`;
  setScore();
  $("#bar").style.width = `${(S.idx / S.queue.length) * 100}%`;
  $("#qchap").textContent = "Chapter " + q.chapter_num;
  const topicEl = $("#qtopic");
  if (q.topic) { topicEl.textContent = q.topic; topicEl.classList.remove("hidden"); } else topicEl.classList.add("hidden");
  $("#qtext").textContent = q.question;
  const box = $("#options");
  box.innerHTML = "";
  for (const [k, v] of Object.entries(q.options)) {
    const b = document.createElement("button");
    b.className = "opt"; b.dataset.key = k;
    b.innerHTML = `<span class="key">${k}</span><span class="otext">${v}</span>`;
    b.onclick = () => answer(k);
    box.appendChild(b);
  }
  $("#feedback").className = "feedback hidden";
  $("#nextBtn").classList.add("hidden");

  if (S.pending) { applyFeedback(S.pending); }   // restore answered-but-not-advanced state after refresh
}

async function answer(chosen) {
  const q = S.queue[S.idx];
  const timeSpent = Math.max(0, Math.round((Date.now() - S.qStart) / 1000));
  const res = await fetch("/api/answer", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: q.id, chosen }),
  }).then((r) => r.json());
  const record = {
    id: q.id, chapter_num: q.chapter_num, topic: q.topic, question: q.question,
    chosen, is_correct: res.is_correct, time_spent: timeSpent,
    correct_option: res.correct_option, correct_text: res.correct_text, explanation: res.explanation,
  };
  S.answers.push(record);
  S.pending = { ...record };
  save();
  applyFeedback(S.pending);
}

function applyFeedback(p) {
  $$(".opt").forEach((o) => {
    o.disabled = true;
    if (o.dataset.key === p.correct_option) o.classList.add("correct");
    else if (o.dataset.key === p.chosen) o.classList.add("wrong");
  });
  const fb = $("#feedback");
  if (p.is_correct) { fb.className = "feedback ok"; $("#fbhead").textContent = "✓ Correct"; }
  else { fb.className = "feedback no"; $("#fbhead").textContent = `✗ Incorrect — correct answer is ${p.correct_option}: ${p.correct_text}`; }
  $("#fbexpl").textContent = p.explanation;
  setScore();
  const nb = $("#nextBtn");
  nb.classList.remove("hidden");
  nb.textContent = (S.idx + 1 >= S.queue.length) ? "See results →" : "Next →";
  nb.focus();
}

$("#nextBtn").onclick = () => {
  S.idx++; S.pending = null; S.qStart = Date.now(); save();
  if (S.idx >= S.queue.length) finish();
  else renderQuestion();
};

$("#quitBtn").onclick = () => {
  if (!confirm("Quit this quiz? Your progress will be discarded.")) return;
  stopTicking(); clearState(); show("setup");
};

// ---------- finish + submit ----------
async function finish() {
  stopTicking();
  const duration = Math.round((Date.now() - S.totalStart) / 1000);
  const details = S.answers.map((a) => ({
    id: a.id, chapter_num: a.chapter_num, chosen: a.chosen, is_correct: a.is_correct, time_spent: a.time_spent,
  }));
  let saved = { id: null };
  try {
    saved = await fetch("/api/submit", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chapters: S.chapters, duration_seconds: duration, details }),
    }).then((r) => r.json());
  } catch (e) {}
  const ok = S.answers.filter((a) => a.is_correct).length;
  const total = S.answers.length;
  const wrong = S.answers.filter((a) => !a.is_correct).map((a) => ({
    q: a.question, ans: `${a.correct_option}. ${a.correct_text}`, expl: a.explanation,
  }));
  const weak = await fetch("/api/weak").then((r) => r.json()).catch(() => ({ weak: [] }));
  const result = {
    id: saved.id, score: ok, total, duration,
    pct: total ? Math.round((ok / total) * 100) : 0, wrong, weak: (weak.weak || []).slice(0, 6),
  };
  S = { phase: "result", result }; save();
  renderResult(result); show("result");
}

function renderResult(r) {
  $("#resultRing").style.setProperty("--pct", r.pct + "%");
  $("#resultPct").textContent = r.pct + "%";
  $("#resultScore").innerHTML = `You scored <b>${r.score}</b> out of <b>${r.total}</b>`;
  const msg = r.pct >= 85 ? "Excellent — you're exam-ready on these topics!" :
              r.pct >= 70 ? "Good work. Review the misses below to lock it in." :
              r.pct >= 50 ? "Getting there — study the explanations below." :
                            "Keep practicing — read through every explanation below.";
  $("#resultMsg").textContent = msg;
  const m = Math.floor(r.duration / 60), s = r.duration % 60;
  $("#resultMeta").innerHTML =
    `<span>⏱ Time: <b>${m}m ${s}s</b></span><span>Avg <b>${r.total ? Math.round(r.duration / r.total) : 0}s</b> / question</span>`;
  $("#dlResultBtn").style.display = r.id ? "" : "none";
  $("#dlResultBtn").onclick = () => downloadPdf(r.id);

  const rw = $("#reviewWrong");
  rw.innerHTML = "";
  if (r.weak && r.weak.length) {
    const wk = document.createElement("div");
    wk.className = "weakbox";
    wk.innerHTML = `<h3>Your weak areas (across all quizzes)</h3>` +
      r.weak.map((w) => weakRow(w)).join("");
    rw.appendChild(wk);
  }
  if (r.wrong && r.wrong.length) {
    const h = document.createElement("h3");
    h.className = "histsub"; h.textContent = `Review your ${r.wrong.length} missed question${r.wrong.length > 1 ? "s" : ""}`;
    rw.appendChild(h);
    for (const w of r.wrong) {
      const d = document.createElement("div"); d.className = "rev";
      const rq = document.createElement("div"); rq.className = "rq"; rq.textContent = w.q;
      const ra = document.createElement("div"); ra.className = "ra"; ra.textContent = "✓ Correct answer — " + w.ans;
      const re = document.createElement("div"); re.className = "re"; re.textContent = w.expl;
      d.append(rq, ra, re); rw.appendChild(d);
    }
  } else {
    const p = document.createElement("p"); p.className = "perfect"; p.textContent = "🎉 Perfect run — nothing to review!";
    rw.appendChild(p);
  }
}

function weakRow(w) {
  const cls = w.pct >= 50 ? "bad" : w.pct >= 25 ? "mid" : "good";
  return `<div class="weakrow"><span>Ch ${w.chapter}. ${w.title}</span>
          <span class="wpct ${cls}">${w.pct}% wrong (${w.wrong}/${w.total})</span></div>`;
}

function downloadPdf(id) {
  const a = document.createElement("a");
  a.href = `/api/results/${id}/pdf`; a.download = `dialysis-quiz-result-${id}.pdf`;
  document.body.appendChild(a); a.click(); a.remove();
}

$("#againBtn").onclick = async () => { clearState(); await loadChapters(); show("setup"); };
$("#toHistoryBtn").onclick = () => openHistory();

// ---------- history ----------
async function openHistory() {
  const [res, weak] = await Promise.all([
    fetch("/api/results").then((r) => r.json()),
    fetch("/api/weak").then((r) => r.json()),
  ]);
  const wb = $("#weakBox");
  if (weak.weak && weak.weak.length) {
    wb.innerHTML = `<h3>Your weak areas — study these chapters</h3>` +
      weak.weak.slice(0, 10).map((w) => weakRow(w)).join("");
    wb.style.display = "";
  } else { wb.innerHTML = ""; wb.style.display = "none"; }

  const list = $("#historyList");
  const rows = res.results || [];
  if (!rows.length) { list.innerHTML = `<p class="subnote">No quizzes yet — take one to see it here.</p>`; }
  else {
    list.innerHTML = rows.map((r) => {
      const d = new Date(r.created_at);
      const pct = r.total ? Math.round((100 * r.score) / r.total) : 0;
      const m = Math.floor(r.duration_seconds / 60), s = r.duration_seconds % 60;
      const chap = r.chapters === "all" ? "All chapters" : "Ch " + r.chapters;
      return `<div class="histrow">
          <div class="hinfo clickable" onclick="openResult(${r.id})">
            <div class="hscore">${r.score}/${r.total} <span class="hpct">(${pct}%)</span></div>
            <div class="hmeta">${chap} · ⏱ ${m}m ${s}s · ${d.toLocaleString()}</div>
          </div>
          <div class="rowbtns">
            <button class="ghost sm" onclick="openResult(${r.id})">View</button>
            <button class="ghost sm" onclick="downloadPdf(${r.id})">⬇ PDF</button>
          </div>
        </div>`;
    }).join("");
  }
  show("history");
}
window.downloadPdf = downloadPdf;

// ---------- result detail (view without downloading) ----------
async function openResult(id) {
  const data = await fetch(`/api/results/${id}`).then((r) => r.json());
  if (data.error || !data.result) { alert("Could not load that quiz."); return; }
  const r = data.result;
  const pct = r.total ? Math.round((100 * r.score) / r.total) : 0;
  const m = Math.floor(r.duration_seconds / 60), s = r.duration_seconds % 60;
  const chap = r.chapters === "all" ? "All chapters" : "Ch " + r.chapters;
  $("#detailTitle").textContent = `Quiz review — ${r.score}/${r.total} (${pct}%)`;
  $("#detailMeta").innerHTML =
    `<span>${chap}</span><span>⏱ Total <b>${m}m ${s}s</b></span>` +
    `<span>${new Date(r.created_at).toLocaleString()}</span>`;
  $("#detailPdfBtn").onclick = () => downloadPdf(id);
  $("#detailBody").innerHTML = data.items.map((it) => `
    <div class="rev ${it.is_correct ? "good" : ""}">
      <div class="rq">Q${it.n}. <span class="chip">Ch ${it.chapter_num}</span> ${escapeHtml(it.question)}
        <span class="qtime">⏱ ${it.time_spent}s</span></div>
      <div class="${it.is_correct ? "ra" : "rawrong"}">${it.is_correct ? "✓" : "✗"} Your answer: ${it.chosen || "—"}. ${escapeHtml(it.chosen_text || "(no answer)")}</div>
      ${it.is_correct ? "" : `<div class="ra">✓ Correct: ${it.correct}. ${escapeHtml(it.correct_text)}</div>`}
      <div class="re">${escapeHtml(it.explanation)}</div>
    </div>`).join("");
  show("detail");
}
window.openResult = openResult;
function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }
$("#detailBackBtn").onclick = () => openHistory();

$("#historyBtn").onclick = () => openHistory();
$("#backBtn").onclick = () => {
  if (S && S.phase === "quiz") { show("quiz"); }
  else if (S && S.phase === "result" && S.result) { show("result"); }
  else show("setup");
};

// ---------- logout ----------
$("#logoutBtn").onclick = async () => {
  await fetch("/api/logout", { method: "POST" });
  clearState();
  window.location.href = "/login";
};

// ---------- screens ----------
function show(name) {
  ["setup", "quiz", "result", "history", "detail"].forEach((s) => $("#" + s).classList.toggle("hidden", s !== name));
  window.scrollTo(0, 0);
}

boot();
