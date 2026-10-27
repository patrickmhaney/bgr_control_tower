/* Requirements: Sketches. Tiles on a 12-column board, one board per dashboard
   (requirements/sketches.yml). Each tile shows one of its dashboard's measures,
   optionally by a dimension, drawn as a sketch: shapes, never numbers, so a
   review stays on layout and content. A board is saved whole, as one list. */
"use strict";

(() => {
  const { R, save, label, plural, onDashboard } = Req;
  const COLS = 12, ROW_H = 56, GAP = 10;
  const KINDS = () => R.data.questions.tiles.map(([kind, name, w, h]) => ({ kind, name, w, h }));
  const KIND = (k) => KINDS().find((x) => x.kind === k) || { name: k };
  // What the "by" dimension means on each kind of tile; kinds without one don't ask.
  const BY = { line: "Split into lines by (optional)", bar: "Compare by", table: "One row per", filter: "Filter by" };
  const CHARTS = ["kpi", "line", "bar", "table"];
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const dname = (d) => R.data.dimensions[d]?.name || d;

  const page = {
    dash: null, tile: null, dragging: false,
    busy() { return this.dragging; },
    tiles() { return R.data.sketches[this.dash] || []; },
  };
  R.pages.sketches = page;
  const target = (m) => !!(R.data.measures[m]?.answers?.target || "").trim();

  function defaultTitle(t) {
    const m = t.measure ? label("measure", t.measure) : "", d = t.dimension ? dname(t.dimension) : "";
    switch (t.kind) {
      case "kpi": return m || "Headline number";
      case "line": return m ? `${m} over time` : "Trend";
      case "bar": return m ? m + (d ? ` by ${d}` : "") : "Comparison";
      case "table": return m ? m + (d ? ` by ${d}` : "") : "Table";
      case "filter": return d || "Filter";
      default: return "Note";
    }
  }

  /* ------------------------------------------------------------ sketches */
  // A small seeded generator, so a tile keeps its shape from one draw to the next.
  function rng(seed) {
    let a = 0;
    for (const ch of seed) a = (Math.imul(a, 31) + ch.charCodeAt(0)) | 0;
    return () => {
      a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function walk(r, n, lo = 12, hi = 50) {
    let y = lo + (hi - lo) * (0.35 + 0.3 * r());
    return Array.from({ length: n }, (_, i) => {
      y = clamp(y + (r() - 0.48) * 12, lo, hi);
      return `${((i * 100) / (n - 1)).toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
  }
  const chart = (inner) => `<svg class="rq-sk" viewBox="0 0 100 60" preserveAspectRatio="none" aria-hidden="true">${inner}</svg>`;
  const axes = () => [15, 30, 45].map((y) => `<line class="rq-skgrid" x1="0" x2="100" y1="${y}" y2="${y}"/>`).join("")
    + `<line class="rq-skaxis" x1="0" x2="100" y1="59.5" y2="59.5"/>`;
  const ph = (cls, w) => `<span class="rq-ph ${cls}"${w ? ` style="width:${w}%"` : ""}></span>`;

  function sketch(t, i) {
    const r = rng(`${page.dash}:${i}:${t.kind}:${t.measure || ""}`);
    if (CHARTS.includes(t.kind) && !t.measure) return `<div class="rq-skempty">Choose a measure</div>`;
    switch (t.kind) {
      case "kpi": return `<div class="rq-skkpi">${ph("big")}<span class="rq-skcmp">${ph("sm")} ${target(t.measure) ? "vs target" : "vs prior period"}</span>
        ${t.h >= 2 ? chart(`<polyline class="rq-skline" points="${walk(r, 10, 8, 52)}"/>`) : ""}</div>`;
      case "line": {
        const n = t.dimension ? 3 : 1;
        return `<div class="rq-skchart">${chart(axes() + (target(t.measure) ? `<line class="rq-sktarget" x1="0" x2="100" y1="18" y2="18"/>` : "")
          + Array.from({ length: n }, (_, k) => `<polyline class="rq-skline s${k}" points="${walk(r, 14)}"/>`).join(""))}
          ${t.dimension ? `<div class="rq-sklegend">${[0, 1, 2].map((k) => `<span class="s${k}"><i></i>${ph("xs")}</span>`).join("")}</div>` : ""}</div>`;
      }
      case "bar": {
        const n = clamp(t.w + 1, 4, 9), bw = 100 / n;
        const hs = Array.from({ length: n }, () => 12 + r() * 44).sort((a, b) => b - a);
        return `<div class="rq-skchart">${chart(axes() + hs.map((v, k) => `<rect class="rq-skbar" x="${k * bw + bw * 0.18}" width="${bw * 0.64}" y="${60 - v}" height="${v}"/>`).join(""))}
          <div class="rq-skticks">${hs.map(() => ph("xs")).join("")}</div></div>`;
      }
      case "table": {
        const rows = Math.max(1, t.h * 2 - 2);
        const head = [t.dimension ? dname(t.dimension) : "Item", label("measure", t.measure), target(t.measure) ? "vs target" : "vs prior"];
        return `<div class="rq-sktable"><div class="rq-sktr th">${head.map((x) => `<span>${esc(x)}</span>`).join("")}</div>
          ${Array.from({ length: rows }, () => `<div class="rq-sktr">${ph("sm", 40 + r() * 50)}${ph("sm", 30 + r() * 40)}${ph("sm", 20 + r() * 30)}</div>`).join("")}</div>`;
      }
      case "filter": return `<div class="rq-skfilter"><span>${t.dimension ? "All" : "Choose a dimension"}<i>▾</i></span></div>`;
      default: return `<div class="rq-sknote">${esc(t.note || "Add a note in the panel.")}</div>`;
    }
  }

  /* --------------------------------------------------------------- saving */
  function put(list, delay = 0) {
    save("sketch", page.dash, list.map((t) => Object.fromEntries(Object.entries(t).filter(([, v]) => v !== "" && v != null))), delay);
  }
  function update(i, patch, delay = 0) {
    const list = page.tiles().map((t) => ({ ...t }));
    Object.assign(list[i], patch);
    put(list, delay);
  }
  function spot(w, h) {
    const used = new Set();
    for (const t of page.tiles()) for (let x = t.x; x < t.x + t.w; x++) for (let y = t.y; y < t.y + t.h; y++) used.add(`${x}:${y}`);
    for (let y = 0; ; y++) for (let x = 0; x <= COLS - w; x++) {
      let free = true;
      for (let dx = 0; dx < w && free; dx++) for (let dy = 0; dy < h && free; dy++) if (used.has(`${x + dx}:${y + dy}`)) free = false;
      if (free) return { x, y };
    }
  }
  function addTile(kind, measure) {
    const k = KIND(kind), on = onDashboard(page.dash);
    // With only one measure on the dashboard, a chart can only mean that one.
    const m = measure || (CHARTS.includes(kind) && on.length === 1 ? on[0] : undefined);
    const list = [...page.tiles(), { kind, ...spot(k.w, k.h), w: k.w, h: k.h, ...(m ? { measure: m } : {}) }];
    page.tile = list.length - 1;
    put(list);
  }
  function removeTile(i) {
    const list = page.tiles().filter((_, k) => k !== i);
    page.tile = null;
    put(list);
    toast("Tile removed");
  }

  /* ---------------------------------------------------------------- board */
  const rows = (extra = 0) => Math.max(6, ...page.tiles().map((t) => t.y + t.h + 1), extra);
  const place = (g) => `grid-column:${g.x + 1} / span ${g.w};grid-row:${g.y + 1} / span ${g.h}`;

  function boardHTML() {
    const n = rows();
    let cells = "";
    for (let y = 0; y < n; y++) for (let x = 0; x < COLS; x++) cells += `<div class="rq-bcell" style="grid-column:${x + 1};grid-row:${y + 1}"></div>`;
    const tiles = page.tiles().map((t, i) => {
      const m = t.measure && R.data.measures[t.measure];
      const time = (m?.answers?.time || "").split(/[.;]/)[0];
      const sub = t.kind === "line" && time ? time : t.kind === "kpi" && m && target(t.measure) ? "Against target" : "";
      return `<div class="rq-tile k-${t.kind} ${page.tile === i ? "selected" : ""}" tabindex="0" data-i="${i}" style="${place(t)}"
        aria-label="${esc(KIND(t.kind).name)}: ${esc(t.title || defaultTitle(t))}">
        <div class="rq-tileh"><span class="rq-tilet">${esc(t.title || defaultTitle(t))}</span>${sub ? `<span class="rq-tiles">${esc(sub)}</span>` : ""}</div>
        <div class="rq-tileb">${sketch(t, i)}</div><span class="rq-resize" title="Drag to resize"></span></div>`;
    }).join("");
    return { n, html: cells + tiles + (page.tiles().length ? "" : `<div class="rq-bempty">Empty board. Add a tile from the bar above.</div>`) };
  }

  page.drawBoard = function (focused = document.activeElement?.closest?.(".rq-tile")?.dataset.i) {
    const board = $("#rq-board");
    if (!board || this.dragging) return;
    const { n, html } = boardHTML();
    board.style.setProperty("--rows", n);
    board.innerHTML = html;
    if (focused != null && +focused === this.tile) board.querySelector(`.rq-tile[data-i="${focused}"]`)?.focus({ preventScroll: true });
  };

  page.draw = function (main) {
    const focused = document.activeElement?.closest?.(".rq-tile")?.dataset.i;
    const codes = Object.keys(R.data.dashboards);
    if (!codes.includes(this.dash)) this.dash = codes.find((c) => (R.data.sketches[c] || []).length) || codes[0] || null;
    if (this.tile != null && !this.tiles()[this.tile]) this.tile = null;
    const nav = codes.map((c) => {
      const d = R.data.dashboards[c], n = (R.data.sketches[c] || []).length;
      return `<button class="${c === this.dash ? "active" : ""}" data-rq="sketchdash" data-k="${esc(c)}"><b class="mono">${esc(c)}</b>
        <span>${esc(d.name || "")}</span><small class="faint">${n ? plural(n, "tile") : "Not sketched"}</small></button>`;
    }).join("");
    const d = R.data.dashboards[this.dash];
    main.innerHTML = `<div class="rq-guide"><b>Sketch each dashboard before it's built:</b> what goes where, and what each tile shows. Sketches use shapes
        instead of numbers, so the conversation stays on layout and content. Drag a tile to move it and its corner to resize it; with a tile
        selected, arrow keys move it and Shift + arrows resize it.</div>
      <div class="rq-proto"><nav class="rq-protonav"><div class="rq-protonavh">Dashboards</div>${nav || `<p class="faint">Add dashboards on the Measures screen.</p>`}</nav>
        <section class="rq-protomain">${d ? `<div class="rq-protohead"><h3>${esc(this.dash)}${d.name ? ` · ${esc(d.name)}` : ""}</h3></div>
          <div class="rq-protoadd">${KINDS().map((k) => `<button class="btn sm" data-rq="addtile" data-k="${k.kind}">+ ${esc(k.name)}</button>`).join("")}</div>
          <div class="rq-boardwrap"><div class="rq-board" id="rq-board"></div></div>` : `<h3>No dashboards yet</h3>`}</section>
        <aside class="panel rq-protoside" id="rq-side">${d ? sideHTML() : ""}</aside></div>`;
    this.drawBoard(focused);
  };

  /* ----------------------------------------------------------- side panel */
  const field = (lbl, input) => `<label class="rq-sfield"><span class="rq-lbl">${esc(lbl)}</span>${input}</label>`;
  function filterNote(dim) {
    if (!dim) return "";
    const v = Req.dashboardView(page.dash);
    if (!v.procs.length || v.all.includes(dim)) return "";
    const part = v.some.find((x) => x.d === dim);
    return part ? `Only filters ${part.measures.map((n) => label("measure", n)).join(", ")}.` : "None of this dashboard's processes are ticked for it on the bus matrix.";
  }

  function sideHTML() {
    const t = page.tiles()[page.tile], on = onDashboard(page.dash);
    if (t) {
      const linked = new Set(R.data.measures[t.measure]?.answers?.dimensions || []);
      const D = Object.keys(R.data.dimensions), own = D.filter((d) => linked.has(d)), rest = D.filter((d) => !linked.has(d));
      const opt = (d) => `<option value="${esc(d)}" ${t.dimension === d ? "selected" : ""}>${esc(dname(d))}</option>`;
      const note = t.kind === "filter" ? filterNote(t.dimension) : "";
      return `<div class="rq-sideh"><h3>Tile</h3><button class="btn sm ghost" data-rq="tiledone">Done</button></div>
        <div class="rq-kinds">${KINDS().map((k) => `<button class="btn sm ${k.kind === t.kind ? "on" : ""}" data-rq="tilekind" data-k="${k.kind}">${esc(k.name)}</button>`).join("")}</div>
        ${CHARTS.includes(t.kind) ? field("Shows", `<select data-rq="tilemeasure"><option value="">${on.length ? "Choose a measure" : "No measures on this dashboard yet"}</option>
          ${on.map((n) => `<option value="${esc(n)}" ${t.measure === n ? "selected" : ""}>${esc(label("measure", n))}</option>`).join("")}</select>`) : ""}
        ${BY[t.kind] ? field(BY[t.kind], `<select data-rq="tiledim"><option value="">${D.length ? "None" : "No dimensions yet"}</option>
          ${own.length ? `<optgroup label="This measure's breakdowns">${own.map(opt).join("")}</optgroup>` : ""}
          ${rest.length ? `<optgroup label="${own.length ? "Other dimensions" : "Dimensions"}">${rest.map(opt).join("")}</optgroup>` : ""}</select>`) : ""}
        ${note ? `<p class="rq-hint">${esc(note)}</p>` : ""}
        ${field("Title", `<input class="rq-in" id="rq-tiletitle" data-rq="tiletitle" value="${esc(t.title || "")}" placeholder="${esc(defaultTitle(t))}">`)}
        ${field(t.kind === "text" ? "Note" : "Notes for whoever builds it", `<textarea class="rq-in" id="rq-tilenote" data-rq="tilenote" rows="3"
          placeholder="${t.kind === "text" ? "What should this note say?" : "Anything to know: drill-throughs, thresholds, colours."}">${esc(t.note || "")}</textarea>`)}
        <button class="btn sm ghost rq-bad" data-rq="tilerm">Remove tile</button>`;
    }
    const d = R.data.dashboards[page.dash], placed = new Set(page.tiles().map((x) => x.measure));
    const v = Req.dashboardView(page.dash), names = (ds) => ds.map(dname).join(", ");
    return `<div class="rq-sideh"><h3>About this dashboard</h3></div>
      ${R.data.questions.dashboard.map((q) => field(q.title, `<textarea class="rq-in" id="rq-use-${q.key}" data-rq="use" data-q="${q.key}" rows="2" placeholder="${esc(q.placeholder || "")}">${esc(d[q.key] || "")}</textarea>`)).join("")}
      <div class="rq-sideh"><h3>Measures</h3></div>
      ${on.length ? `<ul class="rq-sidem">${on.map((n) => `<li><button class="linkbtn" data-rq="open" data-k="measure" data-v="${esc(n)}">${esc(label("measure", n))}</button>
        ${placed.has(n) ? `<span class="faint">In the sketch</span>` : `<button class="btn sm" data-rq="addtile" data-k="kpi" data-v="${esc(n)}">Add</button>`}</li>`).join("")}</ul>`
        : `<p class="faint">No measures on this dashboard yet. Add them on the Measures screen.</p>`}
      ${on.length ? `<div class="rq-sideh"><h3>Filters</h3></div><p class="rq-hint">${!v.procs.length ? "Link its measures to business processes to see which filters work across it."
        : v.all.length ? `Work on every tile: ${esc(names(v.all))}.` : "No dimension works on every tile yet."}
        ${v.some.length ? ` Only some tiles: ${esc(names(v.some.map((x) => x.d)))}.` : ""}
        <button class="linkbtn" data-rq="busof" data-k="${esc(page.dash)}">See it on the bus matrix</button></p>` : ""}`;
  }

  /* --------------------------------------------------------------- events */
  page.click = function (rq, t) {
    const { k, v } = t.dataset;
    switch (rq) {
      case "sketchdash": this.dash = k; this.tile = null; Req.draw(); return true;
      case "sketchof": this.dash = k; this.tile = null; Req.setScreen("sketches"); return true;
      case "busof": R.pages.bus.view = k; Req.setScreen("bus"); return true;
      case "addtile": addTile(k, v); return true;
      case "tilekind": update(this.tile, { kind: k }); return true;
      case "tiledone": this.tile = null; Req.draw(); return true;
      case "tilerm": removeTile(this.tile); return true;
    }
    return undefined;
  };
  page.field = function (rq, t, e) {
    const change = e.type === "change";
    switch (rq) {
      case "tilemeasure": if (change) update(this.tile, { measure: t.value || null }); return true;
      case "tiledim": if (change) update(this.tile, { dimension: t.value || null }); return true;
      case "tiletitle": if (!change) { update(this.tile, { title: t.value }, 600); this.drawBoard(); } return true;
      case "tilenote": if (!change) { update(this.tile, { note: t.value }, 600); this.drawBoard(); } return true;
      case "use": if (!change) save("dashboard", this.dash, { [t.dataset.q]: t.value }); return true;
    }
    return undefined;
  };

  function startDrag(e, el, mode) {
    const i = +el.dataset.i, t = page.tiles()[i], board = $("#rq-board"), rect = board.getBoundingClientRect();
    const colW = (rect.width - GAP * (COLS - 1)) / COLS + GAP, rowH = ROW_H + GAP;
    const sx = e.clientX, sy = e.clientY, orig = { x: t.x, y: t.y, w: t.w, h: t.h };
    let cur = orig, moved = false;
    e.preventDefault();
    el.focus({ preventScroll: true });
    el.setPointerCapture(e.pointerId);
    page.dragging = true;
    el.classList.add("dragging");
    const onMove = (ev) => {
      if (Math.abs(ev.clientX - sx) + Math.abs(ev.clientY - sy) > 4) moved = true;
      const dx = Math.round((ev.clientX - sx) / colW), dy = Math.round((ev.clientY - sy) / rowH);
      cur = mode === "move" ? { ...orig, x: clamp(orig.x + dx, 0, COLS - orig.w), y: Math.max(0, orig.y + dy) }
        : { ...orig, w: clamp(orig.w + dx, 1, COLS - orig.x), h: clamp(orig.h + dy, 1, 12) };
      el.style.cssText = place(cur);
      board.style.setProperty("--rows", rows(cur.y + cur.h + 1));
    };
    const onUp = () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
      page.dragging = false;
      page.tile = i;
      const changed = Object.fromEntries(Object.entries(cur).filter(([k, v]) => v !== orig[k]));
      if (moved && Object.keys(changed).length) update(i, changed);
      else Req.draw();
    };
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
  }

  document.addEventListener("pointerdown", (e) => {
    const board = e.target.closest?.("#rq-board");
    if (!board || e.button !== 0) return;
    const tile = e.target.closest(".rq-tile");
    if (!tile) {
      if (page.tile != null) { page.tile = null; Req.draw(); }
      return;
    }
    startDrag(e, tile, e.target.closest(".rq-resize") ? "resize" : "move");
  });

  // Arrows move the selected tile; Shift + arrows resize it.
  document.addEventListener("keydown", (e) => {
    const el = e.target.closest?.("#rq-board .rq-tile");
    if (!el) return;
    const i = +el.dataset.i, t = page.tiles()[i];
    const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (step) {
      e.preventDefault();
      e.stopPropagation();
      page.tile = i;
      const [dx, dy] = step;
      update(i, e.shiftKey ? { w: clamp(t.w + dx, 1, COLS - t.x), h: clamp(t.h + dy, 1, 12) }
        : { x: clamp(t.x + dx, 0, COLS - t.w), y: Math.max(0, t.y + dy) }, 400);
    } else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); removeTile(i); }
    else if (e.key === "Escape") { e.stopPropagation(); page.tile = null; el.blur(); Req.draw(); }
  }, true);
  document.addEventListener("focusin", (e) => {
    const el = e.target.closest?.("#rq-board .rq-tile");
    if (el && page.tile !== +el.dataset.i) {
      page.tile = +el.dataset.i;
      $("#rq-side").innerHTML = sideHTML();
      document.querySelectorAll("#rq-board .rq-tile").forEach((x) => x.classList.toggle("selected", x === el));
    }
  });
})();
