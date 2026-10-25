/* The preview screens: query and ask (dashboards are in dash.js). Uses the helpers in studio.js. */
"use strict";

const Views = (() => {
  const V = {
    query: { mode: "metrics", schema: null, sql: "", result: null, metrics: null, chosen: [], dims: [], group: ["", ""], since: "", mresult: null },
    ask: { status: null, thread: [], busy: false },
  };
  const busyHTML = (msg) => `<div class="panel empty-state"><b>Data not available right now</b><p>${esc(msg)}</p></div>`;
  const statusBadge = (st) => st && st !== "active" ? `<span class="status ${st}">${esc(st)}</span>` : "";

  async function load(path, body) {
    try { return { ok: true, data: await api(path, body) }; }
    catch (e) { return { ok: false, error: e.message }; }
  }

  /* ----------------------------------------------------------------- query */
  const dimLabel = (d) => {
    const [ent, ...rest] = d.split("__");
    const name = rest.join(" ").replace(/_/g, " ");
    return ent === "metric_time" ? `Time · ${name}` : `${ent.replace(/_/g, " ")} · ${name}`;
  };

  async function showQuery() {
    document.querySelectorAll("#query-mode button").forEach((b) => b.classList.toggle("active", b.dataset.qmode === V.query.mode));
    if (V.query.mode === "sql") return showSql();
    return showMetrics();
  }

  async function showMetrics() {
    const q = V.query;
    if (!q.metrics) {
      $("#query-main").innerHTML = `<div class="faint">Loading the semantic layer…</div>`;
      const r = await load("/api/metrics");
      if (!r.ok) { $("#query-main").innerHTML = busyHTML(r.error); return; }
      q.metrics = r.data.metrics;
    }
    renderMetrics();
  }

  function renderMetrics() {
    const q = V.query;
    const live = q.metrics.filter((m) => m.source !== "backlog"), backlog = q.metrics.filter((m) => m.source === "backlog");
    const chip = (m) => `<button class="mchip ${q.chosen.includes(m.name) ? "on" : ""}" data-mchip="${m.name}">${esc(m.label)} ${statusBadge(m.status)}</button>`;
    const grouped = {};
    for (const d of q.dims) (grouped[d.split("__")[0]] ||= []).push(d);
    const order = Object.keys(grouped).sort((a, b) => (a === "metric_time" ? -1 : b === "metric_time" ? 1 : a.localeCompare(b)));
    const select = (i) => `<select data-mgroup="${i}" ${q.chosen.length ? "" : "disabled"}><option value="">(none)</option>${order.map((g) =>
      `<optgroup label="${esc(g === "metric_time" ? "Time" : g.replace(/_/g, " "))}">${grouped[g].map((d) =>
        `<option value="${d}" ${q.group[i] === d ? "selected" : ""}>${esc(dimLabel(d))}</option>`).join("")}</optgroup>`).join("")}</select>`;
    $("#query-main").innerHTML = `
      <div class="qgrid">
        <div class="panel">
          <h3>Metrics</h3><p class="sub">Pick one to four. Each is defined once in the semantic layer.</p>
          <div class="mchips">${live.map(chip).join("")}</div>
          <h4 class="mini">No number yet</h4><div class="mchips">${backlog.map(chip).join("")}</div>
          <h3 style="margin-top:20px">Group by</h3><p class="sub">Only dimensions valid for every chosen metric are offered.</p>
          <div class="qrow">${select(0)}${select(1)}</div>
          <h3 style="margin-top:16px">Since</h3>
          <div class="qrow"><select id="msince">${sinceOptions().map(([v, l]) =>
            `<option value="${v}" ${q.since === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
          <div class="qrow" style="margin-top:16px"><button class="btn primary" id="mrun" ${q.chosen.length ? "" : "disabled"}>Run</button>
            <button class="btn ghost" id="mrefuse" title="A request the semantic layer refuses">Try: DSO by department</button></div>
        </div>
        <div id="mresult">${metricResultHTML()}</div>
      </div>`;
  }

  function sinceOptions() {
    const today = new Date((S.state?.clock?.today || new Date().toISOString().slice(0, 10)) + "T00:00:00");
    const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
    const year = new Date(today.getFullYear(), 0, 1), back = new Date(today.getFullYear(), today.getMonth() - 11, 1);
    return [["", "All time"], [iso(year), `${today.getFullYear()} to date`], [iso(back), "Last 12 months"]];
  }

  function metricResultHTML() {
    const r = V.query.mresult;
    if (!r) return `<div class="panel empty-state"><b>No query yet</b><p>Choose metrics and dimensions, then Run. The semantic layer writes the SQL.</p></div>`;
    if (r.error) {
      // Business names in place of the semantic layer's identifiers.
      let msg = r.error;
      for (const m of V.query.metrics || []) msg = msg.split(m.name).join(m.label);
      msg = msg.replace(/\b[a-z_]+__[a-z_]+\b/g, (d) => dimLabel(d));
      const [first, rest] = msg.split(". Valid dimensions: ");
      return `<div class="panel refusal"><div class="eyebrow">Refused by the semantic layer</div><h3>${esc(first.endsWith(".") ? first : first + ".")}</h3>
        ${rest ? `<p class="sub">It offers ${rest.split(", ").length} valid dimensions instead, and never guesses a join it does not know.</p>` : ""}</div>`;
    }
    const metricCols = r.metrics.map((m) => m.name);
    const fmtOf = Object.fromEntries(r.metrics.map((m) => [m.name, { percent: "percent", currency_usd: "usd", days: "days" }[m.format] || "int"]));
    const dims = r.columns.filter((c) => !metricCols.includes(c));
    let chart = "";
    if (dims.length === 1) {
      const mi = r.columns.indexOf(metricCols[0]), di = r.columns.indexOf(dims[0]);
      if (dims[0].startsWith("metric_time")) {
        chart = Charts.line(r.rows.slice(-24).map((row) => ({ month: String(row[di]).slice(0, 10), value: row[mi] })), fmtOf[metricCols[0]]);
      } else {
        chart = Charts.bars(r.rows.slice(0, 15).map((row) => ({ label: row[di], value: row[mi] })), fmtOf[metricCols[0]]);
      }
    }
    const gov = r.metrics.map((m) => `<div class="gov"><b>${esc(m.label)}</b> ${statusBadge(m.status)}
      ${m.provisional_reason ? `<div class="sub">${esc(m.provisional_reason)}</div>` : ""}
      ${(m.caveats || []).map((c) => `<div class="caveat">${esc(c)}</div>`).join("")}</div>`).join("");
    return `<div class="panel"><div class="ph"><h3>${r.rows.length} rows</h3></div>${gov}
      ${chart ? `<div class="qchart">${chart}</div>` : ""}
      ${tableHTML(r.columns, r.rows, (c, v) => metricCols.includes(c) ? fmtNum(v, fmtOf[c]) : (typeof v === "string" && /^\d{4}-\d\d-\d\dT/.test(v) ? v.slice(0, 10) : v))}
      <details class="sqlbox"><summary>SQL written by the semantic layer</summary><pre class="code">${esc(r.sql)}</pre></details></div>`;
  }

  function tableHTML(cols, rows, fmt = (c, v) => v) {
    return `<div class="tablewrap"><table class="grid-table"><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${r.map((v, i) => `<td class="${typeof v === "number" ? "num" : ""}">${esc(fmt(cols[i], v) ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  async function chooseMetric(name) {
    const q = V.query;
    q.chosen = q.chosen.includes(name) ? q.chosen.filter((m) => m !== name) : [...q.chosen, name].slice(-4);
    q.dims = [];
    if (q.chosen.length) {
      const r = await load("/api/metrics/dimensions", { metrics: q.chosen });
      q.dims = r.ok ? r.data.dimensions : [];
    }
    q.group = q.group.map((g) => (q.dims.includes(g) ? g : ""));
    renderMetrics();
  }

  async function runMetrics(body) {
    const q = V.query;
    $("#mresult").innerHTML = `<div class="panel"><div class="faint">Running…</div></div>`;
    const r = await load("/api/metrics/query", body || { metrics: q.chosen, group_by: q.group.filter(Boolean), start: q.since || null });
    q.mresult = r.ok ? r.data : { error: r.error };
    $("#mresult").innerHTML = metricResultHTML();
  }

  async function showSql() {
    const q = V.query;
    if (!q.schema) {
      const r = await load("/api/query/schema");
      if (!r.ok) { $("#query-main").innerHTML = busyHTML(r.error); return; }
      q.schema = r.data;
      q.sql ||= r.data.examples[0].sql;
    }
    const groups = {};
    for (const t of q.schema.tables) (groups[t.schema] ||= []).push(t);
    $("#query-main").innerHTML = `
      <div class="sqlgrid">
        <div class="panel schema">${Object.entries(groups).map(([sch, ts]) => `<h4 class="mini">${esc(sch)}</h4>${ts.map((t) =>
          `<details><summary data-table="${esc(sch)}.${esc(t.table)}">${esc(t.table)}</summary>${t.columns.map((c) =>
            `<div class="col"><span>${esc(c.name)}</span><span class="faint">${esc(c.type.toLowerCase())}</span></div>`).join("")}</details>`).join("")}`).join("")}</div>
        <div>
          <div class="panel">
            <div class="ph"><select id="sql-example"><option value="">Examples: the golden answers' reference SQL…</option>${q.schema.examples.map((e, i) =>
              `<option value="${i}">${esc(e.label)}</option>`).join("")}</select>
              <button class="btn primary" id="sql-run">Run <span class="kbd">⌘↵</span></button></div>
            <textarea id="sql-text" spellcheck="false">${esc(q.sql)}</textarea>
            <div class="faint small-note">Read-only. One statement, at most ${q.schema.limit} rows, 15 seconds.</div>
          </div>
          <div id="sql-result">${sqlResultHTML()}</div>
        </div>
      </div>`;
  }

  function sqlResultHTML() {
    const r = V.query.result;
    if (!r) return "";
    if (r.error) return `<div class="panel refusal"><div class="eyebrow">Query error</div><h3>${esc(r.error)}</h3></div>`;
    return `<div class="panel"><div class="ph"><h3>${r.rows.length}${r.truncated ? "+" : ""} rows</h3><span class="faint">${r.ms} ms</span></div>
      ${tableHTML(r.columns, r.rows, (c, v) => (typeof v === "number" && !Number.isInteger(v) ? v.toLocaleString("en-US", { maximumFractionDigits: 4 }) : v))}</div>`;
  }

  async function runSql() {
    const q = V.query;
    q.sql = $("#sql-text").value;
    $("#sql-result").innerHTML = `<div class="panel"><div class="faint">Running…</div></div>`;
    const r = await load("/api/query/sql", { sql: q.sql });
    q.result = r.ok ? r.data : { error: r.error };
    $("#sql-result").innerHTML = sqlResultHTML();
  }

  /* ------------------------------------------------------------------- ask */
  const SUGGESTIONS = ["Which site has the worst on-time delivery this year?", "How has DSO moved month by month in 2026?",
    "Show DSO by department", "What does Order Fill Rate measure, and who owns it?"];

  function md(text) {
    // Paragraphs, bullets and **bold** - enough for an answer, with everything escaped first.
    return esc(text).split(/\n{2,}/).map((block) => {
      const lines = block.split("\n");
      if (lines.every((l) => /^\s*([-*]|\d+\.)\s/.test(l))) return `<ul>${lines.map((l) => `<li>${l.replace(/^\s*([-*]|\d+\.)\s/, "")}</li>`).join("")}</ul>`;
      if (lines.every((l) => l.trim().startsWith("|"))) return `<pre class="mdtable">${block}</pre>`;
      return `<p>${lines.join("<br>")}</p>`;
    }).join("").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  }

  async function showAsk() {
    const a = V.ask;
    if (!a.status) { const r = await load("/api/ask/status"); a.status = r.ok ? r.data : { available: false, reason: r.error }; }
    renderAsk();
  }

  function renderAsk() {
    const a = V.ask;
    if (!a.status.available) {
      $("#ask-main").innerHTML = `<div class="panel empty-state"><b>Chat is not configured</b><p>${esc(a.status.reason)}</p>
        <p class="sub">When it is, a question like "${esc(SUGGESTIONS[0])}" is answered by ${esc(a.status.model || "Claude")}
        calling the same four tools the MCP server offers: list metrics, describe a metric, list valid dimensions, query.
        Each call is shown, and every number comes back with its status and caveats. Questions and results are sent to the Claude API.</p></div>`;
      return;
    }
    const turns = a.thread.map((t) => t.role === "user" ? `<div class="msg user"><div>${esc(t.content)}</div></div>`
      : `<div class="msg bot">${t.tools?.length ? `<div class="tools">${t.tools.map((x) => `<div class="toolcall"><span class="mono">${esc(x.tool)}</span>
          <span class="faint">${esc(Object.entries(x.input).map(([k, v]) => `${k}=${Array.isArray(v) ? v.join(",") : v}`).join(" "))}</span>
          <span class="tsum ${x.summary.startsWith("Refused") ? "bad" : ""}">${esc(x.summary)}</span></div>`).join("")}</div>` : ""}
          ${t.error ? `<div class="alert">${esc(t.error)}</div>` : t.content ? `<div class="answer">${md(t.content)}</div>` : `<div class="faint">Thinking…</div>`}</div>`).join("");
    $("#ask-main").innerHTML = `<div class="panel chat">
      <div class="thread" id="thread">${turns || `<div class="faint">Ask about any metric. Try one of these:</div>`}</div>
      <div class="suggest">${SUGGESTIONS.map((s) => `<button class="mchip" data-suggest="${esc(s)}" ${a.busy ? "disabled" : ""}>${esc(s)}</button>`).join("")}</div>
      <form id="ask-form" class="askbar"><input id="ask-input" placeholder="Ask a question about the metrics" autocomplete="off" ${a.busy ? "disabled" : ""}>
        <button class="btn primary" ${a.busy ? "disabled" : ""}>Ask</button></form>
      <div class="faint small-note">${esc(a.status.model)} · governed metric tools only · questions and results are sent to the Claude API</div></div>`;
    const th = $("#thread"); th.scrollTop = th.scrollHeight;
  }

  async function ask(question) {
    const a = V.ask;
    if (!question.trim() || a.busy) return;
    const history = a.thread.filter((t) => t.content && !t.error).map((t) => ({ role: t.role, content: t.content }));
    a.thread.push({ role: "user", content: question });
    const turn = { role: "assistant", content: "", tools: [] };
    a.thread.push(turn); a.busy = true; renderAsk();
    try {
      const res = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, history }) });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
      const reader = res.body.getReader(), dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const ev = JSON.parse(buf.slice(0, nl)); buf = buf.slice(nl + 1);
          if (ev.type === "tool") turn.tools.push(ev);
          else if (ev.type === "answer") turn.content = ev.text || "(no answer)";
          else if (ev.type === "error") turn.error = ev.message;
          renderAsk();
        }
      }
    } catch (e) { turn.error = e.message; }
    a.busy = false; renderAsk();
  }

  /* ---------------------------------------------------------------- events */
  document.addEventListener("click", (e) => {
    const t = e.target.closest("button, summary");
    if (!t) return;
    if (t.dataset.qmode) { V.query.mode = t.dataset.qmode; return showQuery(); }
    if (t.dataset.mchip) return chooseMetric(t.dataset.mchip);
    if (t.dataset.suggest) return ask(t.dataset.suggest);
    switch (t.id) {
      case "mrun": return runMetrics();
      case "mrefuse": return runMetrics({ metrics: ["dso_days_to_pay_proxy"], group_by: ["employee__department_name"] });
      case "sql-run": return runSql();
    }
  });
  document.addEventListener("dblclick", (e) => {
    const t = e.target.closest("summary[data-table]");
    if (t) $("#sql-text").value = `select *\nfrom ${t.dataset.table}\nlimit 100`;
  });
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset.mgroup !== undefined) { V.query.group[+t.dataset.mgroup] = t.value; return; }
    if (t.id === "msince") { V.query.since = t.value; return; }
    if (t.id === "sql-example" && t.value !== "") { $("#sql-text").value = V.query.schema.examples[+t.value].sql; V.query.sql = $("#sql-text").value; }
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.id === "sql-text" && e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); runSql(); }
  });
  document.addEventListener("submit", (e) => {
    if (e.target.id !== "ask-form") return;
    e.preventDefault();
    const input = $("#ask-input"), q = input.value; input.value = ""; ask(q);
  });

  function show(name) {
    if (name === "dash") return Dash.show();
    if (name === "gov") return Gov.show();
    if (name === "query") return showQuery();
    if (name === "ask") return showAsk();
  }
  return { show };
})();
window.Views = Views;
