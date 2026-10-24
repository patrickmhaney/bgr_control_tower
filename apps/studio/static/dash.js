/* The Dashboards screen: one report page per saved query, read from marts.dashboard_cube.
   Every number comes from the API, which applies the Power BI measure templates. Nothing is computed here
   except how a number is shown: formats, deltas between two numbers the API returned, and sort order. */
"use strict";

const Dash = (() => {
  const D = { pages: null, page: null, metric: null, period: "month", asof: null, filters: {}, dim: null,
    split: false, sort: null, search: "", showAll: false, res: null };
  const PERIODS = [["month", "Month"], ["qtd", "QTD"], ["ytd", "YTD"], ["12m", "12M"]];
  const ALL = "__all";
  const page = () => D.pages.find((p) => p.id === D.page);
  const metaOf = (id) => page().metrics.find((m) => m.id === id);
  const plural = (label) => (/y$/.test(label) ? label.slice(0, -1) + "ies" : label + "s");
  const busyHTML = (msg) => `<div class="panel empty-state"><b>Data not available right now</b><p>${esc(msg)}</p></div>`;
  const statusPill = (st) => (st && st !== "active" ? `<span class="status ${st}">${esc(st)}</span>` : "");
  const chg = (cur, prev, m) => {
    const d = Charts.change(cur, prev, m.fmt, m.better);
    return d ? `<span class="chg ${d.tone}">${d.arrow} ${esc(d.text)}</span>` : "";
  };

  async function show() {
    if (!D.pages) {
      try { D.pages = (await api("/api/dashboards")).pages; }
      catch (e) { $("#dash-main").innerHTML = busyHTML(e.message); return; }
      D.page = D.pages[0].id;
    }
    renderNav();
    return refresh();
  }

  function renderNav() {
    const sections = [];
    for (const p of D.pages) {
      let s = sections.find((x) => x.name === p.section);
      if (!s) sections.push((s = { name: p.section, pages: [] }));
      s.pages.push(p);
    }
    $("#dash-nav").innerHTML = sections.map((s) => `<div class="dn-sec">${esc(s.name)}</div>${s.pages.map((p) =>
      `<button class="${p.id === D.page ? "active" : ""}" data-dpage="${p.id}"><span>${esc(p.title)}</span>${p.code ? `<span class="dn-code">${esc(p.code)}</span>` : ""}</button>`).join("")}`).join("");
  }

  async function refresh() {
    const main = $("#dash-main");
    main.classList.add("loading");
    const qs = new URLSearchParams({ period: D.period });
    if (D.metric) qs.set("metric", D.metric);
    if (D.asof) qs.set("asof", D.asof);
    if (D.dim) qs.set("dim", D.dim);
    if (Object.keys(D.filters).length) qs.set("filters", JSON.stringify(D.filters));
    try { D.res = await api(`/api/dashboards/${D.page}?${qs}`); }
    catch (e) { main.classList.remove("loading"); main.innerHTML = busyHTML(e.message); return; }
    D.metric = D.res.metric;
    render();
    main.classList.remove("loading");
  }

  /* ------------------------------------------------------------- render */
  function render() {
    const res = D.res, p = page(), sel = metaOf(res.metric);
    const others = p.dims.filter((d) => d.id !== "metric_time__month");
    const html = [header(p, res), filterBar(p, res, others)];
    const bars = barsHTML(res, sel, others);
    const few = res.cards.length <= (bars ? 1 : 2);
    const trendPanel = trendHTML(res, sel, others, !bars && !few);
    if (few) html.push(`<div class="dgrid side ${bars ? "three" : ""}"><div class="kstack">${res.cards.map((c) => cardHTML(c, res)).join("")}</div>${trendPanel}${bars}</div>`);
    else html.push(cardsHTML(p, res), `<div class="dgrid ${bars ? "" : "one"}">${trendPanel}${bars}</div>`);
    if (res.heatmap && res.heatmap.rows.filter((r) => r.values.some((v) => typeof v === "number")).length > 1) html.push(heatHTML(res, sel));
    if (res.matrix) html.push(matrixHTML(res, sel));
    if (res.table) html.push(tableHTML(res));
    else if (res.cards.length > 2) html.push(kpiTableHTML(p, res));
    html.push(lineage(p, res));
    $("#dash-main").innerHTML = html.join("");
    drawTrend();
  }

  function drawTrend() {
    const slot = $("#dash-main .trend-slot");
    if (slot && D.trendCfg) slot.innerHTML = Charts.trend({ ...D.trendCfg, width: Math.max(slot.clientWidth, 320) });
  }
  let resizing;
  window.addEventListener("resize", () => { clearTimeout(resizing); resizing = setTimeout(drawTrend, 120); });

  function header(p, res) {
    const today = S.state?.clock?.today;
    const refreshed = new Date(res.refreshed).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    return `<div class="dash-head">
      <div><div class="eyebrow">${esc(p.section)}${p.code ? ` · ${esc(p.code)}` : ""}</div><h2>${esc(p.title)}</h2>
        <p class="muted">${esc(p.description)}</p></div>
      <div class="dh-meta">
        <div class="fresh"><span class="fdot"></span>Data through <b>${today ? esc(shortDate(today)) : "–"}</b></div>
        <div class="faint">Warehouse refreshed ${esc(refreshed)}</div>
        <div class="dh-actions"><button class="btn ghost sm" id="dash-defs">Definitions</button>
          <button class="btn ghost sm" id="dash-csv">Export CSV</button></div>
      </div></div>`;
  }

  function filterBar(p, res, others) {
    const enc = (v) => esc(JSON.stringify(v));
    const slicers = others.map((d) => {
      const cur = d.id in res.filters ? JSON.stringify(res.filters[d.id]) : ALL;
      return `<label class="fgroup"><span>${esc(d.label)}</span><select data-dfilter="${d.id}" class="${cur !== ALL ? "set" : ""}">
        <option value="${ALL}">All ${esc(plural(d.label).toLowerCase())}</option>
        ${(res.filter_options[d.id] || []).map((v) => `<option value="${enc(v)}" ${JSON.stringify(v) === cur ? "selected" : ""}>${esc(v ?? "(blank)")}</option>`).join("")}</select></label>`;
    }).join("");
    const w = res.window;
    const cmp = res.comparisons.map((c) => c.label.replace(/^vs /, "")).join(" and ");
    const summary = w.partial
      ? `<b>${esc(w.label)}</b>, month to date (${esc(w.progress)}). Amounts are not compared until the month closes.`
      : `<b>${esc(w.label)}</b>, compared with ${esc(cmp)}`;
    return `<div class="fbar">
      <div class="fgroup"><span>Period</span><div class="segmented sm">${PERIODS.map(([k, l]) =>
        `<button data-dperiod="${k}" class="${k === res.period ? "active" : ""}">${l}</button>`).join("")}</div></div>
      <label class="fgroup"><span>As of</span><select id="dash-asof">${res.months.map((m) =>
        `<option value="${m.value}" ${m.value === res.asof ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select></label>
      ${slicers}
      ${Object.keys(res.filters).length ? `<button class="linkbtn" id="dash-clear">Clear filters</button>` : ""}
      <div class="fsum">${summary}</div></div>`;
  }

  /* --------------------------------------------------------------- cards */
  function cardHTML(c, res) {
    const m = metaOf(c.metric);
    let deltas;
    if (c.as_of !== undefined) {
      const at = c.as_of ? new Date(c.as_of + "T00:00:00") : null;
      const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
      const lab = (n) => (at ? `vs ${Charts.monthLong(iso(new Date(at.getFullYear(), at.getMonth() - n, 1)))}` : "");
      deltas = [["prev", lab(1)], ["py", lab(12)]];
    } else deltas = res.comparisons.map((k) => [k.key, k.label]);
    const lines = deltas.map(([k, label]) => {
      if (c.cmp[k] === null && m.kind === "sum" && res.window.partial) return "";
      const d = chg(c.value, c.cmp[k], m);
      return `<div class="kd">${d || `<span class="chg flat">–</span>`}<span>${esc(label)}</span></div>`;
    }).join("");
    const mtd = m.kind === "sum" && res.window.partial ? `<div class="kd"><span class="chg flat">MTD</span><span>month to date, not compared</span></div>` : "";
    const base = m.denominator && typeof c.base === "number"
      ? `Based on ${esc(fmtNum(c.base, m.denominator_fmt))} ${esc(m.denominator.toLowerCase())}` : "";
    const tone = (() => {
      const d = Charts.change(c.value, c.cmp[deltas[0][0]], m.fmt, m.better);
      return d ? d.tone : "flat";
    })();
    return `<div class="kpi ${c.metric === res.metric ? "selected" : ""}" data-dmetric="${c.metric}" role="button" tabindex="0">
      <div class="kt"><span class="kl">${esc(m.label)}</span>
        ${m.caveats.length ? `<span class="kwarn" title="${esc(m.caveats.join("\n"))}">!</span>` : ""}
        <span class="kinfo" data-ddef="${c.metric}" title="Definition" role="button" tabindex="0">i</span></div>
      <div class="kv">${fmtNum(c.value, m.fmt)}</div>
      <div class="kds">${lines}${mtd}</div>
      <div class="ks tone-${tone}">${Charts.spark2(c.spark)}<span class="faint">12 mo</span></div>
      ${c.note || base || m.status !== "active" ? `<div class="kn">${statusPill(m.status)}<span>${c.note ? esc(c.note) : base}</span></div>` : ""}</div>`;
  }

  function cardsHTML(p, res) {
    const n = res.cards.length, cols = n <= 6 ? n : Math.ceil(n / 2);
    if (!p.groups) return `<div class="kpis" style="--cols:${cols}">${res.cards.map((c) => cardHTML(c, res)).join("")}</div>`;
    const groups = [];
    res.cards.forEach((c, i) => {
      let g = groups.find((x) => x.name === p.groups[i]);
      if (!g) groups.push((g = { name: p.groups[i], cards: [] }));
      g.cards.push(c);
    });
    return `<div class="kgroups">${groups.map((g) => `<section class="kgroup" style="--n:${g.cards.length}">
      <h4>${esc(g.name)}</h4><div class="kgrid">${g.cards.map((c) => cardHTML(c, res)).join("")}</div></section>`).join("")}</div>`;
  }

  /* --------------------------------------------------------------- trend */
  function trimmed(res) {
    // Start the time axis where this cube's data starts.
    const t = res.trend;
    let i = t.months.findIndex((_, k) => typeof t.values[k] === "number" || typeof t.prior[k] === "number");
    if (i < 0) i = 0;
    return i;
  }

  function trendHTML(res, sel, others, wide = false) {
    const t = res.trend, from = trimmed(res);
    const months = t.months.slice(from);
    const dimLabel = res.heatmap ? res.heatmap.label : null;
    const canSplit = !!res.heatmap && res.heatmap.rows.length > 1 && !(res.heatmap.dim in res.filters);
    const split = D.split && canSplit;
    let series;
    if (split) {
      series = res.heatmap.rows.slice(0, 4).map((r, i) => ({ label: r.label ?? "(blank)", values: r.values.slice(from), color: Charts.SERIES[i] }));
      if (sel.kind !== "sum") series.push({ label: `All ${plural(dimLabel).toLowerCase()}`, values: res.heatmap.overall.slice(from), color: "var(--ink-2)", dash: true });
    } else {
      series = [{ label: "This year", values: t.values.slice(from), area: true },
        { label: "A year earlier", values: t.prior.slice(from), color: "var(--ink-3)", dash: true }];
    }
    // Drawn once the panel is on the page, at its real width, so the text is never scaled.
    D.trendCfg = { months, series, fmt: sel.fmt, partial: t.partial, band: split ? null : [res.window.start, res.window.end],
      height: wide ? 280 : 270, additive: sel.kind === "sum" };
    const chart = series.some((x) => x.values.some((v) => typeof v === "number")) ? `<div class="trend-slot"></div>` : "";
    const legend = split
      ? series.map((s) => `<span class="lg"><i class="${s.dash ? "dash" : ""}" style="border-color:${s.color}"></i>${esc(s.label)}</span>`).join("")
      : `<span class="lg"><i style="border-color:var(--accent)"></i>${esc(sel.label)}</span><span class="lg"><i class="dash" style="border-color:var(--ink-3)"></i>A year earlier</span>
         <span class="lg"><b class="bandkey"></b>Selected period</span>`;
    const mtd = sel.kind === "sum" && t.values[t.months.indexOf(t.partial)] !== null && t.values[t.months.indexOf(t.partial)] !== undefined
      ? ` · ${Charts.monthLong(t.partial)} to date is in the tooltip, not plotted` : "";
    const sub = (split ? `Largest ${Math.min(4, res.heatmap.rows.length)} ${plural(dimLabel).toLowerCase()} by volume` : `Monthly, ${Charts.monthLong(months[0])} to date`) + mtd;
    return `<div class="panel">
      <div class="ph"><div><h3>${esc(sel.label)} by month</h3><div class="sub">${esc(sub)}</div></div>
        ${canSplit ? `<div class="segmented sm"><button data-dsplit="0" class="${split ? "" : "active"}">Trend</button><button data-dsplit="1" class="${split ? "active" : ""}">By ${esc(dimLabel.toLowerCase())}</button></div>` : ""}</div>
      ${chart ? `<div class="legend">${legend}</div>${chart}` : `<div class="empty">${esc(t.note || "No data.")}</div>`}</div>`;
  }

  /* ------------------------------------------------------------ breakdown */
  function barsHTML(res, sel, others) {
    if (res.matrix && res.matrix.dims.length === 1) return matrixBars(res, sel);
    if (!res.breakdown || !res.table || res.table.rows.length < 2) return "";
    const tb = res.table, cmpLabel = res.comparisons.find((c) => c.key === res.first_cmp).label.replace(/^vs /, "");
    const largest = tb.rows.length > 10;
    let rows = tb.rows.slice(0, 10).map((r) => ({ label: r.label, value: r.cur[sel.id], prev: r.cmp[sel.id], weight: r.cur._weight,
      weightLabel: res.breakdown.basis || null }));
    const asc = sel.kind !== "sum" && sel.better === "down";
    rows = rows.filter((r) => typeof r.value === "number").sort((a, b) => (asc ? a.value - b.value : b.value - a.value));
    const selected = res.breakdown.dim in res.filters ? res.filters[res.breakdown.dim] : undefined;
    const picker = others.length > 1 ? `<select id="dash-dim">${others.map((x) => `<option value="${x.id}" ${x.id === res.breakdown.dim ? "selected" : ""}>By ${esc(x.label.toLowerCase())}</option>`).join("")}</select>` : "";
    const all = `All ${plural(res.breakdown.label).toLowerCase()}`;
    const bars = Charts.hbars({ rows, fmt: sel.fmt, better: sel.better, reference: sel.kind === "sum" ? null : tb.total.cur[sel.id],
      refLabel: "All", selected, cmpLabel });
    const what = largest ? `${rows.length} largest ${plural(res.breakdown.label).toLowerCase()}${res.breakdown.basis ? ` by ${res.breakdown.basis.toLowerCase()}` : ""}, ${sel.kind === "sum" ? "largest" : "best"} first`
      : sel.kind === "sum" ? "Largest first" : "Best first";
    return `<div class="panel">
      <div class="ph"><div><h3>${esc(sel.label)} by ${esc(res.breakdown.label.toLowerCase())}</h3>
        <div class="sub">${esc(res.window.label)} · ${esc(what)}</div></div>${picker}</div>
      ${bars || `<div class="empty">No data for this period.</div>`}
      <div class="keyrow"><span><i class="k-tick"></i>${esc(cmpLabel)}</span>${sel.kind !== "sum" ? `<span><i class="k-ref"></i>${esc(all)}</span>` : ""}
        <span class="faint">Select a bar to filter the page</span></div></div>`;
  }

  /* -------------------------------------------------------------- heatmap */
  function heatHTML(res, sel) {
    const h = res.heatmap, from = trimmed(res);
    const months = h.months.slice(from);
    const cols = months.map((m) => ({ label: Charts.monthTick(m), title: Charts.monthLong(m) + (m === res.trend.partial ? " (to date)" : ""), dim: m === res.trend.partial }));
    const all = `All ${plural(h.label).toLowerCase()}`;
    const grid = Charts.heatmap({ cols, rows: h.rows.map((r) => ({ label: r.label, values: r.values.slice(from) }))
      .filter((r) => r.values.some((v) => typeof v === "number")),
      overall: h.overall.slice(from), fmt: sel.fmt, better: sel.better, kind: sel.kind, allLabel: all });
    const how = sel.kind === "sum" ? "Darker is larger." : `Each cell against ${all.toLowerCase()} that month: <span class="sw better"></span> better <span class="sw worse"></span> worse.`;
    return `<div class="panel">
      <div class="ph"><div><h3>${esc(sel.label)} by ${esc(h.label.toLowerCase())} and month</h3>
        <div class="sub">${how}${h.more ? ` The ${h.rows.length} largest by volume; ${h.more} more in the table below.` : ""}</div></div></div>
      ${grid || `<div class="empty">No data.</div>`}</div>`;
  }

  /* A fixed metric at the cube's full grain: a grid of its two dimensions, or bars for one. */
  function matrixHTML(res, sel) {
    const mx = res.matrix;
    if (mx.dims.length !== 2) return "";
    const colKeys = [...new Set(mx.rows.map((r) => r[1]))], rowKeys = [...new Set(mx.rows.map((r) => r[0]))];
    const at = (a, b) => mx.rows.find((r) => r[0] === a && r[1] === b)?.[2];
    const cols = colKeys.map((k) => ({ label: k ?? "(blank)", title: `${mx.dims[1].label}: ${k ?? "(blank)"}` }));
    const grid = Charts.heatmap({ cols, rows: rowKeys.map((r) => ({ label: r, values: colKeys.map((k) => at(r, k)) })),
      overall: mx.company, fmt: sel.fmt, better: sel.better, kind: "fixed", allLabel: "Company" });
    return `<div class="panel">
      <div class="ph"><div><h3>${esc(sel.label)} by ${esc(mx.dims[0].label.toLowerCase())} and ${esc(mx.dims[1].label.toLowerCase())}</h3>
        <div class="sub">${esc(mx.month)}, at the cube's own grain. ${typeof mx.company === "number"
          ? `Shaded against the company value, ${esc(fmtNum(mx.company, sel.fmt))}: <span class="sw better"></span> better <span class="sw worse"></span> worse.` : ""}
          This metric does not add up across rows, so there are no subtotals.</div></div></div>
      ${grid || `<div class="empty">No data.</div>`}</div>`;
  }

  function matrixBars(res, sel) {
    const mx = res.matrix;
    const rows = mx.rows.map((r) => ({ label: r[0], value: r[1] })).filter((r) => typeof r.value === "number")
      .sort((a, b) => (sel.better === "down" ? a.value - b.value : b.value - a.value));
    return `<div class="panel"><div class="ph"><div><h3>${esc(sel.label)} by ${esc(mx.dims[0].label.toLowerCase())}</h3>
      <div class="sub">${esc(mx.month)}, at the cube's own grain</div></div></div>
      ${Charts.hbars({ rows, fmt: sel.fmt, better: sel.better, reference: mx.company, refLabel: "Company", cmpLabel: "" })}</div>`;
  }

  /* --------------------------------------------------------------- tables */
  function sortedRows(tb) {
    let rows = tb.rows;
    if (D.search) rows = rows.filter((r) => String(r.label ?? "").toLowerCase().includes(D.search.toLowerCase()));
    if (D.sort) {
      const { col, dir } = D.sort;
      rows = [...rows].sort((a, b) => {
        const x = col === "_label" ? a.label : a.cur[col], y = col === "_label" ? b.label : b.cur[col];
        if (x === null || x === undefined) return 1;
        if (y === null || y === undefined) return -1;
        return (typeof x === "string" ? x.localeCompare(y) : x - y) * dir;
      });
    }
    return rows;
  }

  function tableHTML(res) {
    const tb = res.table, ms = tb.metrics.map(metaOf);
    const rows = sortedRows(tb), limit = D.showAll ? rows.length : 15;
    const selected = tb.dim in res.filters ? res.filters[tb.dim] : undefined;
    const cmpLabel = res.comparisons.find((c) => c.key === res.first_cmp).label;
    const arrow = (col) => (D.sort && D.sort.col === col ? (D.sort.dir > 0 ? " ↑" : " ↓") : "");
    const cell = (r, m) => `<td class="num ${m.id === res.metric ? "hl" : ""}"><div class="tv">${fmtNum(r.cur[m.id], m.fmt)}</div><div class="td">${chg(r.cur[m.id], r.cmp[m.id], m)}</div></td>`;
    const search = tb.rows.length > 15 ? `<input id="dash-search" class="search" placeholder="Search ${esc(plural(tb.label).toLowerCase())}" value="${esc(D.search)}">` : "";
    return `<div class="panel">
      <div class="ph"><div><h3>${esc(tb.label)} scorecard</h3><div class="sub">${esc(res.window.label)} · change ${esc(cmpLabel)} · ${tb.rows.length} ${esc(plural(tb.label).toLowerCase())}, largest first</div></div>
        <div class="ph-tools">${search}</div></div>
      <div class="tablewrap scard"><table class="grid-table ${ms.length <= 2 ? "narrow" : ""}">
        <thead><tr><th data-dsort="_label">${esc(tb.label)}${arrow("_label")}</th>${ms.map((m) => `<th class="num ${m.id === res.metric ? "hl" : ""}" data-dsort="${m.id}">${esc(m.label)}${arrow(m.id)}</th>`).join("")}</tr></thead>
        <tbody><tr class="total"><td>All ${esc(plural(tb.label).toLowerCase())}</td>${ms.map((m) => cell(tb.total, m)).join("")}</tr>
        ${rows.slice(0, limit).map((r) => `<tr class="${selected !== undefined && selected === r.label ? "sel" : ""}" data-xfilter="${esc(JSON.stringify(r.label))}">
          <td>${esc(r.label ?? "(blank)")}</td>${ms.map((m) => cell(r, m)).join("")}</tr>`).join("")}</tbody></table></div>
      ${rows.length > limit ? `<button class="linkbtn more" id="dash-more">Show all ${rows.length}</button>` : ""}</div>`;
  }

  /* The company page: the monthly KPI pack, one row per metric. */
  function kpiTableHTML(p, res) {
    const months = res.spark_months.slice(-6);
    const off = res.spark_months.length - months.length;
    const groups = p.groups || p.metrics.map(() => "");
    let last = null;
    const body = res.cards.map((c, i) => {
      const m = metaOf(c.metric);
      const head = groups[i] !== last && groups[i] ? `<tr class="grp"><td colspan="${months.length + 5}">${esc(groups[i])}</td></tr>` : "";
      last = groups[i];
      return `${head}<tr class="${c.metric === res.metric ? "sel" : ""}" data-dmetric="${c.metric}">
        <td><div class="tm">${esc(m.label)} ${statusPill(m.status)}</div><div class="faint tiny">${esc(m.owner === "TBD" ? `Owner TBD${m.owner_proposed ? ` (proposed: ${m.owner_proposed})` : ""}` : m.owner || "")}</div></td>
        ${months.map((_, k) => `<td class="num">${fmtNum(c.spark[off + k], m.fmt)}</td>`).join("")}
        <td class="num hl"><b>${fmtNum(c.value, m.fmt)}</b></td>
        ${res.comparisons.map((k) => `<td class="num">${chg(c.value, c.cmp[k.key], m) || `<span class="faint">–</span>`}</td>`).join("")}
        <td>${Charts.spark2(c.spark, { width: 96, height: 24, color: "var(--accent)" })}</td></tr>`;
    }).join("");
    return `<div class="panel">
      <div class="ph"><div><h3>KPI pack</h3><div class="sub">Each metric by month, and for ${esc(res.window.label)} with its comparisons. Select a row to chart it.</div></div></div>
      <div class="tablewrap scard"><table class="grid-table kpack">
        <thead><tr><th>Metric</th>${months.map((m) => `<th class="num">${esc(Charts.monthTick(m))}</th>`).join("")}<th class="num hl">${esc(res.window.label)}</th>
          ${res.comparisons.map((k) => `<th class="num">${esc(k.label)}</th>`).join("")}<th>12 months</th></tr></thead>
        <tbody>${body}</tbody></table></div></div>`;
  }

  function lineage(p, res) {
    const kinds = {};
    for (const m of p.metrics) kinds[m.kind] = (kinds[m.kind] || 0) + 1;
    const names = { sum: "SUM", ratio: "DIVIDE(SUM, SUM)", fixed: "single-row value" };
    return `<div class="lineage">
      <div><span>Source</span><span class="mono">marts.dashboard_cube</span> where <span class="mono">_cube = '${esc(p.id)}'</span> · grain ${p.dims.map((d) => esc(d.label)).join(" × ")}</div>
      <div><span>Measures</span>${Object.entries(kinds).map(([k, n]) => `${n} ${esc(names[k])}`).join(" · ")} - the templates the Power BI model is generated from</div>
      ${res.sql ? `<details><summary>Query behind the cards</summary><pre class="code">${esc(res.sql)}</pre></details>` : ""}</div>`;
  }

  /* ---------------------------------------------------------- definitions */
  function defHTML(m) {
    const pagesWith = D.pages.filter((p) => p.metrics.some((x) => x.id === m.id)).map((p) => p.title);
    return `<div class="def">
      <div class="eyebrow">Metric definition</div><h2>${esc(m.label)} ${statusPill(m.status)}</h2>
      <p>${esc(m.description)}</p>
      <dl>
        ${m.numerator ? `<dt>Formula</dt><dd>${esc(m.numerator)} ÷ ${esc(m.denominator)}</dd>` : ""}
        <dt>Owner</dt><dd>${esc(m.owner || "TBD")}${m.owner_proposed ? ` <span class="faint">(proposed: ${esc(m.owner_proposed)})</span>` : ""}</dd>
        <dt>Direction</dt><dd>${m.better === "up" ? "Higher is better" : m.better === "down" ? "Lower is better" : "Neutral"}</dd>
        <dt>Rolls up as</dt><dd>${esc({ sum: "A sum: adds up to any grain", ratio: "A ratio of two sums: correct at any grain", fixed: "Fixed: shown only at its cube's own grain" }[m.kind])}</dd>
        <dt>On pages</dt><dd>${pagesWith.map(esc).join(", ")}</dd>
      </dl>
      ${m.provisional_reason ? `<div class="caveat"><b>Why provisional.</b> ${esc(m.provisional_reason)}</div>` : ""}
      ${m.caveats.map((c) => `<div class="caveat">${esc(c)}</div>`).join("")}
      <h4 class="mini">Power BI measure</h4><pre class="code">${esc(m.dax)}</pre>
      <h4 class="mini">The same template in SQL</h4><pre class="code">${esc(m.sql)}</pre>
      <p class="faint small-note">Defined once in transform/models/semantic/metrics.yml. Every route - this page, Power BI, the API, the MCP tools - reads this definition.</p></div>`;
  }

  function allDefs() {
    const p = page();
    openDrawer(`<div class="eyebrow">${esc(p.title)}</div><h2>Definitions</h2><p class="muted">The ${p.metrics.length} metrics on this page, as the semantic layer defines them.</p>
      ${p.metrics.map((m) => `<button class="defrow" data-ddef="${m.id}"><b>${esc(m.label)}</b> ${statusPill(m.status)}<span>${esc(m.description)}</span></button>`).join("")}`);
  }

  /* ------------------------------------------------------------------ csv */
  function exportCsv() {
    const res = D.res, q = (v) => (v === null || v === undefined ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
    let lines;
    if (res.table) {
      const tb = res.table, cmp = res.comparisons.find((c) => c.key === res.first_cmp).label;
      lines = [[tb.label, ...tb.metrics.flatMap((m) => [metaOf(m).label, `${metaOf(m).label} (${cmp.replace(/^vs /, "")})`])],
        ...[{ label: "All", ...tb.total }, ...sortedRows(tb)].map((r) => [r.label, ...tb.metrics.flatMap((m) => [r.cur[m], r.cmp[m]])])];
    } else {
      lines = [["Metric", ...res.spark_months, res.window.label, ...res.comparisons.map((k) => k.label.replace(/^vs /, ""))],
        ...res.cards.map((c) => [metaOf(c.metric).label, ...c.spark, c.value, ...res.comparisons.map((k) => c.cmp[k.key])])];
    }
    const blob = new Blob([lines.map((l) => l.map(q).join(",")).join("\n")], { type: "text/csv" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `${D.page}_${res.asof.slice(0, 7)}_${res.period}.csv` });
    a.click(); URL.revokeObjectURL(a.href);
    toast("Exported the table as CSV");
  }

  /* --------------------------------------------------------------- events */
  const root = () => $("#view-dash");
  function setFilter(dim, value) {
    if (dim in D.filters && D.filters[dim] === value) delete D.filters[dim];
    else D.filters[dim] = value;
    D.showAll = false;
    return refresh();
  }

  document.addEventListener("click", (e) => {
    if (!root().contains(e.target) && !$("#drawer").contains(e.target)) return;
    const def = e.target.closest("[data-ddef]");
    if (def) { e.stopPropagation(); return openDrawer(defHTML(metaOf(def.dataset.ddef))); }
    const t = e.target.closest("[data-dpage], [data-dmetric], [data-dperiod], [data-dsplit], [data-dsort], [data-xfilter], button");
    if (!t || !root().contains(t)) return;
    if (t.dataset.dpage) {
      Object.assign(D, { page: t.dataset.dpage, metric: null, dim: null, filters: {}, sort: null, search: "", showAll: false, split: false });
      renderNav(); return refresh();
    }
    if (t.dataset.dmetric) { D.metric = t.dataset.dmetric; return refresh(); }
    if (t.dataset.dperiod) { D.period = t.dataset.dperiod; return refresh(); }
    if (t.dataset.dsplit) { D.split = t.dataset.dsplit === "1"; return render(); }
    if (t.dataset.dsort) {
      const col = t.dataset.dsort;
      D.sort = D.sort && D.sort.col === col ? (D.sort.dir < 0 ? { col, dir: 1 } : null) : { col, dir: col === "_label" ? 1 : -1 };
      return render();
    }
    if (t.dataset.xfilter !== undefined) {
      const dim = D.res.table ? D.res.table.dim : D.res.breakdown?.dim;
      if (dim) return setFilter(dim, JSON.parse(t.dataset.xfilter));
    }
    switch (t.id) {
      case "dash-clear": D.filters = {}; return refresh();
      case "dash-defs": return allDefs();
      case "dash-csv": return exportCsv();
      case "dash-more": D.showAll = true; return render();
    }
  });
  document.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && root().contains(e.target) && e.target.matches("[data-dmetric], [data-ddef]")) {
      e.preventDefault(); e.target.click();
    }
  });
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (!root().contains(t)) return;
    if (t.id === "dash-asof") { D.asof = t.value; return refresh(); }
    if (t.id === "dash-dim") { D.dim = t.value; D.sort = null; return refresh(); }
    if (t.dataset.dfilter) {
      if (t.value === ALL) delete D.filters[t.dataset.dfilter]; else D.filters[t.dataset.dfilter] = JSON.parse(t.value);
      return refresh();
    }
  });
  document.addEventListener("input", (e) => {
    if (e.target.id !== "dash-search") return;
    D.search = e.target.value;
    const pos = e.target.selectionStart;
    render();
    const inp = $("#dash-search"); inp.focus(); inp.setSelectionRange(pos, pos);
  });

  return { show };
})();
window.Dash = Dash;
