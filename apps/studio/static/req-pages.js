/* The Requirements screens: Overview, Processes, Bus matrix, Measures and
   Ownership. Each draws from Req.R.data (the snapshot of the project's files)
   and saves through Req. Sketches are in req-sketch.js. */
"use strict";

(() => {
  const { R, save, act, openEntry, entry, label, done, meter, istat, mstat, interview, plural, person, depts, deptName,
    whoText, whoDept, placements, processOf, onDashboard, isProcess, me, UNOWNED } = Req;
  const pages = R.pages;
  const procs = () => Object.entries(R.data.processes);
  const dims = () => Object.entries(R.data.dimensions);
  const ticked = (p, d) => (R.data.bus_matrix[p] || []).includes(d);

  /* ------------------------------------------------------------ new codes */
  // Every entry is keyed by a code that never changes: made from its name, editable before it's added.
  const words = (s) => s.split(/[^A-Za-z0-9]+/).filter(Boolean);
  const CODE = {
    process: (n) => words(n).map((w) => (w.toLowerCase() === "to" ? "2" : w[0])).join("").toUpperCase(),
    dashboard: (n) => CODE.process(n),
    dimension: (n) => words(n).join("_").toLowerCase(),
    department: (n) => (words(n).length > 1 ? words(n).map((w) => w[0]).join("") : words(n)[0]?.slice(0, 5) || "").toUpperCase(),
  };
  const PATTERN = { process: /^[A-Z][A-Z0-9]*$/, dashboard: /^[A-Z][A-Z0-9]*$/, dimension: /^[a-z][a-z0-9_]*$/, department: /^[A-Z][A-Z0-9_]*$/ };
  const taken = (kind) => new Set(kind === "department" ? depts().map((d) => d.department_code)
    : Object.keys(R.data[{ process: "processes", dashboard: "dashboards", dimension: "dimensions" }[kind]]));
  function codeFor(kind, name) {
    let base = CODE[kind](name);
    if (base && !/^[A-Za-z]/.test(base)) base = (kind === "dimension" ? "d_" : "X") + base;
    let code = base, n = 2;
    while (code && taken(kind).has(code)) code = base + (kind === "dimension" ? "_" : "") + n++;
    return code;
  }
  const addForm = (kind, placeholder, button) => `<form class="rq-addform" data-rq="add" data-kind="${kind}">
    <input class="rq-in" name="name" data-rq="addname" data-kind="${kind}" placeholder="${esc(placeholder)}" required>
    <input class="rq-in rq-code mono" name="code" data-rq="addcode" placeholder="Code" title="Its key in the files. It can't change after.">
    <button class="btn sm">${esc(button)}</button></form>`;

  async function add(kind, name, code, extra = {}) {
    name = name.trim();
    code = (code || codeFor(kind, name)).trim();
    if (!PATTERN[kind].test(code)) {
      toast(kind === "dimension" ? "A dimension code is lower case, e.g. customer." : "A code is capitals and digits, e.g. O2C.");
      return null;
    }
    const out = await act("POST", `/api/requirements/${kind}`, { key: code, value: { name, ...extra } }, `Added ${name}`);
    if (out && (kind === "process" || kind === "dimension")) openEntry(kind, code);
    return out;
  }

  // Shared by the pages: opening anything, and the add forms.
  const common = {
    click(rq, t) {
      if (rq === "open") { openEntry(t.dataset.k, t.dataset.v, t.dataset.f ? { focus: t.dataset.f } : {}); return true; }
      if (rq === "starter") { add(t.dataset.k, t.dataset.v); return true; }
      return undefined;
    },
    field(rq, t, e) {
      if (rq === "addname" && e.type === "input") {
        const code = t.form.elements.code;
        if (code.dataset.auto !== "0") code.value = t.value.trim() ? codeFor(t.dataset.kind, t.value) : "";
        return true;
      }
      if (rq === "addcode" && e.type === "input") { t.dataset.auto = t.value ? "0" : ""; return true; }
      return undefined;
    },
    async submit(rq, data, f) {
      if (rq !== "add") return undefined;
      if (await add(f.dataset.kind, data.name, data.code)) f.reset();
      return true;
    },
  };
  pages.common = common;

  /* ============================================================== OVERVIEW */
  function suggestions() {
    // "process:dimension" -> the measures that break down by a dimension their process doesn't tick.
    const out = new Map();
    for (const [name, m] of Object.entries(R.data.measures)) {
      const p = processOf(name);
      if (!p || !R.data.processes[p]) continue;
      for (const d of m.answers?.dimensions || []) {
        if (ticked(p, d) || !R.data.dimensions[d]) continue;
        const k = `${p}:${d}`;
        out.set(k, [...(out.get(k) || []), name]);
      }
    }
    return out;
  }
  const onGrid = () => Object.keys(R.data.measures).filter((n) => placements(n).length);
  const isOwned = (kind, key) => (kind === "measure"
    ? ![UNOWNED, ""].includes(R.data.measures[key].definition.owner || "")
    : !!whoText(entry(kind, key).answers?.owner));

  // What a measure with no number is waiting for, in words.
  function waiting(name) {
    const m = R.data.measures[name], d = m.definition, a = m.answers || {};
    const out = [];
    if (!(a.formula || "").trim()) out.push("how it's calculated (question 3)");
    const unmapped = [...(a.sources || [])].filter((s) => !R.data.project.business_systems[s]);
    if (unmapped.length) out.push(`${unmapped.join(", ")} connected as a source`);
    if (d.status === "blocked") out.push("data no source system has");
    for (const u of d.unblock_requires || []) out.push(u.replace(/\.$/, ""));
    if (!isOwned("measure", name)) out.push("an owner");
    return out;
  }

  pages.overview = {
    draw(main) {
      const P = procs(), D = dims(), M = onGrid(), dashboards = Object.keys(R.data.dashboards);
      const complete = (list, kind) => list.filter((k) => interview(entry(kind, k)) === "complete").length;
      const ticks = Object.values(R.data.bus_matrix).reduce((n, l) => n + l.length, 0);
      const sketched = dashboards.filter((c) => (R.data.sketches[c] || []).length);
      const card = (n, screen, title, what, d, total, line) => `<button class="rq-ovstep" data-rq="screen" data-k="${screen}">
        <span class="rq-ovn">${n}</span><b>${esc(title)}</b><span class="faint">${esc(what)}</span>
        <span class="rq-minibar"><i style="width:${total ? (100 * d) / total : 0}%"></i></span><span class="rq-ovline">${esc(line)}</span></button>`;

      const todo = [];
      const need = (text, screen, button) => todo.push(`<li><span>${esc(text)}</span><button class="btn sm" data-rq="screen" data-k="${screen}">${esc(button)}</button></li>`);
      if (!P.length) need("List the business processes the warehouse should cover.", "processes", "Add processes");
      const unowned = P.filter(([k]) => !isOwned("process", k)).length + D.filter(([k]) => !isOwned("dimension", k)).length
        + M.filter((k) => !isOwned("measure", k)).length;
      if (unowned) need(`${plural(unowned, "item")} ${unowned === 1 ? "has" : "have"} no owner.`, "ownership", "See which");
      const noSteps = P.filter(([, p]) => !(p.answers?.steps || []).some((s) => (s.name || "").trim())).length;
      if (noSteps) need(`${plural(noSteps, "process", "processes")} ${noSteps === 1 ? "has" : "have"} no steps mapped.`, "processes", "Map steps");
      if (P.length && !D.length) need("Add the dimensions the business analyses by, then tick them on the bus matrix.", "bus", "Add dimensions");
      const sugg = suggestions().size;
      if (sugg) need(`The bus matrix has ${plural(sugg, "suggested tick")} from measure breakdowns.`, "bus", "Review");
      const unlinked = M.filter((n) => !processOf(n)).length;
      if (unlinked && P.length) need(`${plural(unlinked, "measure")} ${unlinked === 1 ? "isn't" : "aren't"} linked to a business process.`, "measures", "Link them");
      const all = [...P.map(([, e]) => e), ...D.map(([, e]) => e), ...Object.values(R.data.measures)];
      const follow = all.filter((e) => e.followup).length;
      if (follow) need(`${plural(follow, "item")} ${follow === 1 ? "needs" : "need"} follow-up.`, "measures", "Measures");
      const unknown = all.reduce((n, e) => n + Object.keys(e.unknown || {}).length, 0);
      if (unknown) need(`${plural(unknown, "question")} answered "I don't know". They're listed in docs/open_questions.md with who might know.`, "measures", "Measures");
      const unsketched = dashboards.filter((c) => !sketched.includes(c) && onDashboard(c).length);
      if (unsketched.length) need(`${unsketched.join(", ")} ${unsketched.length === 1 ? "has" : "have"} measures but no sketch.`, "sketches", "Sketch");

      const backlog = Object.keys(R.data.measures).filter((n) => R.data.measures[n].definition.file === "backlog.yml");
      const notBuilt = backlog.map((n) => {
        const w = waiting(n), m = R.data.measures[n];
        return `<li><div><button class="linkbtn" data-rq="open" data-k="measure" data-v="${esc(n)}">${esc(m.definition.label || n)}</button> ${mstat(m.definition.status)}
          ${m.definition.reason ? `<div class="faint">${esc(m.definition.reason)}</div>` : ""}</div>
          <div class="rq-wait">${w.length ? `Waiting for ${w.map(esc).join("; ")}.` : `<span class="rq-ready">Ready to build</span>`}</div></li>`;
      }).join("");
      const problems = R.data.problems.length ? `<div class="panel rq-problems"><h3>The files have ${plural(R.data.problems.length, "problem")}</h3>
        <p class="sub">Probably from an edit made outside the Studio. Saves still work; fix these in the files.</p>
        <ul>${R.data.problems.map((p) => `<li class="mono">${esc(p)}</li>`).join("")}</ul></div>` : "";

      main.innerHTML = `${problems}<div class="rq-ovsteps">
          ${card(1, "processes", "Processes", "What the business does, step by step, and who does each step.", complete(P.map(([k]) => k), "process"), P.length,
            P.length ? `${complete(P.map(([k]) => k), "process")} of ${plural(P.length, "process", "processes")} complete` : "None yet")}
          ${card(2, "bus", "Bus matrix", "What each process is analysed by. Shared dimensions are defined once.", complete(D.map(([k]) => k), "dimension"), D.length,
            D.length ? `${plural(D.length, "dimension")} · ${plural(ticks, "tick")}` : "No dimensions yet")}
          ${card(3, "measures", "Measures", "The numbers on each dashboard, defined once, with an owner.", complete(M, "measure"), M.length,
            M.length ? `${complete(M, "measure")} of ${plural(M.length, "measure")} complete` : "None defined yet")}
          ${card(4, "sketches", "Sketches", "Each dashboard sketched: what goes where, and what it shows.", sketched.length, dashboards.length,
            `${sketched.length} of ${plural(dashboards.length, "dashboard")} sketched`)}
        </div>
        <div class="rq-ovgrid">
          <div class="panel"><h3>Needs attention</h3><ul class="rq-todo">${todo.join("") || `<li class="faint">Nothing outstanding.</li>`}</ul></div>
          <div class="panel"><h3>Not built yet</h3>
            <p class="sub">Measures the business asked for that have no number yet, and what each is waiting for. To build the ready ones,
              ask Claude Code to "build the measures that are ready". A definition edited later needs no build.</p>
            <ul class="rq-notbuilt">${notBuilt || `<li class="faint">Every measure asked for has a number.</li>`}</ul></div>
        </div>`;
    },
  };

  /* ============================================================= PROCESSES */
  const STARTERS = ["Order to Cash", "Procure to Pay", "Inventory to Delivery", "Record to Report", "Hire to Retire", "Plan to Produce"];
  const PRIORITY = { now: "Now", next: "Next", later: "Later" };

  function swimlane(code, p) {
    const steps = (p.answers?.steps || []).filter((s) => (s.name || "").trim());
    if (!steps.length) return `<button class="rq-lanes-empty" data-rq="open" data-k="process" data-v="${esc(code)}" data-f="steps">+ Add the main steps</button>`;
    const laneOf = (s) => whoDept(s) || "none";
    const lanes = [...new Set(steps.map(laneOf))].sort((a, b) => (a === "none") - (b === "none"));
    const cells = lanes.map((lane, r) => `<div class="rq-lanelabel" style="grid-row:${r + 1}">${esc(lane === "none" ? "Not assigned" : deptName(lane))}</div>
      <div class="rq-laneband" style="grid-row:${r + 1}"></div>`).join("");
    const boxes = steps.map((s, i) => {
      const sub = [s.person ? person(s.person)?.name : "", s.system].filter(Boolean).join(" · ");
      return `<button class="rq-lstep" style="grid-row:${lanes.indexOf(laneOf(s)) + 1};grid-column:${i + 2}" data-rq="open" data-k="process" data-v="${esc(code)}" data-f="steps" title="${esc(s.name)}">
        <span class="rq-lstepn">${i + 1}. ${esc(s.name)}</span>${sub ? `<span class="rq-lstepsub">${esc(sub)}</span>` : ""}</button>`;
    }).join("");
    return `<div class="rq-lanes-wrap"><div class="rq-lanes" style="--steps:${steps.length}">${cells}${boxes}</div><svg class="rq-lanes-svg" aria-hidden="true"></svg></div>`;
  }

  // Elbow arrows from each step to the next, once the boxes are laid out.
  function connectors() {
    document.querySelectorAll("#rq-main .rq-lanes-wrap").forEach((wrap, n) => {
      const out = wrap.querySelector("svg"), r = wrap.getBoundingClientRect();
      const box = { left: r.left - wrap.scrollLeft, top: r.top };
      const steps = [...wrap.querySelectorAll(".rq-lstep")].map((el) => el.getBoundingClientRect());
      out.setAttribute("width", wrap.scrollWidth);
      out.setAttribute("height", r.height);
      const paths = steps.slice(0, -1).map((a, i) => {
        const b = steps[i + 1];
        const x1 = a.right - box.left, y1 = a.top + a.height / 2 - box.top, x2 = b.left - box.left - 2, y2 = b.top + b.height / 2 - box.top;
        const xm = (x1 + x2) / 2;
        return `<path d="${Math.abs(y1 - y2) < 1 ? `M${x1},${y1} H${x2}` : `M${x1},${y1} H${xm} V${y2} H${x2}`}" marker-end="url(#rq-arrow-${n})"/>`;
      }).join("");
      out.innerHTML = `<defs><marker id="rq-arrow-${n}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z"/></marker></defs>${paths}`;
    });
  }
  window.addEventListener("resize", () => { if (R.screen === "processes") connectors(); });

  pages.processes = {
    draw(main) {
      const P = procs();
      const list = !P.length ? `<div class="panel empty-state"><b>No processes yet.</b><p>Start with the three or four the business depends on most.</p>
          <div class="rq-starters">${STARTERS.map((n) => `<button class="btn sm" data-rq="starter" data-k="process" data-v="${esc(n)}">${esc(n)}</button>`).join("")}</div></div>`
        : P.map(([code, p]) => {
          const a = p.answers || {}, owner = whoText(a.owner);
          const measures = Object.keys(R.data.measures).filter((n) => processOf(n) === code).length;
          const nd = (R.data.bus_matrix[code] || []).length;
          const active = R.open?.kind === "process" && R.open.key === code;
          return `<article class="panel rq-proc ${active ? "active" : ""}">
            <button class="rq-proch" data-rq="open" data-k="process" data-v="${esc(code)}">
              <span class="rq-proct"><b>${esc(p.name || code)}</b><span class="mono faint">${esc(code)}</span>${a.priority ? `<span class="rq-tag">${PRIORITY[a.priority]}</span>` : ""}</span>
              <span class="rq-procm"><span class="${owner ? "" : "faint"}">${owner ? `Owner: ${esc(owner)}` : "No owner yet"}</span>
                <span class="rq-procs">${p.followup ? `<span class="rq-flag">Follow-up</span>` : ""}${istat(p)}${meter("process", p)}</span></span></button>
            ${a.purpose ? `<p class="rq-purpose">${esc(a.purpose)}</p>` : ""}
            ${swimlane(code, p)}
            <div class="rq-procf"><span>${plural(measures, "measure")}</span>
              <button class="linkbtn" data-rq="screen" data-k="bus">${plural(nd, "dimension")}</button>
              ${a.event ? `<span class="faint">Records: ${esc(a.event)}</span>` : ""}</div></article>`;
        }).join("");
      main.innerHTML = `<div class="rq-guide"><b>A business process is work the business does over and over that creates data:</b> taking an order, buying
          stock, paying people. List the main ones, the steps in each, and who does each step. The warehouse is organised around them.</div>
        <div class="rq-toolbar">${addForm("process", "Process name, e.g. Order to Cash", "+ Add a process")}</div>
        <div class="rq-proclist">${list}</div>`;
      requestAnimationFrame(connectors);
    },
  };

  /* ============================================================ BUS MATRIX */
  function dashboardView(code) {
    const measures = onDashboard(code), byProc = [];
    for (const n of measures) {
      const p = processOf(n);
      if (!p || !R.data.processes[p]) continue;
      let e = byProc.find((x) => x.p === p);
      if (!e) byProc.push(e = { p, measures: [] });
      e.measures.push(n);
    }
    const order = Object.keys(R.data.processes);
    byProc.sort((a, b) => order.indexOf(a.p) - order.indexOf(b.p));
    const all = [], some = [];
    for (const [d] of dims()) {
      const on = byProc.filter((e) => ticked(e.p, d));
      if (on.length && on.length === byProc.length) all.push(d);
      else if (on.length) some.push({ d, measures: on.flatMap((e) => e.measures) });
    }
    return { measures, procs: byProc, all, some, unlinked: measures.filter((n) => !byProc.some((e) => e.measures.includes(n))) };
  }
  Req.dashboardView = dashboardView;
  const mnames = (list) => list.map((n) => label("measure", n)).join(", ");
  const dname = (d) => R.data.dimensions[d]?.name || d;

  function tick(p, d, on) {
    const order = Object.keys(R.data.dimensions);
    const list = (R.data.bus_matrix[p] || []).filter((x) => x !== d).concat(on ? [d] : [])
      .sort((a, b) => order.indexOf(a) - order.indexOf(b));
    save("bus", p, list, 0);
  }

  pages.bus = {
    view: null,
    draw(main) {
      const P = procs(), D = dims(), sugg = suggestions();
      if (this.view && !R.data.dashboards[this.view]) this.view = null;
      const v = this.view ? dashboardView(this.view) : null;
      const toolbar = `<div class="rq-toolbar">${addForm("process", "Process name", "+ Process")}${addForm("dimension", "Dimension, e.g. Customer", "+ Dimension")}
        <label class="rq-pick">Dashboard <select data-rq="busview"><option value="">All processes</option>
          ${Object.entries(R.data.dashboards).map(([c, d]) => `<option value="${esc(c)}" ${c === this.view ? "selected" : ""}>${esc(c)}${d.name ? ` · ${esc(d.name)}` : ""}</option>`).join("")}</select></label></div>`;
      const guide = `<div class="rq-guide"><b>The bus matrix shows what each process can be analysed by.</b> Tick a box to see that process by that
        dimension. A dimension ticked for several processes is shared, and defined once. Dashed boxes are suggestions from the breakdowns on the measures.
        Pick a dashboard to see which filters work across all of it.</div>`;
      if (!D.length) {
        main.innerHTML = `${guide}${toolbar}<div class="panel empty-state"><b>No dimensions yet.</b><p>Add the things the business slices its numbers by.</p>
          <div class="rq-starters">${["Date", "Customer", "Product", "Site", "Supplier", "Employee"].map((n) => `<button class="btn sm" data-rq="starter" data-k="dimension" data-v="${n}">${n}</button>`).join("")}</div></div>`;
        return;
      }
      const used = (d) => P.filter(([p]) => ticked(p, d)).length;
      const head = D.map(([d, x]) => {
        const n = used(d);
        let fit = "", use = n > 1 ? `Shared · ${n}` : n === 1 ? "1 process" : "Not used";
        if (v) [fit, use] = v.all.includes(d) ? ["v-all", "Whole dashboard"] : v.some.some((s) => s.d === d) ? ["v-some", "Some measures"] : ["v-out", "Not used here"];
        return `<button class="rq-buscol ${interview(x)} ${fit}" data-rq="open" data-k="dimension" data-v="${esc(d)}" title="Open ${esc(x.name || d)}">
          <span class="rq-buscoln">${esc(x.name || d)}</span><span class="rq-buscolu">${esc(use)}</span></button>`;
      }).join("");
      const rows = P.map(([p, x]) => {
        const inView = v?.procs.find((e) => e.p === p);
        const sub = v ? (inView ? mnames(inView.measures) : "Not on this dashboard")
          : [whoText(x.answers?.owner), x.answers?.event ? `Records: ${x.answers.event}` : ""].filter(Boolean).join(" · ") || "No owner yet";
        const cells = D.map(([d]) => {
          const on = ticked(p, d), s = sugg.get(`${p}:${d}`);
          const fit = !v ? "" : !inView ? "v-out" : v.all.includes(d) ? "v-all" : "";
          const t = `${x.name || p} by ${dname(d)}`;
          return `<button class="rq-buscell ${on ? "on" : s ? "sugg" : ""} ${fit}" data-rq="tick" data-k="${esc(p)}" data-v="${esc(d)}" aria-pressed="${on}"
            title="${esc(on ? t : s ? `Suggested: ${mnames(s)} ${s.length === 1 ? "breaks" : "break"} down by ${dname(d)}` : t)}"><i></i></button>`;
        }).join("");
        return `<button class="rq-busrow ${interview(x)} ${v ? (inView ? "v-in" : "v-out") : ""}" data-rq="open" data-k="process" data-v="${esc(p)}">
          <span class="rq-busrown">${esc(x.name || p)}</span><span class="rq-busrows">${esc(sub)}</span></button>${cells}
          <div class="rq-buscount">${(R.data.bus_matrix[p] || []).length}</div>`;
      }).join("");
      main.innerHTML = `${guide}${toolbar}<div class="rq-buslayout">
        <div class="rq-gridwrap"><div class="rq-bus ${v ? "viewing" : ""}" style="--dims:${D.length}">
          <div class="rq-buscorner">Process · Dimension</div>${head}<div></div>${rows}</div></div>
        <aside class="panel rq-checks">${v ? viewHTML(v, sugg) : checksHTML(sugg)}</aside></div>`;
    },
    click(rq, t) {
      if (rq !== "tick") return undefined;
      tick(t.dataset.k, t.dataset.v, !ticked(t.dataset.k, t.dataset.v));
      return true;
    },
    field(rq, t, e) {
      if (rq !== "busview" || e.type !== "change") return undefined;
      this.view = t.value || null;
      Req.draw();
      return true;
    },
  };

  const suggestionItem = (k, ms) => {
    const [p, d] = k.split(":");
    return `<li><span><b>${esc(label("process", p))} by ${esc(dname(d))}?</b> ${esc(mnames(ms))} ${ms.length === 1 ? "breaks" : "break"} down by it.</span>
      <button class="btn sm" data-rq="tick" data-k="${esc(p)}" data-v="${esc(d)}">Tick</button></li>`;
  };

  function checksHTML(sugg) {
    const items = [...sugg].map(([k, ms]) => suggestionItem(k, ms));
    for (const [p, x] of procs()) {
      if (!(R.data.bus_matrix[p] || []).length) items.push(`<li><span>${esc(x.name || p)} has no dimensions ticked.</span></li>`);
      if (!x.answers?.event && !("event" in (x.unknown || {}))) {
        items.push(`<li><span>Say what ${esc(x.name || p)} records, at its finest detail.</span><button class="btn sm" data-rq="open" data-k="process" data-v="${esc(p)}" data-f="event">Answer</button></li>`);
      }
    }
    for (const [d, x] of dims()) {
      const n = procs().filter(([p]) => ticked(p, d)).length;
      if (!n) items.push(`<li><span>${esc(x.name || d)} isn't ticked for any process.</span></li>`);
      else if (n > 1 && !whoText(x.answers?.owner)) {
        items.push(`<li><span>${esc(x.name || d)} is shared by ${n} processes but has no owner.</span><button class="btn sm" data-rq="open" data-k="dimension" data-v="${esc(d)}" data-f="owner">Name one</button></li>`);
      }
    }
    return `<h3>Checks</h3><ul class="rq-checklist">${items.join("") || `<li class="faint">Nothing to check.</li>`}</ul>`;
  }

  function viewHTML(v, sugg) {
    const d = R.data.dashboards[pages.bus.view];
    const sec = (title, body) => `<section><h4>${esc(title)}</h4>${body}</section>`;
    let body = "";
    if (!v.measures.length) body = `<p class="faint">No measures on this dashboard yet.</p>`;
    else {
      body += sec("Measures come from", v.procs.length
        ? `<ul>${v.procs.map((e) => `<li><b>${esc(label("process", e.p))}</b> <span class="faint">${esc(mnames(e.measures))}</span></li>`).join("")}</ul>`
        : `<p class="faint">None of its measures are linked to a process yet.</p>`);
      if (v.procs.length) {
        body += sec("Filters for the whole dashboard", `<p>${v.all.length ? esc(v.all.map(dname).join(", "))
          : `None yet. No dimension is ticked for ${v.procs.length === 1 ? "its process" : `all ${v.procs.length} of its processes`}.`}</p>`);
        if (v.some.length) body += sec("Filters for some measures only", `<ul>${v.some.map((x) => `<li><b>${esc(dname(x.d))}</b> <span class="faint">${esc(mnames(x.measures))}</span></li>`).join("")}</ul>`);
      }
      if (v.unlinked.length) {
        body += sec("Not linked to a process", `<ul>${v.unlinked.map((n) => `<li><span>${esc(label("measure", n))}</span>
          <button class="btn sm" data-rq="open" data-k="measure" data-v="${esc(n)}">Link</button></li>`).join("")}</ul>`);
      }
      const mine = new Set(v.measures);
      const ticks = [...sugg].map(([k, ms]) => [k, ms.filter((n) => mine.has(n))]).filter(([, ms]) => ms.length);
      if (ticks.length) body += sec("Suggested ticks", `<ul class="rq-checklist">${ticks.map(([k, ms]) => suggestionItem(k, ms)).join("")}</ul>`);
    }
    return `<h3>${esc(pages.bus.view)}${d.name ? ` · ${esc(d.name)}` : ""}</h3>${body}
      <p><button class="linkbtn" data-rq="sketchof" data-k="${esc(pages.bus.view)}">Sketch this dashboard</button></p>`;
  }

  /* ============================================================== MEASURES */
  const FILTERS = [["all", "All"], ["mine", "Mine"], ["followup", "Needs follow-up"], ["unassigned", "Unassigned"], ["unknown", "Don't know"]];
  function matches(name) {
    const m = R.data.measures[name];
    if (R.filter === "mine") return !!me() && m.assignee === me();
    if (R.filter === "followup") return !!m.followup;
    if (R.filter === "unassigned") return !m.assignee;
    if (R.filter === "unknown") return Object.keys(m.unknown || {}).length > 0;
    return true;
  }
  function at() {
    const out = {};
    for (const [name, m] of Object.entries(R.data.measures)) for (const p of m.placements) (out[p.dashboard] ||= {})[p.slot] = name;
    return out;
  }

  pages.measures = {
    draw(main) {
      const slots = R.data.project.slots || 4, grid = at(), dashes = Object.entries(R.data.dashboards);
      const placed = onGrid(), c = { not_started: 0, in_progress: 0, complete: 0 };
      placed.forEach((n) => c[interview(R.data.measures[n])]++);
      const follow = placed.filter((n) => R.data.measures[n].followup).length;
      const filled = Object.values(grid).reduce((n, row) => n + Object.keys(row).length, 0);
      const pct = (x) => (placed.length ? (100 * x) / placed.length : 0);
      const summary = `<div class="rq-progress"><div class="rq-big">${c.complete} <small>of ${plural(placed.length, "measure")} on the dashboards complete</small></div>
        <div class="rq-bar2"><i class="ok" style="width:${pct(c.complete)}%"></i><i class="warn" style="width:${pct(c.in_progress)}%"></i></div>
        <div class="rq-legend"><span><i class="ok"></i>${c.complete} complete</span><span><i class="warn"></i>${c.in_progress} in progress</span>
          <span><i></i>${c.not_started} not started</span><span><i class="flag"></i>${follow} need follow-up</span>
          <span class="faint">${dashes.length * slots - filled} empty slots</span></div></div>`;
      const filters = `<div class="segmented sm">${FILTERS.map(([k, l]) => `<button data-rq="filter" data-k="${k}" class="${R.filter === k ? "active" : ""}">${l}</button>`).join("")}</div>`;

      const cols = Array.from({ length: slots }, (_, i) => `<div class="rq-colh"><span>Measure ${i + 1}</span>${i === slots - 1 && slots > 1
        ? `<button class="rq-del" data-rq="rmslot" title="Remove the last measure column (only when it's empty)">×</button>` : ""}</div>`).join("");
      const rows = dashes.map(([code, d]) => {
        const here = Object.values(grid[code] || {});
        const doneHere = here.filter((n) => interview(R.data.measures[n]) === "complete").length;
        const cells = Array.from({ length: slots }, (_, i) => {
          const slot = `M${i + 1}`, name = grid[code]?.[slot];
          if (!name) return `<button class="rq-cell rq-cempty" data-rq="cell" data-k="${esc(code)}" data-v="${slot}"><span class="rq-cname">+ Add a measure</span></button>`;
          const m = R.data.measures[name], others = m.placements.filter((p) => p.dashboard !== code);
          const share = others.length === 1 ? `Also on ${others[0].dashboard}` : others.length ? `Also on ${others.length} more` : "";
          const who = m.assignee ? person(m.assignee)?.name || m.assignee : "";
          const active = R.open?.kind === "measure" && R.open.key === name;
          return `<button class="rq-cell ${interview(m)} ${R.filter !== "all" && !matches(name) ? "dim" : ""} ${active ? "active" : ""}" data-rq="cell" data-k="${esc(code)}" data-v="${slot}">
            <span class="rq-ctop"><span class="rq-cname">${esc(m.definition.label || name)}</span>${mstat(m.definition.status)}</span>
            ${share ? `<span class="rq-cshare">${esc(share)}</span>` : ""}
            <span class="rq-cwho">${who ? esc(m.assignee === me() ? "You" : who) : "Unassigned"}</span>
            <span class="rq-cfoot">${istat(m)}${m.followup ? `<span class="rq-flag">Follow-up</span>` : meter("measure", m)}</span></button>`;
        }).join("");
        return `<div class="rq-rowh"><button class="rq-del" data-rq="rmdash" data-k="${esc(code)}" title="Delete ${esc(code)}">×</button>
          <span class="rq-dcode mono">${esc(code)}</span>
          <input class="rq-dname" id="rq-dname-${esc(code)}" data-rq="dashname" data-k="${esc(code)}" value="${esc(d.name || "")}" placeholder="Add a name">
          <span class="rq-rcount">${doneHere} of ${here.length} complete</span></div>${cells}<div></div>`;
      }).join("");

      const free = Object.keys(R.data.processes).filter((p) => !R.data.dashboards[p]);
      const addDash = `<form class="rq-addform" data-rq="dashadd">
        <select name="process" data-rq="dashpick"><option value="">A dashboard of its own</option>
          ${free.map((p) => `<option value="${esc(p)}">For process ${esc(label("process", p))}</option>`).join("")}</select>
        <input class="rq-in rq-code mono" name="code" placeholder="Code, e.g. OPS" required>
        <input class="rq-in" name="name" placeholder="Name, e.g. Operations">
        <button class="btn sm">+ Add a dashboard</button></form>`;
      const loose = Object.keys(R.data.measures).filter((n) => !placements(n).length);
      main.innerHTML = `${summary}
        <div class="rq-toolbar">${filters}<span class="rq-spacer"></span>
          <span class="faint">Click a cell to open its questions. Changes save as you type.</span></div>
        <div class="rq-gridwrap"><div class="rq-grid" style="--slots:${slots}">
          <div class="rq-colh">Dashboard</div>${cols}
          ${slots < 12 ? `<button class="rq-addcol" data-rq="addslot" title="Add a measure column">+</button>` : "<div></div>"}
          ${rows}</div></div>
        <div class="rq-toolbar">${addDash}</div>
        ${loose.length ? `<div class="panel rq-loose"><h3>Not on a dashboard</h3>
          <p class="sub">Defined, but in no slot. Open one to answer its questions, or put it in an empty slot from that slot.</p>
          <div class="gchips">${loose.map((n) => `<button class="gchip ${esc(R.data.measures[n].definition.status || "")}" data-rq="open" data-k="measure" data-v="${esc(n)}">${esc(label("measure", n))}</button>`).join("")}</div></div>` : ""}`;
    },

    click(rq, t) {
      const { k, v } = t.dataset;
      switch (rq) {
        case "filter":
          R.filter = k;
          if (k === "mine" && !me()) toast("Put your name under Who's editing? first; it has to match a name in People.");
          Req.draw();
          return true;
        case "cell": {
          const name = at()[k]?.[v];
          if (name) openEntry("measure", name, { via: { dashboard: k, slot: v } });
          else openEntry("slot", `${k}/${v}`, { dashboard: k, slot: v });
          return true;
        }
        case "addslot": act("PUT", "/api/requirements/settings", { slots: (R.data.project.slots || 4) + 1 }); return true;
        case "rmslot": act("PUT", "/api/requirements/settings", { slots: (R.data.project.slots || 4) - 1 }); return true;
        case "rmdash": {
          const n = onDashboard(k).length;
          if (!confirm(`Delete the ${k} dashboard${n ? ` and take its ${plural(n, "measure")} off it` : ""}? The measures stay defined, under "Not on a dashboard"; its sketch goes with it. Undo puts it back.`)) return true;
          act("DELETE", `/api/requirements/dashboard/${k}`, undefined, `Deleted ${k}`);
          return true;
        }
        case "place": {
          const { dashboard, slot } = R.open;
          act("PUT", `/api/requirements/slots/${dashboard}/${slot}`, { metric: k }, `Showing ${label("measure", k)} on ${dashboard}`)
            .then((out) => { if (out) openEntry("measure", k, { via: { dashboard, slot } }); });
          return true;
        }
      }
      return undefined;
    },

    field(rq, t, e) {
      if (rq === "dashname" && e.type === "input") { save("dashboard", t.dataset.k, { name: t.value }); return true; }
      if (rq === "dashpick" && e.type === "change") {
        const f = t.form;
        f.elements.code.value = t.value;
        f.elements.name.value = t.value ? label("process", t.value) : "";
        return true;
      }
      if (rq === "useexisting" && e.type === "change" && t.value) { this.click("place", { dataset: { k: t.value } }); return true; }
      if (rq === "newlabel" && e.type === "input") { $("#rq-twin").innerHTML = twinHTML(t.value); return true; }
      return undefined;
    },

    async submit(rq, data, f) {
      if (rq === "dashadd") {
        const code = data.code.trim().toUpperCase();
        if (!/^[A-Z][A-Z0-9]*$/.test(code)) { toast("A dashboard code is capitals and digits, e.g. OPS."); return true; }
        if (await act("POST", "/api/requirements/dashboard", { key: code, value: { name: data.name.trim() } }, `Added ${code}`)) f.reset();
        return true;
      }
      if (rq === "newmeasure") {
        const { dashboard, slot } = R.open;
        const out = await act("POST", "/api/requirements/measure", { value: { label: data.label.trim() }, dashboard, slot }, `Added ${data.label.trim()}`);
        if (out) openEntry("measure", out.key, { via: { dashboard, slot }, focus: "definition" });
        return true;
      }
      return undefined;
    },

    /** An empty cell: define a new measure there, or show one defined already. */
    slotDrawer(open) {
      const { dashboard, slot } = open, d = R.data.dashboards[dashboard];
      const head = `<div class="eyebrow">${esc(dashboard)}${d?.name ? ` · ${esc(d.name)}` : ""} · Measure ${esc(slot.slice(1))}</div>`;
      const now = at()[dashboard]?.[slot];
      if (!d) return `${head}<h2>This dashboard is gone</h2>`;
      if (now) return `${head}<h2>${esc(label("measure", now))}</h2><p>Someone has just filled this slot.</p>
        <button class="btn sm" data-rq="cell" data-k="${esc(dashboard)}" data-v="${esc(slot)}">Open it</button>`;
      const here = new Set(onDashboard(dashboard));
      const groups = {};
      for (const n of Object.keys(R.data.measures)) {
        if (here.has(n)) continue;
        const where = placements(n)[0]?.dashboard;
        (groups[where ? `On ${where}${R.data.dashboards[where]?.name ? ` · ${R.data.dashboards[where].name}` : ""}` : "Not on a dashboard"] ||= []).push(n);
      }
      return `${head}<h2>An empty slot</h2>
        <h4>Define a new measure</h4>
        <form class="rq-addform" data-rq="newmeasure"><input class="rq-in" id="rq-newlabel" name="label" data-rq="newlabel" placeholder="e.g. Order Fill Rate" required autofocus>
          <button class="btn sm primary">Add</button></form>
        <div id="rq-twin"></div>
        <p class="rq-hint">The name the business knows it by. Its key in the files is made from it and never changes after.</p>
        ${Object.keys(groups).length ? `<h4>Or show one that's already defined</h4>
          <p>One definition, the same number everywhere it's shown.</p>
          <select data-rq="useexisting"><option value="">Choose a measure</option>${Object.entries(groups).map(([g, ns]) =>
            `<optgroup label="${esc(g)}">${ns.map((n) => `<option value="${esc(n)}">${esc(label("measure", n))}</option>`).join("")}</optgroup>`).join("")}</select>` : ""}`;
    },
  };

  // A new name that matches a measure already defined is probably that measure.
  function twinHTML(text) {
    const q = text.trim().toLowerCase();
    if (!q) return "";
    const key = q.replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
    const twin = Object.keys(R.data.measures).find((n) => n === key || (label("measure", n) || "").toLowerCase() === q);
    if (!twin) return "";
    const on = onDashboard(R.open.dashboard).includes(twin);
    const where = placements(twin).map((p) => p.dashboard).join(", ");
    return `<div class="rq-share">${on ? `<b>${esc(label("measure", twin))}</b> is already on this dashboard.`
      : `<b>${esc(label("measure", twin))}</b> is already defined${where ? ` (on ${esc(where)})` : ""}. If it's the same measure, show it here instead of defining it again.
        <button class="btn sm" data-rq="place" data-k="${esc(twin)}">Show it here</button>`}</div>`;
  }

  /* ============================================================= OWNERSHIP */
  // The department that owns something: its own, or its person's. "none" for an owner with no department, null for no owner.
  function ownerDept(kind, key) {
    if (kind === "measure") {
      const o = R.data.measures[key].definition.owner || "";
      if (!o || o === UNOWNED) return null;
      const p = Object.values(R.data.people).find((x) => x.role === o);
      return p?.department || "none";
    }
    const w = entry(kind, key).answers?.owner;
    return w ? whoDept(w) || "none" : null;
  }
  const link = (kind, key) => `<button class="linkbtn" data-rq="open" data-k="${kind}" data-v="${esc(key)}" data-f="owner">${esc(label(kind, key))}</button>`;
  const joined = (list) => list.join(", ") || `<span class="faint">–</span>`;

  pages.ownership = {
    draw(main) {
      const P = procs().map(([k]) => k), D = dims().map(([k]) => k), M = Object.keys(R.data.measures);
      const gaps = [["Processes", "process", P], ["Dimensions", "dimension", D], ["Measures", "measure", M]]
        .map(([l, kind, keys]) => [l, keys.filter((k) => ownerDept(kind, k) === null).map((k) => link(kind, k))]).filter(([, l]) => l.length);
      const steps = new Map();
      for (const [code, p] of procs()) for (const s of p.answers?.steps || []) {
        if ((s.name || "").trim()) { const d = whoDept(s) || "none"; steps.set(d, [...(steps.get(d) || []), `${s.name} (${p.name || code})`]); }
      }
      const rows = [...depts().map((d) => [d.department_code, d.department_name]), ["none", "No department"]].map(([id, name]) => {
        const ps = P.filter((k) => ownerDept("process", k) === id), ds = D.filter((k) => ownerDept("dimension", k) === id);
        const ms = M.filter((k) => ownerDept("measure", k) === id), st = steps.get(id) || [];
        if (!ps.length && !ds.length && !ms.length && !st.length) return "";
        return `<tr><td><b>${esc(name)}</b></td><td>${joined(ps.map((k) => link("process", k)))}</td>
          <td>${st.length ? `<span title="${esc(st.join("\n"))}">${plural(st.length, "step")}</span>` : `<span class="faint">–</span>`}</td>
          <td>${joined(ds.map((k) => link("dimension", k)))}</td><td>${joined(ms.map((k) => link("measure", k)))}</td></tr>`;
      }).join("");
      const moves = depts().filter((d) => R.data.department_metrics.some((r) => r.department_code === d.department_code)).map((d) => {
        const inf = (kind) => R.data.department_metrics.filter((r) => r.department_code === d.department_code && r.influence === kind)
          .map((r) => `${R.data.measures[r.metric_name] ? link("measure", r.metric_name) : esc(r.metric_name)} <span class="faint">(${esc(r.process_code)})</span>`);
        return `<tr><td><b>${esc(d.department_name)}</b></td><td>${joined(inf("owns"))}</td><td>${joined(inf("contributes"))}</td></tr>`;
      }).join("");
      const used = depts().filter((d) => P.some((k) => ownerDept("process", k) === d.department_code
        || (R.data.processes[k].answers?.steps || []).some((s) => whoDept(s) === d.department_code)));
      const matrix = P.length && used.length ? P.map((k) => `<tr><td>${link("process", k)}</td>${used.map((d) => {
        const owns = ownerDept("process", k) === d.department_code;
        const n = (R.data.processes[k].answers?.steps || []).filter((s) => (s.name || "").trim() && whoDept(s) === d.department_code).length;
        return `<td class="c">${owns ? `<span class="rq-tag">Owns</span>` : ""}${n ? `<span class="faint">${owns ? " · " : ""}${plural(n, "step")}</span>` : ""}</td>`;
      }).join("")}</tr>`).join("") : `<tr><td class="faint" colspan="${used.length + 1}">Shows once processes have owners or steps with departments.</td></tr>`;
      const deptRows = depts().map((d) => `<tr><td><input class="rq-in" id="rq-dept-${esc(d.department_code)}" data-rq="deptname" data-k="${esc(d.department_code)}" value="${esc(d.department_name)}"></td>
        <td class="mono">${esc(d.department_code)}</td><td class="num">${Object.values(R.data.people).filter((p) => p.department === d.department_code).length}</td>
        <td><button class="btn sm ghost rq-bad" data-rq="deptrm" data-k="${esc(d.department_code)}" title="Remove">×</button></td></tr>`).join("");

      main.innerHTML = `<div class="rq-guide"><b>Every process, dimension and measure needs an owner:</b> the person or department that answers for its
          definition and gets problems fixed at the source. Owners are set on each item; this page shows the gaps and how the work is shared.</div>
        <div class="rq-own">
          <div class="panel"><h3>Not owned yet</h3>${gaps.length ? `<dl class="rq-gaps">${gaps.map(([l, list]) => `<dt>${l} · ${list.length}</dt><dd>${list.join(", ")}</dd>`).join("")}</dl>`
            : `<p class="faint">Everything has an owner.</p>`}</div>
          <div class="panel"><h3>By department</h3><p class="sub">A person's department stands in for theirs. A measure's owner is a role: its department is the department of the people with that role.</p>
            <div class="rq-tablewrap"><table class="rq-table"><thead><tr><th>Department</th><th>Processes owned</th><th>Steps done</th><th>Dimensions owned</th><th>Measures owned</th></tr></thead>
            <tbody>${rows || `<tr><td colspan="5" class="faint">Nothing is owned yet.</td></tr>`}</tbody></table></div></div>
          ${moves ? `<div class="panel"><h3>Measures each department moves</h3><p class="sub">Which measures a department's work owns or contributes to, in each process
            (<span class="mono">seeds/department_metric.csv</span>, set by the engineers). It decides what a department dashboard shows.</p>
            <div class="rq-tablewrap"><table class="rq-table"><thead><tr><th>Department</th><th>Owns</th><th>Contributes to</th></tr></thead><tbody>${moves}</tbody></table></div></div>` : ""}
          <div class="panel"><h3>Processes and the departments in them</h3><p class="sub">Who owns each process, and who does its steps. Many departments in one process means many handoffs.</p>
            <div class="rq-tablewrap"><table class="rq-table"><thead><tr><th>Process</th>${used.map((d) => `<th class="c">${esc(d.department_name)}</th>`).join("")}</tr></thead><tbody>${matrix}</tbody></table></div></div>
          <div class="panel"><h3>Departments</h3><p class="sub">From <span class="mono">seeds/department.csv</span>. A department still used by a person, an owner, a step or another seed can't be removed.</p>
            <table class="rq-table"><thead><tr><th>Name</th><th>Code</th><th class="num">People</th><th></th></tr></thead><tbody>${deptRows}</tbody></table>
            ${addForm("department", "Department name", "Add department")}</div>
        </div>`;
    },
    click(rq, t) {
      if (rq === "deptrm") {
        if (confirm(`Remove the ${deptName(t.dataset.k)} department?`)) act("DELETE", `/api/requirements/department/${t.dataset.k}`, undefined, "Removed");
        return true;
      }
      return undefined;
    },
    field(rq, t, e) {
      if (rq !== "deptname" || e.type !== "change") return rq === "deptname" ? true : undefined;
      const d = depts().find((x) => x.department_code === t.dataset.k);
      if (t.value.trim() && t.value.trim() !== d?.department_name) {
        act("PATCH", `/api/requirements/department/${t.dataset.k}`, { name: t.value.trim() }, "Department renamed");
      }
      return true;
    },
  };
})();
