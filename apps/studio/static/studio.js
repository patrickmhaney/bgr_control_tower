/* Control Tower Studio. Plain JavaScript, no build step. */
"use strict";

const S = {
  map: null, stack: "baseline", prevTools: {}, state: null,
  job: null, setup: null, selected: "day", statuses: {}, results: {}, logs: {}, progress: {}, activity: {}, alerts: {},
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
  return `<span class="delta ${tone}">${text} vs last run</span>`;
}

/* ================================================================= MAP */
const swapBadge = (swap) => {
  if (!swap || swap === "source" || swap === "baseline") return "";
  const c = S.map.swap_costs[swap] || { label: swap };
  const effort = swap === "rebuild" ? "" : c.effort;
  return `<span class="badge ${swap}">${esc(c.label)}${effort ? " · " + esc(effort) : ""}</span>`;
};
const contractLabel = (cid) => `Contract ${cid.slice(1)}`;
const nodeById = (id) => [...S.map.nodes, ...S.map.foundation].find((n) => n.id === id);

function cardHTML(n) {
  const t = n.stacks[S.stack];
  const cls = ["card", n.kind || "", t.swap === "none" ? "none" : "", S.stack !== "baseline" && ["adapter", "port", "rebuild"].includes(t.swap) ? "changed" : ""].join(" ");
  const flip = S.prevTools[n.id] && S.prevTools[n.id] !== t.tool ? " flip" : "";
  return `<button class="${cls}" data-node="${n.id}" id="node-${n.id}">
    <div class="role">${esc(n.role)}</div><div class="tool${flip}${t.tool.length > 26 ? " long" : ""}">${esc(t.tool)}</div>${swapBadge(t.swap)}</button>`;
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
    if (shared) { if (g[0] === e) pills.push([e.contract, b.l - 31, b.cy]); }
    else pills.push([e.contract, ...mid]);
  }
  $("#wires").innerHTML = `<defs><marker id="arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
    <path d="M0 0 L10 5 L0 10 z" fill="#98a2b3"/></marker></defs>${paths}`;
  map.querySelectorAll(".pill").forEach((p) => p.remove());
  for (const [c, x, y] of pills) {
    const p = document.createElement("button");
    p.className = "pill"; p.innerHTML = `<span>Contract</span><b>${c.slice(1)}</b>`; p.dataset.contract = c;
    p.style.left = x + "px"; p.style.top = y + "px"; p.title = S.map.contracts[c].name;
    map.appendChild(p);
  }
}

function renderKeeps() {
  const n = S.map.counts;
  const labels = { contracts: "Contracts", metrics: "Metric definitions", golden: "Golden answers", star: "Star schema tables" };
  $("#keeps").innerHTML = S.map.keeps.map((k) => {
    const body = `<div class="n">${n[k.id] ?? "–"}</div><div class="l">${esc(labels[k.id] || k.label)}</div>${k.note ? `<div class="tn">${esc(k.note)}</div>` : ""}`;
    return k.opens ? `<button class="tile golink" data-open-view="${esc(k.opens)}" title="Open ${esc(k.opens === "gov" ? "Governance" : k.opens)}">${body}<span class="go">→</span></button>`
      : `<div class="tile">${body}</div>`;
  }).join("");
  renderKeepsGov();
}

// The governance the metric definitions carry, summarised from the Governance screen's own data.
async function renderKeepsGov() {
  const s = await window.Gov?.summary().catch(() => null);
  if (!s) { $("#keeps-gov").innerHTML = ""; return; }
  $("#keeps-gov").innerHTML = `<button class="govstrip" data-open-view="gov">
    <div class="gs-h"><b>Governance comes with the definitions</b><span>Owner, status and caveats are fields beside each formula. The lint enforces them on every build and every route serves them with the number.</span></div>
    <div class="gs-n"><span><b>${s.agreed}</b> of ${s.kpis} KPIs agreed</span><span class="${s.owned < s.business ? "warn" : ""}"><b>${s.owned}</b> of ${s.business} owners confirmed</span>
      <span class="${s.errors ? "bad" : "ok"}"><b>${s.errors}</b> lint violations</span><span><b>${s.refused}</b> refused with a reason</span></div>
    <span class="go">Governance →</span></button>`;
}

function renderSwaps() {
  const stack = S.map.stacks.find((s) => s.id === S.stack);
  const nodes = [...S.map.nodes, ...S.map.foundation].filter((n) => n.kind !== "source");
  const contracts = Object.keys(S.map.contracts).length;
  if (S.stack === "baseline") {
    $("#swaptitle").textContent = "Open-source baseline";
    $("#swapsub").textContent = "All components shown are implemented in this repository.";
    $("#swaplist").innerHTML = `<div class="headline">${nodes.length} components. No licence cost.</div>
      <div class="swaprow"><span class="badge baseline">Implemented</span><span class="names">${nodes.filter((n) => !n.fixed).map((n) => esc(n.stacks.baseline.tool)).join(", ")}</span></div>
      <div class="swaprow"><span class="badge stays">Platform</span><span class="names">${nodes.filter((n) => n.fixed).map((n) => esc(n.role)).join(", ")}</span></div>`;
    return;
  }
  const by = {};
  for (const n of nodes) (by[n.stacks[S.stack].swap] ||= []).push(n);
  const changing = ["adapter", "port", "rebuild"].reduce((a, k) => a + (by[k]?.length || 0), 0);
  $("#swaptitle").textContent = stack.label;
  $("#swapsub").textContent = "Estimated effort to move each component from the baseline.";
  const order = ["adapter", "port", "rebuild", "same", "none", "stays"];
  $("#swaplist").innerHTML = `<div class="headline"><b>${changing} of ${nodes.length}</b> components change. <b>0 of ${contracts}</b> contracts change.</div>` +
    order.filter((k) => by[k]).map((k) => `<div class="swaprow">${swapBadge(k)}<span class="names">${[...new Set(by[k].map((n) =>
      k === "stays" || k === "none" ? n.role : n.stacks[S.stack].tool))].map(esc).join(", ")}</span></div>`).join("");
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
  $("#drawer").classList.remove("wide");
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
  const contracts = contractsOf(n).map((c) => `<button class="contract-row" data-contract="${c}"><span class="tag">${contractLabel(c)}</span>
      <div><b>${esc(S.map.contracts[c].name)}</b><span>${esc(S.map.contracts[c].promise)}</span></div></button>`).join("");
  const proofs = contractsOf(n).map((c) => `<div class="contract-row"><span class="tag">${contractLabel(c)}</span>
      <div><span>${esc(S.map.contracts[c].proof)}</span></div></div>`).join("");
  const stacks = n.kind === "source" ? "" : `<h4>By stack</h4><table class="stack-table">${S.map.stacks.map((s) =>
    `<tr><td>${esc(s.label)}</td><td><div class="t">${esc(n.stacks[s.id].tool)}</div>${s.id === "baseline" ? "" : swapBadge(n.stacks[s.id].swap)}</td></tr>`).join("")}</table>`;
  const other = n.detail.other?.length ? `<h4>Other options</h4><p>${n.detail.other.map(esc).join(", ")}</p>` : "";
  const note = n.swap_note || n.detail.note ? `<h4>Notes</h4><div class="note">${esc(n.swap_note || n.detail.note)}</div>` : "";
  const test = n.detail.test ? `<div class="proof"><span class="mono">${esc(n.detail.test)}</span></div>` : "";
  const opens = n.opens ? `<h4>Governance</h4><p>Each definition carries its owner, status and caveats, enforced on every build and served with every number.</p>
    <button class="btn" data-open-view="${esc(n.opens.view)}">${esc(n.opens.label)} →</button>` : "";
  const step = n.step && S.state?.clock?.initialised ? `<h4>Pipeline step</h4><button class="btn" data-goto-step="${n.step}">Go to ${esc(stepById(n.step).title)}</button>` : "";
  openDrawer(`<div class="eyebrow">${esc(n.role)}${n.kind === "source" ? " · source system" : ""}</div>
    <h2>${esc(t.tool)}</h2><p>${esc(n.what)}</p>
    ${contracts ? `<h4>Contracts</h4>${contracts}` : ""}
    ${proofs ? `<h4>Verification</h4>${proofs}${test}` : ""}
    ${opens}${stacks}${note}${other}${step}`);
}

function openDrawer2(html, wide) {
  openDrawer(html);
  $("#drawer").classList.toggle("wide", !!wide);
}

async function openContract(id) {
  const c = S.map.contracts[id];
  const ends = S.map.edges.filter((e) => e.contract === id);
  const names = (key) => [...new Set(ends.map((e) => nodeById(e[key]).role))].join(", ");
  S.contract = { id, data: null, file: 0, suites: {}, optional: new Set(), between: ends.length ? `${names("from")} → ${names("to")}` : "" };
  openDrawer2(`<div class="eyebrow">${contractLabel(id)}</div><h2>${esc(c.name)}</h2><p>${esc(c.promise)}</p><div class="faint">Loading…</div>`, true);
  try {
    S.contract.data = await api(`/api/contracts/${id}`);
    renderContract();
  } catch (e) { toast(e.message); }
}

function caseIcon(st) {
  return { pass: "✓", fail: "✗", skip: "–", warn: "!" }[st] || "";
}

function suiteHTML(su, i) {
  const r = S.contract.suites[i] || {};
  const results = r.cases || {};
  const listed = su.cases.map((c) => ({ ...c, ...(results[c.name] || {}) }));
  const extra = Object.values(results).filter((c) => !su.cases.some((x) => x.name === c.name));
  const all = [...listed, ...extra];
  const counts = r.counts || {};
  const chip = r.status === "running" ? `<span class="verdict run">Running…</span>`
    : r.status === "pass" ? `<span class="verdict pass">${counts.pass || 0} passed${counts.warn ? `, ${counts.warn} warnings` : ""}</span>`
    : r.status === "fail" ? `<span class="verdict fail">${counts.fail ? `${counts.fail} failed` : "Failed"}</span>`
    : `<span class="verdict">${all.length ? `${all.length} tests` : "Not run"}</span>`;
  const opt = su.optional ? `<label class="opt"><input type="checkbox" data-optional="${i}" ${S.contract.optional.has(i) ? "checked" : ""}> Include</label>` : "";
  const rows = all.length ? all.map((c) => `<div class="case ${c.status || ""}"><span class="ic">${caseIcon(c.status)}</span>
      <span class="cl">${esc(c.label)}</span><span class="cd">${esc(c.detail || "")}</span></div>`).join("")
    : `<div class="case"><span class="ic"></span><span class="cl faint">Results appear here as the test runs.</span></div>`;
  return `<div class="suite"><div class="suite-top"><div><b>${esc(su.title)}</b>${su.note ? `<div class="faint">${esc(su.note)}</div>` : ""}</div>
    <div class="suite-right">${opt}${chip}</div></div><div class="cases">${rows}</div></div>`;
}

function renderContract() {
  const { id, data: d, file } = S.contract;
  const f = d.files[file];
  const tabs = d.files.length > 1 ? `<div class="filetabs">${d.files.map((x, i) =>
    `<button class="${i === file ? "active" : ""}" data-file="${i}">${esc(x.path.split("/").pop())}</button>`).join("")}</div>` : "";
  const lines = f ? f.text.split("\n").map((t, i) => `<span class="ln">${f.start + i}</span>${esc(t)}`).join("\n") : "";
  const end = f ? f.start + f.text.split("\n").length - 1 : 0;
  const code = f ? `${tabs}<pre class="code">${lines}</pre><div class="codefoot mono">${esc(f.path)} · lines ${f.start}–${end} of ${f.total}</div>` : "";
  const last = d.last ? `<span class="badge ${d.last.passed ? "adapter" : "rebuild"}">${d.last.passed ? "Passed" : "Failed"}</span> in the pipeline at ${esc(d.last.at.slice(11))}` : "";
  const running = S.contract.running;
  const tests = d.suites.length
    ? `<div class="tests-head"><h4>Tests</h4><button class="btn primary small" id="run-tests" ${running || S.job ? "disabled" : ""}>${running ? "Running…" : "Run tests"}</button></div>
       ${d.live ? `<div class="faint small-note">After day 0, results are compared with the reference SQL rather than the frozen answers.</div>` : ""}
       ${d.suites.map(suiteHTML).join("")}`
    : `<h4>Tests</h4><div class="note">${esc(d.enforced || "No tests.")}</div>`;
  $("#drawer-body").innerHTML = `<div class="eyebrow">${contractLabel(id)}</div><h2>${esc(d.name)}</h2><p>${esc(d.promise)}</p>
    <div class="meta">${S.contract.between ? `<div><span class="faint">Between</span> ${esc(S.contract.between)}</div>` : ""}${last ? `<div><span class="faint">Last check</span> ${last}</div>` : ""}</div>
    <h4>Definition</h4>${code}
    ${tests}
    <h4>Verification</h4><p>${esc(d.proof)}</p>
    <h4>All stacks</h4><div class="note">The same in every stack. A replacement component has to pass the same tests.</div>`;
}

async function runContractTests() {
  const sc = S.contract, d = sc.data;
  const chosen = d.suites.map((su, i) => i).filter((i) => !d.suites[i].optional || sc.optional.has(i));
  try {
    const job = await api(`/api/contracts/${sc.id}/run`, { suites: chosen });
    sc.running = true; sc.suites = {};
    S.job = { id: job.id, steps: [`test:${sc.id}`] };
    renderContract(); renderRun();
    const es = new EventSource(`/api/jobs/${job.id}/events`);
    let pending = false;
    const redraw = () => { if (!pending) { pending = true; requestAnimationFrame(() => { pending = false; if (S.contract === sc) renderContract(); }); } };
    es.onmessage = (msg) => {
      const ev = JSON.parse(msg.data);
      if (ev.type === "suite") { sc.suites[ev.index] = { ...(sc.suites[ev.index] || { cases: {} }), status: ev.status, counts: ev.counts }; redraw(); }
      else if (ev.type === "case") { const su = (sc.suites[ev.index] ||= { cases: {} }); su.cases[ev.case.name] = ev.case; redraw(); }
      else if (ev.type === "done") {
        es.close(); sc.running = false; S.job = null;
        const failed = Object.values(sc.suites).reduce((a, x) => a + (x.counts?.fail || 0), 0);
        toast(ev.ok ? "All tests passed." : failed ? `${failed} tests failed.` : "Tests failed. See the log.");
        redraw(); renderRun();
      }
    };
  } catch (e) { toast(e.message); }
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
  $("#daytext").innerHTML = c.initialised ? `Business day <b>${shortDate(c.today)}</b>${busy ? " · running" : ""}` : "Not initialized";
  if (!c.initialised) return;
  $("#bizdate").textContent = longDate(c.today);
  $("#daytrack").style.width = `${(100 * c.day) / c.days}%`;
  $("#daycount").textContent = `Day ${c.day} of ${c.days}`;
}

function renderControls() {
  const c = S.state.clock, busy = !!S.job || !!S.state.busy, atEnd = c.initialised && c.day >= c.days;
  $("#day-btn").disabled = busy || atEnd;
  $("#day-btn").textContent = atEnd ? "End of timeline" : "Run full day";
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
    const shields = s.checks.map((c) => `<span class="shield ${shieldStatus(s.id, c)}">${c === "quality" ? "<span>Data</span><b>tests</b>" : `<span>Contract</span><b>${c.slice(1)}</b>`}</span>`).join("");
    const node = nodeById(s.node);
    const link = shields ? `<div class="link">${shields}</div>` : i < S.state.steps.length - 1 ? `<div class="link bare"></div>` : "";
    const mark = st === "ok" ? "✓" : st === "failed" ? "!" : i + 1;
    return `<button class="stepchip ${st} ${s.id === S.selected ? "selected" : ""}" data-step="${s.id}">
      <span class="num">${mark}</span><span class="name">${esc(s.title)}</span>
      <span class="role">${esc(node ? node.role : "Source systems")}</span></button>${link}`;
  }).join("");
}

function renderStatus() {
  const id = S.selected, st = chipStatus(id), r = S.results[id];
  const line = $("#step-status"), bar = $("#step-bar");
  let text;
  if (st === "running") text = `<b>Running…</b><span class="activity">${esc(S.activity[id] || "")}</span>`;
  else if (st === "checking") text = "<b>Running checks…</b>";
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
    : `<span class="faint">No output yet.</span>`;
  $("#log").classList.toggle("open", S.logOpen);
  $("#techtoggle").textContent = S.logOpen ? "Hide log" : "Show log";
  if (S.logOpen) $("#log").scrollTop = $("#log").scrollHeight;
}

function checkHTML(cid, result) {
  const meta = S.map.contracts[cid];
  const isContract = !!meta;
  const kind = isContract ? `<span class="tag">${contractLabel(cid)}</span>${esc(meta.name)}` : "Data tests";
  const open = isContract ? `<button class="linkbtn" data-contract="${cid}">View contract and tests →</button>` : "";
  if (!result) {
    return `<div class="check"><div class="check-top"><div class="kind">${kind}</div><span class="verdict">Not run yet</span></div>
      <p class="promise" style="margin-top:10px">${esc(isContract ? meta.promise : "dbt tests on the staging tables: keys, uniqueness and relationships.")}</p>${open}</div>`;
  }
  const v = result.passed ? "pass" : "fail";
  const rows = result.facts.map((f) => `<div class="row"><span>${esc(f.label)}</span><span>${esc(fmtFact(f))}</span></div>`).join("");
  const problems = result.problems.length ? `<ul class="problems">${result.problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : "";
  return `<div class="check ${v}"><div class="check-top"><div class="kind">${kind}</div><span class="verdict ${v}">${result.passed ? "Passed" : "Failed"}</span></div>
    <h3>${esc(result.title)}</h3>${isContract ? `<p class="promise">${esc(meta.promise)}</p>` : ""}
    <div class="rows">${rows}</div>${problems}
    ${result.test ? `<div class="ci">CI: <span class="mono">${esc(result.test)}</span></div>` : ""}${open}</div>`;
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
    : `<div class="empty">No results yet.</div>`;
  const alert = S.alerts[S.selected] || (r?.status === "failed" ? (r.error || "A check failed. The pipeline stopped at this step.") : "");
  $("#step-alert").innerHTML = alert ? `<div class="alert">${esc(alert)}</div>` : "";
  $("#step-checks").innerHTML = s.checks.length
    ? s.checks.map((c) => checkHTML(c, r?.checks?.find((x) => x.id === c))).join("")
    : `<div class="panel"><h3>No checks</h3><p class="nocheck">This step advances the simulated source systems by one day. The first contract check (C2) runs after Collect.</p></div>`;
  renderStatus(); renderLog();
}

function renderBanner() {
  const b = $("#banner");
  const fresh = S.state.clock.initialised && !S.job && !Object.keys(S.results).length;
  const busy = !S.job && S.state.busy;
  b.className = "banner" + (S.setup?.error ? " error" : "");
  if (busy) b.innerHTML = `<b>Pipeline busy.</b><span class="muted">${esc(S.state.busy)}</span>`;
  else if (S.setup?.error) b.innerHTML = `<b>Reset failed</b><span>${esc(S.setup.error)}</span>`;
  else if (S.setup) {
    const p = S.setup.progress;
    b.innerHTML = `<b>Resetting to day 0</b><span class="activity">${esc(S.setup.activity)}</span>
      <div class="bar ${p ? "" : "indeterminate"}"><i style="width:${p ? (100 * p[0]) / p[1] : 0}%"></i></div>`;
  } else if (fresh) b.innerHTML = `<b>Day 0 ready.</b><span class="muted">No steps have run yet. Use Next step or Run full day.</span>`;
  b.hidden = !(S.setup || fresh || busy);
}

function renderRun() {
  if (!S.state) return;
  renderDay();
  const ready = S.state.clock.initialised || S.job;
  $("#run-setup").hidden = !!ready;
  $("#run-main").hidden = !ready;
  if (!ready) return;
  renderControls(); renderBanner(); renderStrip(); renderDetail();
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
  for (const s of steps) { delete S.statuses[s]; delete S.alerts[s]; }
  if (steps.includes("reset")) { S.setup = { activity: "", progress: null }; S.results = {}; S.logs = {}; S.selected = "day"; }
  renderRun();
  const es = new EventSource(`/api/jobs/${id}/events`);
  let pending = false;
  es.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    const step = ev.step;
    if (step === "reset") {
      if (ev.type === "log" && !ev.line.startsWith("$ ")) S.setup.activity = ev.line;
      if (ev.progress) S.setup.progress = ev.progress;
      if (ev.type === "step" && ev.status === "failed") S.setup.error = ev.reason;
      if (!pending) { pending = true; requestAnimationFrame(() => { pending = false; renderBanner(); }); }
      return;
    }
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
      const held = ev.result.checks.every((c) => c.passed) && !ev.result.error;
      S.results[step] = { ...ev.result, status: held ? "ok" : "failed" };
      if (step === "day") refreshClock();
      renderRun();
    } else if (ev.type === "done") {
      es.close();
      S.job = null;
      S.statuses = {};
      if (S.setup && !S.setup.error) S.setup = null;
      if (!ev.ok) toast(S.setup ? "Reset failed." : "Run stopped at a failed step.");
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
  if (t.dataset.openView) { closeDrawer(); return showView(t.dataset.openView); }
  if (t.dataset.contract) return openContract(t.dataset.contract);
  if (t.dataset.file) { S.contract.file = +t.dataset.file; return renderContract(); }
  if (t.dataset.gotoStep) { closeDrawer(); S.selected = t.dataset.gotoStep; showView("run"); return; }
  if (t.dataset.step) { S.selected = t.dataset.step; renderStrip(); renderDetail(); return; }
  if (t.dataset.provider) return swapMatcher(t.dataset.provider);
  switch (t.id) {
    case "drawer-close": return closeDrawer();
    case "day-btn": return startJob({ steps: ALL() });
    case "next-btn": return startJob({ steps: [nextStep()] });
    case "setup-btn": return startJob({ reset: true });
    case "reset-btn":
      if (confirm("Reset to day 0? This rebuilds all data (about 35 seconds).")) { S.setup = null; startJob({ reset: true }); }
      return;
    case "techtoggle": S.logOpen = !S.logOpen; return renderLog();
    case "run-tests": return runContractTests();
  }
});
$("#scrim").addEventListener("click", closeDrawer);
document.addEventListener("change", (e) => {
  const i = e.target.dataset?.optional;
  if (i === undefined) return;
  if (e.target.checked) S.contract.optional.add(+i); else S.contract.optional.delete(+i);
});
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
    toast(`Matcher set to ${provider === "rules" ? "Rules" : "Splink"}. Re-running from Match.`);
    if (S.state.clock.initialised) startJob({ steps: FROM("match") });
    else renderControls();
  } catch (err) { toast(err.message); }
}

function showView(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  try { localStorage.setItem("studio.view", name); } catch { /* private window */ }
  if (name === "map") requestAnimationFrame(drawWires);
  else if (name === "run") renderRun();
  else window.Views?.show(name);
}

// Notice runs started elsewhere (a terminal, a schedule): they hold the pipeline lock.
setInterval(async () => {
  if (S.job || !S.state || document.hidden) return;
  try {
    const st = await api("/api/state");
    if (st.busy !== S.state.busy || st.clock.today !== S.state.clock.today) {
      S.state.busy = st.busy; S.state.clock = st.clock;
      renderRun();
    }
  } catch { /* the server may be restarting */ }
}, 4000);

let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(drawWires, 80); });

(async function init() {
  S.map = await api("/api/map");
  renderMap();
  await refreshState();
  const last = lastStep();
  if (last) S.selected = last;
  if (S.state.job && !S.state.job.steps[0].startsWith("test:")) attach(S.state.job.id, S.state.job.steps);
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
