/* Control Tower Studio. Plain JavaScript, no build step. */
"use strict";

const S = {
  map: null, stack: "baseline", prevTools: {}, state: null,
  job: null, selected: "day", statuses: {}, results: {}, logs: {}, progress: {}, activity: {}, alerts: {},
  logOpen: false,
};

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (path, body) => {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
};
const toast = (msg) => {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.remove("show"), 3200);
};
const longDate = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
const shortDate = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });

/* ------------------------------------------------------------ formatting */
function fmtNum(raw, fmt) {
  if (raw === null || raw === undefined) return "–";
  if (fmt === "percent") return (raw * 100).toFixed(1) + "%";
  if (fmt === "usd") {
    const a = Math.abs(raw);
    if (a >= 1e6) return "$" + (raw / 1e6).toFixed(2) + "M";
    if (a >= 1e3) return "$" + (raw / 1e3).toFixed(1) + "K";
    return "$" + raw.toFixed(0);
  }
  if (fmt === "days") return raw.toFixed(1) + " days";
  if (typeof raw === "number") return raw.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return String(raw);
}
const fmtFact = (f) => f.value ?? fmtNum(f.raw, f.fmt);
function fmtDelta(f) {
  if (typeof f.raw !== "number" || typeof f.prev !== "number") return "";
  const d = f.raw - f.prev;
  if (Math.abs(d) < 1e-12) return "";
  const sign = d > 0 ? "+" : "−";
  let text;
  if (f.fmt === "percent") { const p = Math.abs(d * 100); text = `${sign}${p < 0.05 ? p.toFixed(2) : p.toFixed(1)} pts`; }
  else if (f.fmt === "usd") text = sign + fmtNum(Math.abs(d), "usd");
  else if (f.fmt === "days") text = `${sign}${Math.abs(d).toFixed(1)} days`;
  else text = sign + Math.abs(d).toLocaleString("en-US", { maximumFractionDigits: 2 });
  const tone = !f.better ? "" : ((d > 0) === (f.better === "up") ? "good" : "bad");
  return `<span class="delta ${tone}">${text} since last run</span>`;
}

/* ================================================================= MAP */
const swapBadge = (swap) => {
  if (!swap || swap === "source" || swap === "baseline") return "";
  const c = S.map.swap_costs[swap] || { label: swap };
  const effort = swap === "rebuild" ? "" : c.effort;
  return `<span class="badge ${swap}">${esc(c.label)}${effort ? " · " + esc(effort) : ""}</span>`;
};
const nodeById = (id) => [...S.map.nodes, ...S.map.foundation].find((n) => n.id === id);

function cardHTML(n) {
  const t = n.stacks[S.stack];
  const cls = ["card", n.kind || "", t.swap === "none" ? "none" : "", S.stack !== "baseline" && ["adapter", "port", "rebuild"].includes(t.swap) ? "changed" : ""].join(" ");
  const flip = S.prevTools[n.id] && S.prevTools[n.id] !== t.tool ? " flip" : "";
  const tagline = n.kind === "heart" ? `<div class="tagline">Every metric defined once</div>` : "";
  return `<button class="${cls}" data-node="${n.id}" id="node-${n.id}">
    <div class="role">${esc(n.role)}</div><div class="tool${flip}${t.tool.length > 26 ? " long" : ""}">${esc(t.tool)}</div>${tagline}${swapBadge(t.swap)}</button>`;
}

function renderStacks() {
  $("#stacks").innerHTML = S.map.stacks.map((s) =>
    `<button data-stack="${s.id}" class="${s.id === S.stack ? "active" : ""}">${esc(s.label)}</button>`).join("");
  $("#stacknote").textContent = S.map.stacks.find((s) => s.id === S.stack).note;
}

function renderMap() {
  renderStacks();
  $("#cols").innerHTML = S.map.columns.map((c) => `
    <div><div class="col-head">${esc(c.label)}</div>
      <div class="col-body" data-col="${c.id}">${S.map.nodes.filter((n) => n.column === c.id).map(cardHTML).join("")}</div></div>`).join("");
  $("#foundation").innerHTML = S.map.foundation.map(cardHTML).join("");
  S.prevTools = Object.fromEntries([...S.map.nodes, ...S.map.foundation].map((n) => [n.id, n.stacks[S.stack].tool]));
  renderKeeps(); renderSwaps();
  requestAnimationFrame(drawWires);
}

function drawWires() {
  const map = $("#map"), mr = map.getBoundingClientRect();
  const box = (id) => {
    const r = $("#node-" + id).getBoundingClientRect();
    const l = r.left - mr.left, t = r.top - mr.top;
    return { l, t, r: l + r.width, b: t + r.height, cx: l + r.width / 2, cy: t + r.height / 2 };
  };
  let paths = "", pills = [];
  const groups = {};
  for (const e of S.map.edges) if (e.contract) (groups[e.contract] ||= []).push(e);
  for (const e of S.map.edges) {
    const a = box(e.from), b = box(e.to);
    let d, mid;
    if (e.vertical) {
      const [y0, y1] = a.cy < b.cy ? [a.b, b.t] : [a.t, b.b];
      d = `M${a.cx} ${y0} L${b.cx} ${y1}`; mid = [a.cx, (y0 + y1) / 2];
    } else {
      const x0 = a.r, y0 = a.cy, x1 = b.l - 2, y1 = b.cy, dx = (x1 - x0) / 2;
      d = `M${x0} ${y0} C${x0 + dx} ${y0} ${x1 - dx} ${y1} ${x1} ${y1}`; mid = [(x0 + x1) / 2, (y0 + y1) / 2];
    }
    const twoWay = e.contract === "C3";
    paths += `<path class="wire ${e.contract ? "contract" : ""}" d="${d}" marker-end="url(#arrow)" ${twoWay ? 'marker-start="url(#arrow)"' : ""}/>`;
    if (!e.contract) continue;
    const g = groups[e.contract];
    const shared = g.length > 1 && g.every((x) => x.to === e.to);
    if (shared) { if (g[0] === e) pills.push([e.contract, b.l - 24, b.cy]); }
    else pills.push([e.contract, ...mid]);
  }
  $("#wires").innerHTML = `<defs><marker id="arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
    <path d="M0 0 L10 5 L0 10 z" fill="#98a2b3"/></marker></defs>${paths}`;
  map.querySelectorAll(".pill").forEach((p) => p.remove());
  for (const [c, x, y] of pills) {
    const p = document.createElement("button");
    p.className = "pill"; p.textContent = c; p.dataset.contract = c;
    p.style.left = x + "px"; p.style.top = y + "px"; p.title = S.map.contracts[c].name;
    map.appendChild(p);
  }
}

function renderKeeps() {
  const n = S.map.counts;
  const labels = { contracts: "Contracts between components", metrics: "Metric definitions, with owners and caveats",
    golden: "Golden answers every tool must reproduce", star: "Tables in the star schema" };
  $("#keeps").innerHTML = S.map.keeps.map((k) =>
    `<div class="tile"><div class="n">${n[k.id] ?? "–"}</div><div class="l">${esc(labels[k.id] || k.label)}</div></div>`).join("");
}

function renderSwaps() {
  const stack = S.map.stacks.find((s) => s.id === S.stack);
  const nodes = [...S.map.nodes, ...S.map.foundation].filter((n) => n.kind !== "source");
  const contracts = Object.keys(S.map.contracts).length;
  if (S.stack === "baseline") {
    $("#swaptitle").textContent = "The open-source baseline";
    $("#swapsub").textContent = "Every box on this map is built and running in this project, on this laptop.";
    $("#swaplist").innerHTML = `<div class="headline">${nodes.length} components, <b>$0 in licences</b>. Pick another stack above to see what would change - and what would not.</div>
      <div class="swaprow"><span class="badge baseline">Built here</span><span class="names">${nodes.filter((n) => !n.fixed).map((n) => esc(n.stacks.baseline.tool)).join(", ")}</span></div>
      <div class="swaprow"><span class="badge stays">Part of the platform</span><span class="names">${nodes.filter((n) => n.fixed).map((n) => esc(n.role)).join(", ")}</span></div>`;
    return;
  }
  const by = {};
  for (const n of nodes) (by[n.stacks[S.stack].swap] ||= []).push(n);
  const changing = ["adapter", "port", "rebuild"].reduce((a, k) => a + (by[k]?.length || 0), 0);
  $("#swaptitle").textContent = stack.label;
  $("#swapsub").textContent = "What moving from the baseline to this stack would take, box by box.";
  const order = ["adapter", "port", "rebuild", "same", "none", "stays"];
  $("#swaplist").innerHTML = `<div class="headline"><b>${changing} of ${nodes.length}</b> components change tool. <b>0 of ${contracts}</b> contracts change.</div>` +
    order.filter((k) => by[k]).map((k) => `<div class="swaprow">${swapBadge(k)}<span class="names">${by[k].map((n) =>
      esc(k === "stays" || k === "none" ? n.role : n.stacks[S.stack].tool)).join(", ")}</span></div>`).join("");
}

function setStack(id) {
  if (id === S.stack) return;
  S.stack = id;
  renderMap();
  document.querySelectorAll(".pill").forEach((p) => { p.classList.remove("held"); void p.offsetWidth; p.classList.add("held"); });
}

/* -------------------------------------------------------------- drawer */
function openDrawer(html) {
  $("#drawer-body").innerHTML = html;
  $("#drawer").classList.add("open"); $("#scrim").classList.add("open");
  $("#drawer").setAttribute("aria-hidden", "false");
}
function closeDrawer() {
  $("#drawer").classList.remove("open"); $("#scrim").classList.remove("open");
  $("#drawer").setAttribute("aria-hidden", "true");
}

function contractsOf(n) {
  const ids = new Set();
  for (const e of S.map.edges) if (e.contract && (e.from === n.id || e.to === n.id)) ids.add(e.contract);
  for (const m of String(n.detail.contract || "").matchAll(/C[1-7]/g)) ids.add(m[0]);
  return [...ids].sort();
}

function openNode(id) {
  const n = nodeById(id);
  const t = n.stacks[S.stack];
  const contracts = contractsOf(n).map((c) => `<div class="contract-row"><span class="tag">${c}</span>
      <div><b>${esc(S.map.contracts[c].name)}</b><span>${esc(S.map.contracts[c].promise)}</span></div></div>`).join("");
  const proofs = contractsOf(n).map((c) => `<div class="contract-row"><span class="tag">${c}</span>
      <div><span>${esc(S.map.contracts[c].proof)}</span></div></div>`).join("");
  const stacks = n.kind === "source" ? "" : `<h4>Across the stack options</h4><table class="stack-table">${S.map.stacks.map((s) =>
    `<tr><td>${esc(s.label)}</td><td><div class="t">${esc(n.stacks[s.id].tool)}</div>${s.id === "baseline" ? "" : swapBadge(n.stacks[s.id].swap)}</td></tr>`).join("")}</table>`;
  const other = n.detail.other?.length ? `<h4>Also worth a look</h4><p>${n.detail.other.map(esc).join(", ")}</p>` : "";
  const note = n.swap_note || n.detail.note ? `<h4>Worth knowing</h4><div class="note">${esc(n.swap_note || n.detail.note)}</div>` : "";
  const test = n.detail.test ? `<div class="proof"><span class="mono">${esc(n.detail.test)}</span></div>` : "";
  const step = n.step && S.state?.clock?.initialised ? `<h4>See it run</h4><button class="btn" data-goto-step="${n.step}">Open the “${esc(stepById(n.step).title)}” step</button>` : "";
  openDrawer(`<div class="eyebrow">${esc(n.role)}${n.kind === "source" ? " · the client's system" : ""}</div>
    <h2>${esc(t.tool)}</h2><p>${esc(n.what)}</p>
    ${contracts ? `<h4>Its contracts</h4>${contracts}` : ""}
    ${proofs ? `<h4>How we prove it</h4>${proofs}${test}` : ""}
    ${stacks}${note}${other}${step}`);
}

function openContract(id) {
  const c = S.map.contracts[id];
  const ends = S.map.edges.filter((e) => e.contract === id);
  const names = (key) => [...new Set(ends.map((e) => nodeById(e[key]).role))].join(", ");
  openDrawer(`<div class="eyebrow">Contract ${id}</div><h2>${esc(c.name)}</h2>
    <p>${esc(c.promise)}</p>
    <h4>Between</h4><p>${esc(names("from"))} → ${esc(names("to"))}</p>
    <h4>How we prove it</h4><p>${esc(c.proof)}</p>
    <h4>In every stack</h4><div class="note">The contract does not change when a tool does. A replacement tool has to meet it, and the same test proves it.</div>`);
}

/* ============================================================ RUN VIEW */
const stepById = (id) => S.state.steps.find((s) => s.id === id);
const stepIndex = (id) => S.state.steps.findIndex((s) => s.id === id);

function lastStep() {
  let best = null;
  for (const [id, r] of Object.entries(S.results)) if (!best || r.finished_at > S.results[best].finished_at) best = id;
  return best;
}
function nextStep() {
  const last = lastStep();
  if (!last) return "day";
  if (S.results[last].status === "failed") return last;
  return S.state.steps[(stepIndex(last) + 1) % S.state.steps.length].id;
}

function renderDay() {
  const c = S.state.clock;
  const busy = !!S.job;
  $("#daydot").className = "dot" + (busy ? " busy" : "");
  $("#daytext").innerHTML = c.initialised ? `Business day <b>${shortDate(c.today)}</b>${busy ? " · running" : ""}` : "Not set up yet";
  if (!c.initialised) return;
  $("#bizdate").textContent = longDate(c.today);
  $("#daytrack").style.width = `${(100 * c.day) / c.days}%`;
  $("#daycount").textContent = `Day ${c.day} of ${c.days} in the simulated timeline`;
}

function renderControls() {
  const c = S.state.clock, busy = !!S.job, atEnd = c.initialised && c.day >= c.days;
  $("#day-btn").disabled = busy || atEnd;
  $("#day-btn").textContent = atEnd ? "End of the timeline" : "Run a full day";
  const nx = c.initialised ? nextStep() : null;
  $("#next-btn").disabled = busy || (nx === "day" && atEnd);
  $("#next-btn").textContent = nx ? `Next: ${stepById(nx).title}` : "Next step";
  $("#reset-btn").disabled = busy;
  document.querySelectorAll("#matcher button").forEach((b) => {
    b.classList.toggle("active", b.dataset.provider === S.state.provider); b.disabled = busy;
  });
}

function chipStatus(id) { return S.statuses[id] || S.results[id]?.status || "idle"; }
function shieldStatus(step, cid) {
  if (["running", "checking"].includes(S.statuses[step])) return S.statuses[step] === "checking" ? "checking" : "";
  const r = S.results[step]?.checks?.find((c) => c.id === cid);
  return r ? (r.passed ? "pass" : "fail") : "";
}

function renderStrip() {
  $("#strip").innerHTML = S.state.steps.map((s, i) => {
    const st = chipStatus(s.id);
    const shields = s.checks.map((c) => `<span class="shield ${shieldStatus(s.id, c)}" title="Boundary check">${c === "quality" ? "tests" : c}</span>`).join("");
    const link = shields ? `<div class="link">${shields}</div>` : i < S.state.steps.length - 1 ? `<div class="link bare"></div>` : "";
    const mark = st === "ok" ? "✓" : st === "failed" ? "!" : i + 1;
    return `<button class="stepchip ${st} ${s.id === S.selected ? "selected" : ""}" data-step="${s.id}">
      <span class="num">${mark}</span><span class="name">${esc(s.title)}</span></button>${link}`;
  }).join("");
}

function renderStatus() {
  const id = S.selected, st = chipStatus(id), r = S.results[id];
  const line = $("#step-status"), bar = $("#step-bar");
  let text;
  if (st === "running") text = `<b>Running…</b><span class="activity">${esc(S.activity[id] || "")}</span>`;
  else if (st === "checking") text = "<b>Running the boundary checks…</b>";
  else if (st === "failed") text = `<b style="color:var(--bad)">Stopped</b>${r?.finished_at ? `<span class="faint">at ${r.finished_at.slice(11)}</span>` : ""}`;
  else if (r) text = `<span style="color:var(--ok);font-weight:600">Done</span><span class="faint">at ${r.finished_at.slice(11)}</span>`;
  else text = `<span class="faint">Not run yet</span>`;
  line.innerHTML = text;
  const p = S.progress[id];
  bar.className = "bar" + (st === "running" ? (p ? "" : " indeterminate") : st === "checking" ? " indeterminate" : " hidden");
  bar.firstElementChild.style.width = st === "running" && p ? `${(100 * p[0]) / p[1]}%` : "";
}

function renderLog() {
  const lines = S.logs[S.selected] || [];
  $("#log").innerHTML = lines.length ? lines.map((l) => l.startsWith("$ ") ? `<span class="cmd">${esc(l)}</span>` : esc(l)).join("\n")
    : `<span class="faint">The commands this step runs, and everything they print, appear here while it runs.</span>`;
  $("#log").classList.toggle("open", S.logOpen);
  $("#techtoggle").textContent = S.logOpen ? "Hide technical log" : "Show technical log";
  if (S.logOpen) $("#log").scrollTop = $("#log").scrollHeight;
}

function checkHTML(cid, result) {
  const meta = S.map.contracts[cid];
  const isContract = !!meta;
  const kind = isContract ? `<span class="tag">${cid}</span>Boundary check · ${esc(meta.name)}` : "Quality tests";
  if (!result) {
    return `<div class="check"><div class="check-top"><div class="kind">${kind}</div><span class="verdict">Not run yet</span></div>
      <p class="promise" style="margin-top:10px">${esc(isContract ? meta.promise : "Every cleaned table is tested for missing keys, duplicates and broken references.")}</p></div>`;
  }
  const v = result.passed ? "pass" : "fail";
  const rows = result.facts.map((f) => `<div class="row"><span>${esc(f.label)}</span><span>${esc(fmtFact(f))}</span></div>`).join("");
  const problems = result.problems.length ? `<ul class="problems">${result.problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : "";
  return `<div class="check ${v}"><div class="check-top"><div class="kind">${kind}</div><span class="verdict ${v}">${result.passed ? "Held" : "Broken"}</span></div>
    <h3>${esc(result.title)}</h3>${isContract ? `<p class="promise">${esc(meta.promise)}</p>` : ""}
    <div class="rows">${rows}</div>${problems}
    ${result.test ? `<div class="ci">The same check runs in CI: <span class="mono">${esc(result.test)}</span></div>` : ""}</div>`;
}

function renderDetail() {
  const s = stepById(S.selected), i = stepIndex(S.selected), r = S.results[S.selected];
  const node = nodeById(s.node);
  $("#step-eyebrow").textContent = `Step ${i + 1} of ${S.state.steps.length}`;
  $("#step-title").textContent = s.title;
  $("#step-lead").textContent = s.lead;
  const comp = $("#step-comp");
  comp.hidden = !node;
  if (node) { comp.innerHTML = `<i>${esc(node.stacks.baseline.tool)}</i>${esc(node.role)}`; comp.dataset.node = node.id; }
  const facts = r?.facts || [];
  $("#step-facts").innerHTML = facts.length ? facts.map((f) => `<div class="fact"><div class="v ${f.fmt === "text" ? "text" : ""}">${esc(fmtFact(f))}</div>
      <div class="l">${esc(f.label)}</div>${fmtDelta(f)}</div>`).join("")
    : `<div class="empty">Run this step to see what it does.</div>`;
  const alert = S.alerts[S.selected] || (r?.status === "failed" ? (r.error || "A boundary check failed, so the pipeline stopped here.") : "");
  $("#step-alert").innerHTML = alert ? `<div class="alert">${esc(alert)}</div>` : "";
  $("#step-checks").innerHTML = s.checks.length
    ? s.checks.map((c) => checkHTML(c, r?.checks?.find((x) => x.id === c))).join("")
    : `<div class="panel"><h3>No boundary here</h3><p class="nocheck">This is the source systems doing their normal business. The first check comes when the changes are collected: contract C2 proves nothing was lost on the way in.</p></div>`;
  renderStatus(); renderLog();
}

function renderRun() {
  if (!S.state) return;
  renderDay();
  const ready = S.state.clock.initialised || S.job;
  $("#run-setup").hidden = !!ready;
  $("#run-main").hidden = !ready;
  if (!ready) return;
  renderControls(); renderStrip(); renderDetail();
}

/* ---------------------------------------------------------------- jobs */
async function refreshState() {
  S.state = await api("/api/state");
  S.results = S.state.results || {};
  renderRun();
}

async function startJob(body) {
  try {
    const job = await api("/api/run", body);
    attach(job.id, job.steps);
  } catch (e) { toast(e.message); }
}

function attach(id, steps) {
  S.job = { id, steps };
  for (const s of steps) { const k = s === "reset" ? "day" : s; delete S.statuses[k]; delete S.alerts[k]; }
  renderRun();
  const es = new EventSource(`/api/jobs/${id}/events`);
  let pending = false;
  es.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    const step = ev.step === "reset" ? "day" : ev.step;
    if (ev.type === "step") {
      S.statuses[step] = ev.status;
      if (ev.status === "running") {
        S.selected = step; S.logs[step] = []; S.progress[step] = null; S.activity[step] = "";
      }
      if (ev.status === "failed") S.alerts[step] = ev.reason;
      renderRun();
    } else if (ev.type === "log") {
      (S.logs[step] ||= []).push(ev.line);
      if (!ev.line.startsWith("$ ")) S.activity[step] = ev.line;
      if (ev.progress) S.progress[step] = ev.progress;
      if (step === S.selected && !pending) {
        pending = true;
        requestAnimationFrame(() => { pending = false; renderStatus(); if (S.logOpen) renderLog(); });
      }
    } else if (ev.type === "result") {
      if (ev.step === "reset") S.results = {};
      const held = ev.result.checks.every((c) => c.passed) && !ev.result.error;
      S.results[step] = { ...ev.result, status: held ? "ok" : "failed" };
      if (step === "day" || ev.step === "reset") refreshClock();
      renderRun();
    } else if (ev.type === "done") {
      es.close();
      S.job = null;
      S.statuses = {};
      if (!ev.ok) toast("The run stopped. The step marked in red says why.");
      refreshState();
    }
  };
  es.onerror = () => { /* the browser reconnects; the server replays from the start */ };
}

async function refreshClock() {
  const st = await api("/api/state");
  S.state.clock = st.clock;
  renderDay(); renderControls();
}

const ALL = () => S.state.steps.map((s) => s.id);
const FROM = (id) => ALL().slice(stepIndex(id));

/* --------------------------------------------------------------- events */
document.addEventListener("click", (e) => {
  const t = e.target.closest("button, .pill");
  if (!t) return;
  if (t.dataset.view) return showView(t.dataset.view);
  if (t.dataset.stack) return setStack(t.dataset.stack);
  if (t.dataset.node) return openNode(t.dataset.node);
  if (t.dataset.contract) return openContract(t.dataset.contract);
  if (t.dataset.gotoStep) { closeDrawer(); S.selected = t.dataset.gotoStep; showView("run"); return; }
  if (t.dataset.step) { S.selected = t.dataset.step; renderStrip(); renderDetail(); return; }
  if (t.dataset.provider) return swapMatcher(t.dataset.provider);
  switch (t.id) {
    case "drawer-close": return closeDrawer();
    case "day-btn": return startJob({ steps: ALL() });
    case "next-btn": return startJob({ steps: [nextStep()] });
    case "setup-btn": return startJob({ reset: true, steps: FROM("collect") });
    case "reset-btn":
      if (confirm("Reset to day 0? This rebuilds everything from the start - about a minute.")) startJob({ reset: true, steps: FROM("collect") });
      return;
    case "techtoggle": S.logOpen = !S.logOpen; return renderLog();
  }
});
$("#scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDrawer();
  if (e.key === "ArrowRight" && $("#view-run").classList.contains("active") && !S.job && S.state?.clock?.initialised && !$("#next-btn").disabled) {
    startJob({ steps: [nextStep()] });
  }
});

async function swapMatcher(provider) {
  if (provider === S.state.provider || S.job) return;
  try {
    await api("/api/provider", { provider });
    S.state.provider = provider;
    toast(`Swapped to the ${provider === "rules" ? "rules matcher" : "Splink matcher"} - re-running from “Match”`);
    if (S.state.clock.initialised) startJob({ steps: FROM("match") });
    else renderControls();
  } catch (err) { toast(err.message); }
}

function showView(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  try { localStorage.setItem("studio.view", name); } catch { /* private window */ }
  if (name === "map") requestAnimationFrame(drawWires);
  else renderRun();
}

let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(drawWires, 80); });

(async function init() {
  S.map = await api("/api/map");
  renderMap();
  await refreshState();
  const last = lastStep();
  if (last) S.selected = last;
  if (S.state.job) attach(S.state.job.id, S.state.job.steps);
  const params = new URLSearchParams(location.search);
  let view = params.get("view") || "map";
  if (!params.get("view")) try { view = localStorage.getItem("studio.view") || "map"; } catch { /* private window */ }
  if (params.get("stack")) setStack(params.get("stack"));
  if (params.get("step")) S.selected = params.get("step");
  showView(view);
  const open = params.get("open");
  if (open) (S.map.contracts[open] ? openContract : openNode)(open);
  document.fonts?.ready.then(drawWires);
})();
