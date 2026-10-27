/* The Governance screen: every metric, its owners, its lifecycle and its proof, read from the semantic layer.
   Everything shown comes from /api/governance; this file only lays it out. A KPI's owner and description are
   edited here through the requirements store (Req.call), the same lines the Requirements tab edits: each save
   is a commit in the name under "Who's editing?", and either page redraws when the other saves. */
"use strict";

const Gov = (() => {
  const G = { data: null, view: "kpi", own: "owners", search: "", pending: null };
  const GOV_KEYS = ["owner", "owner_proposed", "status", "provisional_reason", "blocked_reason", "placeholder_reason",
    "unblock_requires", "caveats", "role", "direction", "is_data_quality"];
  const STATUS_ORDER = ["blocked", "placeholder", "provisional", "active"];
  const pill = (st) => `<span class="gstat ${esc(st)}">${esc(st)}</span>`;
  const byName = (n) => G.data.metrics.find((m) => m.name === n);
  const kpis = () => G.data.metrics.filter((m) => m.role === "kpi");
  const confirmed = (m) => m.owner && m.owner !== "TBD";
  const ownerText = (m) => (confirmed(m) ? esc(m.owner) : `<span class="tbd">TBD</span>${m.owner_proposed ? ` <span class="faint">proposed: ${esc(m.owner_proposed)}</span>` : ""}`);
  const chip = (m) => `<button class="gchip ${esc(m.status)}" data-gmetric="${esc(m.name)}" title="${esc(m.description)}">${esc(m.label)}</button>`;
  const procName = (code) => G.data.processes[code] || code;

  async function load() {
    G.data ||= await api("/api/governance");
    return G.data;
  }

  /** The headline numbers, for the Architecture screen's platform assets. */
  async function summary() {
    await load();
    const k = kpis(), live = k.filter((m) => m.source === "metricflow");
    return { kpis: live.length, agreed: live.filter((m) => m.status === "active").length, business: k.length,
      owned: k.filter(confirmed).length, errors: G.data.lint.errors.length, refused: k.length - live.length };
  }

  async function show() {
    if (!G.data) {
      $("#gov-main").innerHTML = `<div class="faint">Reading the semantic layer…</div>`;
      try { await load(); }
      catch (e) { $("#gov-main").innerHTML = `<div class="panel empty-state"><b>Not available</b><p>${esc(e.message)}</p></div>`; return; }
    }
    try { render(); }
    catch (e) { $("#gov-main").innerHTML = `<div class="panel empty-state"><b>Could not draw this screen</b><p>${esc(e.message)}</p></div>`; return; }
    if (G.pending) { const n = G.pending; G.pending = null; openMetric(n); }
  }

  /** Open one metric's page from another screen. */
  function open(name) {
    G.pending = name;
    showView("gov");
  }

  function render() {
    $("#gov-main").innerHTML = [healthHTML(), lifecycleHTML(), ownershipHTML(), catalogHTML()].join("");
  }

  /* ------------------------------------------------------------ source lines */
  function yamlHTML(src) {
    // The file's own lines. Governance keys, and the lines that continue them, are highlighted.
    const lines = src.text.split("\n");
    let govIndent = -1;
    const keyRe = new RegExp(`\\b(${GOV_KEYS.join("|")}):`, "g");
    return lines.map((line, i) => {
      const indent = line.length - line.trimStart().length;
      const m = line.match(/^\s*(?:- )?([a-z_]+):/);
      if (m) govIndent = GOV_KEYS.includes(m[1]) ? indent : (indent <= govIndent ? -1 : govIndent);
      const inGov = govIndent >= 0 && (indent > govIndent || (m && GOV_KEYS.includes(m[1])));
      const body = esc(line).replace(keyRe, `<mark>$1</mark>:`);
      return `<span class="yl ${inGov ? "ygov" : ""}"><i>${src.line + i}</i>${body || " "}</span>`;
    }).join("");
  }

  /* ---------------------------------------------------------------- health */
  function healthHTML() {
    const k = kpis(), live = k.filter((m) => m.source === "metricflow"), backlog = k.filter((m) => m.source === "backlog");
    const comps = G.data.metrics.filter((m) => m.role === "component");
    const active = live.filter((m) => m.status === "active").length, prov = live.filter((m) => m.status === "provisional");
    const own = k.filter(confirmed).length, proposed = k.filter((m) => m.owner_proposed).length;
    const proven = live.filter((m) => m.golden.some((g) => !g.refusal)).length;
    const caveats = live.reduce((a, m) => a + m.caveats.length, 0);
    const tiles = [
      ["", live.length, "KPIs defined", `${comps.length} building blocks, ${backlog.length} in the backlog`],
      ["", `${active} of ${live.length}`, "agreed", `${prov.length} provisional, ${prov.filter((m) => m.provisional_reason).length} with a stated reason`],
      [own < k.length ? "warn" : "ok", `${own} of ${k.length}`, "owners confirmed", `${live.length} KPIs and ${backlog.length} backlog metrics; ${proposed} have a proposed owner awaiting sign-off`],
      [proven === live.length ? "ok" : "", `${proven} of ${live.length}`, "proven by golden answers", "numbers frozen and re-checked on every run"],
      ["", caveats, "caveats published", "returned with the number on every route"],
      ["", backlog.length, "refused with a reason", "blocked or placeholder: no number, only why"],
    ];
    return `<div class="gtiles">${tiles.map(([tone, n, l, s]) => `<div class="gtile ${tone}"><div class="n">${esc(n)}</div><div class="l">${esc(l)}</div><div class="s">${esc(s)}</div></div>`).join("")}</div>`;
  }

  /* ------------------------------------------------------------- lifecycle */
  function lifecycleHTML() {
    const k = kpis();
    const cols = STATUS_ORDER.map((id) => {
      const st = G.data.stages.find((s) => s.id === id), ms = k.filter((m) => m.status === id);
      return `<div class="lc ${id}"><div class="lc-h">${pill(id)}<b>${ms.length}</b></div>
        <div class="lc-means">${esc(st.means)}</div>
        <div class="lc-chips">${ms.map(chip).join("") || `<span class="faint">None</span>`}</div>
        <div class="lc-next"><span>Moves on when</span>${esc(st.next)}</div></div>`;
    }).join(`<div class="lc-arrow">→</div>`);
    return `<div class="panel"><div class="ph"><div><h3>Metric lifecycle</h3>
      <div class="sub">Where every KPI stands, from no data to agreed. Status is a field on the metric, so every route shows it.</div></div></div>
      <div class="lifecycle">${cols}</div></div>`;
  }

  /* ------------------------------------------------------------- ownership */
  function ownershipHTML() {
    const tabs = [["owners", "Accountable owners"], ["departments", "Department responsibility"], ["measures", "Measures and data owners"]];
    const body = G.own === "owners" ? ownersHTML() : G.own === "departments" ? deptHTML() : measuresHTML();
    return `<div class="panel" id="gown"><div class="ph"><div><h3>Ownership</h3>
      <div class="sub">Three kinds, each read from the platform: who is accountable for a definition (metrics.yml), which department moves the number (the dashboard seeds), and who maintains the tables the measures read (the gold models).</div></div>
      <div class="segmented sm">${tabs.map(([k, l]) => `<button data-gown="${k}" class="${G.own === k ? "active" : ""}">${l}</button>`).join("")}</div></div>${body}</div>`;
  }

  function ownersHTML() {
    const k = kpis(), groups = {};
    for (const m of k) (groups[confirmed(m) ? m.owner : m.owner_proposed || "Unassigned"] ||= []).push(m);
    const rows = Object.entries(groups).sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
    const open = k.filter((m) => !confirmed(m)).length;
    return `${open ? `<div class="gnote warn"><b>${open} of ${k.length} business metrics (KPIs and backlog) have no confirmed owner.</b> Each has a proposed owner; the owner field stays <span class="mono">TBD</span> until they sign off, and the lint keeps the gap visible rather than letting it be left blank.</div>` : ""}
      <table class="gtable"><thead><tr><th>Owner</th><th>Accountable for</th><th class="num">Metrics</th><th>Sign-off</th></tr></thead><tbody>
      ${rows.map(([who, ms]) => `<tr><td><b>${esc(who)}</b></td><td><div class="gchips">${ms.map(chip).join("")}</div></td><td class="num">${ms.length}</td>
        <td>${ms.every(confirmed) ? `<span class="gy">✓</span> Confirmed` : `<span class="tbd">Proposed</span>`}</td></tr>`).join("")}</tbody></table>`;
  }

  function deptHTML() {
    const depts = Object.entries(G.data.departments).filter(([c]) => c !== "UNASSIGNED");
    const ms = kpis().filter((m) => m.departments.length);
    const cell = (m, code) => {
      const ds = m.departments.filter((d) => d.department === code);
      return ds.map((d) => `<span class="infl ${esc(d.influence)}" title="${esc(d.name)} ${esc(d.influence)} ${esc(m.label)} in ${esc(procName(d.process))}">${d.influence === "owns" ? "●" : "○"} ${esc(d.process)}</span>`).join("");
    };
    return `<div class="sub">From the project's <span class="mono">seeds/department_metric.csv</span>: the department-dashboard matrix.
      <span class="infl owns">● owns</span> <span class="infl contributes">○ contributes</span>, with the process it happens in.</div>
      <div class="tablewrap gwrap"><table class="gtable dept"><thead><tr><th>Metric</th>${depts.map(([, n]) => `<th class="c">${esc(n)}</th>`).join("")}<th class="c">Cut by department</th></tr></thead><tbody>
      ${ms.map((m) => `<tr data-gmetric="${esc(m.name)}"><td><b>${esc(m.label)}</b> ${pill(m.status)}</td>${depts.map(([c]) => `<td class="c">${cell(m, c)}</td>`).join("")}
        <td class="c">${m.source === "backlog" ? `<span class="faint">no number yet</span>` : m.department_attributable ? `<span class="gy">✓</span>` : `<span class="faint">no</span>`}</td></tr>`).join("")}</tbody></table></div>
      <div class="faint tiny">"Cut by department" is MetricFlow's answer: whether the metric's facts join to an employee, so a department page can show its own slice.</div>`;
  }

  function feeds(measure) {
    const users = (G.data.measure_uses[measure] || []).map(byName).filter(Boolean);
    const k = users.filter((m) => m.role === "kpi");
    if (k.length) return k.map(chip).join("");
    return `<span class="faint">${users.length ? `building blocks only (${users.map((m) => esc(m.label)).join(", ")})` : "no metric yet"}</span>`;
  }

  function measuresHTML() {
    const d = G.data;
    const owners = [...new Set(d.measures.map((m) => m.owner || "none"))];
    return `<div class="sub">Each measure is an aggregation over one bare column of a gold table (the lint enforces it), so every number traces to a table with a contract and a data owner.
      ${owners.length === 1 ? `All ${d.measures.length} measures read tables owned by <b>${esc(owners[0])}</b>.` : ""}</div>
      <div class="tablewrap gwrap"><table class="gtable"><thead><tr><th>Measure</th><th>Aggregation</th><th>Gold table</th><th>Data owner</th><th>Feeds</th></tr></thead><tbody>
      ${d.measures.map((ms) => `<tr><td class="mono">${esc(ms.name)}</td><td class="mono">${esc(ms.agg)}(${esc(ms.column)})</td>
        <td class="mono">gold.${esc(ms.table)}</td><td>${esc(ms.owner || "–")}</td>
        <td><div class="gchips">${feeds(ms.name)}</div></td></tr>`).join("")}</tbody></table></div>`;
  }

  /* --------------------------------------------------------------- catalog */
  function catalogRows() {
    let ms = G.data.metrics.filter((m) => (G.view === "all" ? true : G.view === "component" ? m.role === "component"
      : G.view === "backlog" ? m.source === "backlog" : m.role === "kpi" && m.source === "metricflow"));
    if (G.search) {
      const q = G.search.toLowerCase();
      ms = ms.filter((m) => [m.label, m.name, m.owner_proposed, m.description, ...m.departments.map((d) => d.name)].join(" ").toLowerCase().includes(q));
    }
    return ms;
  }

  function catalogHTML() {
    const all = G.data.metrics, n = (f) => all.filter(f).length;
    const views = [["kpi", "KPIs", n((m) => m.role === "kpi" && m.source === "metricflow")], ["backlog", "Backlog", n((m) => m.source === "backlog")],
      ["component", "Building blocks", n((m) => m.role === "component")], ["all", "All", all.length]];
    return `<div class="panel" id="gcatalog"><div class="ph"><div><h3>Metric catalogue</h3>
      <div class="sub">Every metric the platform knows, with everything governance needs. The same entries the data API, the MCP tools and docs/metric_catalog.md serve. Select one for its full record.</div></div>
      <div class="ph-tools"><div class="segmented sm">${views.map(([k, l, c]) => `<button data-gview="${k}" class="${G.view === k ? "active" : ""}">${l} <span class="faint">${c}</span></button>`).join("")}</div>
        <input id="gov-search" class="search" placeholder="Search metrics, owners, departments" value="${esc(G.search)}"></div></div>
      <div id="gcat-body">${catalogTable()}</div></div>`;
  }

  function catalogTable() {
    const rows = catalogRows();
    if (!rows.length) return `<div class="empty">No metric matches.</div>`;
    return `<div class="tablewrap gwrap"><table class="gtable cat"><thead><tr><th>Metric</th><th>Status</th><th>Accountable owner</th><th>Departments</th>
      <th>Process</th><th>Rolls up</th><th class="num">Pages</th><th class="num">Golden</th><th class="num">Caveats</th><th class="num">API/MCP</th></tr></thead><tbody>
      ${rows.map((m) => `<tr data-gmetric="${esc(m.name)}">
        <td><b>${esc(m.label)}</b><div class="mono tiny faint">${esc(m.name)}</div></td>
        <td>${pill(m.status)}</td><td>${ownerText(m)}</td>
        <td>${m.departments.filter((d) => d.influence === "owns").map((d) => esc(d.name)).join(", ") || `<span class="faint">–</span>`}</td>
        <td>${[...new Set(m.processes.map((p) => p.process))].map(esc).join(", ") || `<span class="faint">–</span>`}</td>
        <td>${m.rollup ? `<span class="mono">${esc(m.rollup)}</span>` : `<span class="faint">–</span>`}</td>
        <td class="num">${m.pages.length || `<span class="faint">0</span>`}</td>
        <td class="num">${m.golden.length || `<span class="faint">0</span>`}</td>
        <td class="num">${m.caveats.length || `<span class="faint">0</span>`}</td>
        <td class="num">${m.usage ? m.usage.requests : `<span class="faint">0</span>`}</td></tr>`).join("")}</tbody></table></div>`;
  }

  /* ---------------------------------------------------------- one metric */
  function openMetric(name) {
    const m = byName(name);
    if (!m) return;
    const def = m.definition || {};
    const formula = def.type === "ratio" ? `${esc(m.numerator_label || def.numerator)} ÷ ${esc(m.denominator_label || def.denominator)}`
      : def.type === "simple" ? `The ${esc(m.measures[0]?.agg || "sum")} of <span class="mono">${esc(def.measure)}</span>`
      : def.type === "derived" ? `<span class="mono">${esc(def.expr)}</span> over ${esc((def.metrics || []).join(", "))}`
      : def.type === "cumulative" ? `<span class="mono">${esc(def.measure)}</span> over a ${esc(def.window || "running")} window` : "";
    const reason = m.provisional_reason || m.blocked_reason || m.placeholder_reason;
    const tables = [...new Set(m.measures.map((x) => `gold.${x.table}`))];
    const lineage = m.source === "backlog" ? "" : `<div class="lineage-chain">
      <div><span>Gold table</span>${tables.map((t) => `<b class="mono">${esc(t)}</b>`).join("")}<em>${esc([...new Set(m.measures.map((x) => x.owner))].join(", "))}</em></div><i>→</i>
      <div><span>Measures</span>${m.measures.map((x) => `<b class="mono">${esc(x.agg)}(${esc(x.column)})</b>`).join("")}</div><i>→</i>
      <div class="me"><span>Metric</span><b>${esc(m.label)}</b><em>${esc(m.status)}</em></div><i>→</i>
      <div><span>Served by</span>${m.cubes.length ? `<b>${m.cubes.length} dashboard cube${m.cubes.length > 1 ? "s" : ""}</b>` : ""}<b>Data API · MCP</b>${m.dax ? "<b>Power BI measure</b>" : ""}</div></div>`;
    const entities = m.dimensions.entities.map(([e, c]) => `<span class="dimchip">${esc(e.replace(/_/g, " "))} <b>${c}</b></span>`).join("");
    const golden = m.golden.map((g) => `<div class="grow"><span class="mono">${esc(g.id)}</span>${g.refusal ? `<span class="gstat blocked">proves a refusal</span>`
      : `<span class="faint">${g.group_by.length ? `by ${esc(g.group_by.join(", "))}` : "total"}</span>`}</div>`).join("");
    openDrawer2(`<div class="gdrawer" data-name="${esc(m.name)}">
      <div class="eyebrow">${m.source === "backlog" ? "Backlog metric" : m.role === "component" ? "Building block" : "KPI"} · <span class="mono nocase">${esc(m.name)}</span></div>
      <h2>${esc(m.label)} ${pill(m.status)}</h2>${editable(m) ? `<label class="gedit"><span>Definition</span>
        <textarea class="rq-in" id="gov-description" data-gedit="description" rows="3" placeholder="What it tells you about the business, in plain words">${esc(m.description)}</textarea></label>`
        : `<p>${esc(m.description)}</p>`}
      ${lineage}
      <div class="gd-grid">
        <section><h4 class="mini">Governance</h4><dl>
          <dt>Status</dt><dd>${pill(m.status)} ${esc(G.data.stages.find((s) => s.id === m.status)?.means || "")}</dd>
          ${reason ? `<dt>Why</dt><dd>${esc(reason)}</dd>` : ""}
          ${(m.unblock_requires || []).length ? `<dt>Unblocked by</dt><dd>${m.unblock_requires.map(esc).join("<br>")}</dd>` : ""}
          ${m.caveats.length ? `<dt>Caveats</dt><dd>${m.caveats.map((c) => `<div class="caveat">${esc(c)}</div>`).join("")}</dd>` : ""}
          ${m.direction ? `<dt>Direction</dt><dd>${m.direction === "higher_is_better" ? "Higher is better" : "Lower is better"}</dd>` : ""}
          ${m.format ? `<dt>Format</dt><dd class="mono">${esc(m.format)}</dd>` : ""}
          ${m.is_data_quality ? `<dt>Kind</dt><dd>Data quality metric</dd>` : ""}
        </dl></section>
        <section><h4 class="mini">Ownership</h4><dl>
          <dt>Accountable</dt><dd>${editable(m) ? ownerEdit(m) : ownerText(m)}</dd>
          <dt>Departments</dt><dd>${m.departments.map((d) => `<div><span class="infl ${esc(d.influence)}">${d.influence === "owns" ? "●" : "○"} ${esc(d.influence)}</span> ${esc(d.name)} <span class="faint">in ${esc(procName(d.process))}</span></div>`).join("") || `<span class="faint">None mapped</span>`}</dd>
          ${m.measures.length ? `<dt>Data owner</dt><dd>${esc([...new Set(m.measures.map((x) => x.owner || "–"))].join(", "))} <span class="faint">(${esc(tables.join(", "))})</span></dd>` : ""}
        </dl></section>
        ${m.source === "backlog" ? "" : `<section><h4 class="mini">Definition</h4><dl>
          <dt>Type</dt><dd><span class="mono">${esc(def.type)}</span>${m.rollup ? ` · rolls up as <span class="mono">${esc(m.rollup)}</span>` : ""}</dd>
          <dt>Formula</dt><dd>${formula}</dd>
          ${def.filter ? `<dt>Filter</dt><dd class="mono">${esc(def.filter)}</dd>` : ""}
          <dt>Cut by</dt><dd>${m.dimensions.count} dimensions, and time at day to fiscal year<div class="dimchips">${entities}</div></dd>
        </dl></section>
        <section><h4 class="mini">Where it is used</h4><dl>
          <dt>Dashboards</dt><dd>${m.pages.map(esc).join(", ") || `<span class="faint">Not on a dashboard page</span>`}</dd>
          <dt>Processes</dt><dd>${[...new Set(m.processes.map((p) => procName(p.process)))].map(esc).join(", ") || `<span class="faint">–</span>`}</dd>
          <dt>API and MCP</dt><dd>${m.usage ? `${m.usage.requests} request${m.usage.requests > 1 ? "s" : ""} in the audit log (${Object.entries(m.usage.routes).map(([r, c]) => `${esc(r)} ${c}`).join(", ")}), last ${esc(new Date(m.usage.last).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }))}` : `<span class="faint">No requests in the audit log yet</span>`}</dd>
        </dl></section>`}
      </div>
      <h4 class="mini">Proof</h4>
      <div class="gproof">${golden || `<span class="faint">No golden answer names this metric.</span>`}</div>
      <div class="gtry"><button class="btn sm" data-gtry="${esc(m.name)}">Ask the semantic layer for it</button><span id="gtry-out" class="faint">Runs the same request the data API and MCP tools make.</span></div>
      ${m.dax ? `<h4 class="mini">Power BI measure (generated)</h4><pre class="code">${esc(m.dax)}</pre>` : ""}
      <h4 class="mini">As written in <span class="mono">${esc(m.yaml.path)}</span></h4>
      <pre class="yaml">${yamlHTML(m.yaml)}</pre>
      <p class="faint small-note">${editable(m) ? "The owner and definition above save as you type, each a commit to that file. " : ""}Anything else here is a reviewed change to that file. A changed number is a re-frozen golden answer.</p></div>`, true);
  }

  /* --------------------------------------------------------------- editing */
  // Definitions of KPIs and backlog metrics live in the requirements store; building blocks are build logic.
  const editable = (m) => m.role === "kpi" && !!window.Req;
  function ownerEdit(m) {
    const roles = {};
    for (const p of Object.values(G.data.people || {})) if (p.role) (roles[p.role] ||= []).push(p.name);
    const who = roles[m.owner];
    return `<input class="rq-in" id="gov-owner" data-gedit="owner" list="gov-roles" value="${esc(confirmed(m) ? m.owner : "")}" placeholder="TBD">
      <datalist id="gov-roles">${Object.entries(roles).map(([r, names]) => `<option value="${esc(r)}">${esc(names.join(", "))}</option>`).join("")}</datalist>
      <div class="faint tiny" id="gov-ownerwho">${who ? esc(who.join(", ")) : confirmed(m) ? "" : m.owner_proposed ? `Proposed: ${esc(m.owner_proposed)}` : "A role, so it outlasts the person. Empty is TBD."}</div>`;
  }

  const timers = {};
  function edit(name, field, value) {
    const m = byName(name);
    if (!m || !Req.editorOk()) return;
    m[field] = field === "owner" ? value.trim() || "TBD" : value;
    if (field === "owner") {
      const who = Object.values(G.data.people || {}).filter((p) => p.role && p.role === m.owner).map((p) => p.name);
      const el = $("#gov-ownerwho");
      if (el) el.textContent = who.join(", ");
    }
    const key = `${name}/${field}`;
    clearTimeout(timers[key]);
    timers[key] = setTimeout(async () => {
      try { await Req.call("PATCH", `/api/requirements/measure/${encodeURIComponent(name)}`, { [field]: value }); }
      catch (e) { toast(`Not saved: ${e.message}`); refresh(); }
    }, 600);
    render();
  }

  // A save from either page, or an edit in an editor: read the definitions again.
  async function refresh() {
    try { G.data = await api("/api/governance"); } catch { G.data = null; return; }
    if (root().classList.contains("active")) render();
    const d = $("#drawer-body .gdrawer");
    if (d && $("#drawer").classList.contains("open") && !d.contains(document.activeElement)) openMetric(d.dataset.name);
  }
  document.addEventListener("DOMContentLoaded", () => window.Req?.onChange((sections) => {
    if (!G.data || !sections.some((x) => ["measures", "people", "dashboards", "all"].includes(x))) return;
    if (root().classList.contains("active") || $("#drawer-body .gdrawer")) refresh();
    else G.data = null;
  }));

  async function tryIt(name) {
    const out = $("#gtry-out");
    out.className = "faint"; out.textContent = "Asking…";
    try {
      const r = await api("/api/metrics/query", { metrics: [name], group_by: [] });
      const g = r.metrics[0];
      out.className = "ok-text";
      out.textContent = `Returned ${r.rows.length} row${r.rows.length === 1 ? "" : "s"}, with status ${g.status}, owner ${g.owner}` +
        (g.caveats?.length ? ` and ${g.caveats.length} caveat${g.caveats.length > 1 ? "s" : ""}` : "") + " beside the number.";
    } catch (e) {
      const busy = /pipeline|no data yet/i.test(e.message);
      out.className = busy ? "faint" : "bad-text";
      out.textContent = `${busy ? "Not available right now" : "Refused"}: ${e.message}`;
    }
  }

  /* --------------------------------------------------------------- events */
  const root = () => $("#view-gov");
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-gmetric], [data-gview], [data-gown], [data-gtry]");
    if (!t || !(root().contains(t) || $("#drawer").contains(t))) return;
    if (t.dataset.gtry) return tryIt(t.dataset.gtry);
    if (t.dataset.gmetric) return openMetric(t.dataset.gmetric);
    if (t.dataset.gview) { G.view = t.dataset.gview; $("#gcatalog").outerHTML = catalogHTML(); return; }
    if (t.dataset.gown) { G.own = t.dataset.gown; $("#gown").outerHTML = ownershipHTML(); return; }
  });
  document.addEventListener("input", (e) => {
    const g = e.target.dataset?.gedit;
    if (g && $("#drawer").contains(e.target)) return edit(e.target.closest(".gdrawer").dataset.name, g, e.target.value);
    if (e.target.id !== "gov-search") return;
    G.search = e.target.value;
    $("#gcat-body").innerHTML = catalogTable();
  });

  return { show, open, summary };
})();
window.Gov = Gov;
