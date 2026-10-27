/* The Requirements tab: what the business asked for, edited where it lives.

   Everything shown comes from /api/requirements: the project's requirements/
   files, each measure joined with its definition in the semantic files. Every
   edit is a save through the requirements store (core/requirements/store.py):
   one commit, in the name under "Who's editing?". Saves from other windows,
   and edits made in an editor, arrive over /api/requirements/events and the
   screen redraws from the files.

   This file holds the state, saving, the live updates, the drawer for a
   process, dimension or measure, People and Source systems. The screens are
   in req-pages.js and req-sketch.js. Every control carries data-rq="<action>". */
"use strict";

const Req = (() => {
  const R = {
    data: null, screen: "overview", open: null, filter: "all", stale: false, drawerStale: false,
    pending: new Map(), timers: new Map(), chains: new Map(), history: {}, saving: 0, failed: "", other: {},
    pages: {},
  };
  const remember = (k, v) => {
    try {
      if (v === undefined) return localStorage.getItem(k);
      if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v);
    } catch { /* private window */ }
    return null;
  };
  R.editor = remember("studio.editor") || "";
  R.screen = remember("studio.req.screen") || "overview";

  const SCREENS = [["overview", "Overview"], ["processes", "Processes"], ["bus", "Bus matrix"],
    ["measures", "Measures"], ["sketches", "Sketches"], ["ownership", "Ownership"]];
  const FILES = { process: "processes", dimension: "dimensions", measure: "measures", dashboard: "dashboards",
    person: "people", bus: "bus_matrix", sketch: "sketches" };
  const LISTS = new Set(["bus", "sketch"]);
  const DEFINITION = ["label", "description", "owner", "caveats"];
  const NOUN = { process: "process", dimension: "dimension", measure: "measure" };
  const UNOWNED = "TBD";

  /* -------------------------------------------------------------- helpers */
  const Q = (kind) => R.data.questions[kind];
  const interview = (e) => e?.interview || "not_started";
  const STATUS = () => Object.fromEntries(R.data.questions.interview);
  const plural = (n, word, many = word + "s") => `${n} ${n === 1 ? word : many}`;
  const empty = (v) => v == null || v === "" || v === false || (Array.isArray(v) && !v.length)
    || (typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length);
  const has = (v) => (typeof v === "string" ? !!v.trim() : !empty(v));
  const person = (id) => R.data.people[id];
  const depts = () => R.data.departments;
  const deptName = (code) => depts().find((d) => d.department_code === code)?.department_name || code;
  const whoText = (w) => (!w ? "" : w.person ? person(w.person)?.name || w.person : w.department ? deptName(w.department) : w.note || "");
  const whoDept = (w) => w?.department || (w?.person && person(w.person)?.department) || null;
  const entry = (kind, key) => R.data[FILES[kind]]?.[key];
  const label = (kind, key) => (kind === "measure" ? R.data.measures[key]?.definition.label : entry(kind, key)?.name) || key;
  const systems = () => Object.keys(R.data.project.business_systems || {});
  const rel = (iso) => {
    if (!iso) return "";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    if (s < 604800) return `${Math.floor(s / 86400)} d ago`;
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };
  const istat = (e) => `<span class="rq-st ${interview(e)}">${esc(STATUS()[interview(e)])}</span>`;
  const mstat = (st) => (st ? `<span class="gstat ${esc(st)}">${esc(st)}</span>` : "");
  // The person "Who's editing?" names, for the Mine filter.
  const me = () => Object.keys(R.data.people).find((id) => person(id).name.trim().toLowerCase() === R.editor.trim().toLowerCase());

  /** Which questions have an answer: as core/requirements answered(), so the page agrees with the server. */
  function answered(kind, e) {
    const a = e.answers || {}, unknown = e.unknown || {}, def = e.definition || {};
    const home = { name: e.name, label: def.label, description: def.description, owner: def.owner };
    return Object.fromEntries(Q(kind).map((q) => {
      let ok;
      if (q.home) ok = has(home[q.home]) && !(q.home === "owner" && home.owner === UNOWNED);
      else if (q.type === "steps") ok = (a.steps || []).some((s) => has(s.name));
      else ok = has(a[q.key]) || (q.box && a[q.box.key] === true) || (q.other && has(a[q.other.key]));
      return [q.key, ok || (q.key in unknown && q.unknown !== false)];
    }));
  }
  const done = (kind, e) => Object.values(answered(kind, e)).filter(Boolean).length;
  function meter(kind, e) {
    const ans = answered(kind, e), unk = e.unknown || {};
    return `<span class="rq-meter" title="${done(kind, e)} of ${Q(kind).length} answered">${Q(kind).map((q) =>
      `<i class="${q.key in unk ? "unk" : ans[q.key] ? "on" : ""}"></i>`).join("")}</span>`;
  }

  // Where a measure sits: its dashboard slots, and the process it belongs to.
  const placements = (name) => R.data.measures[name]?.placements || [];
  const isProcess = (code) => code in R.data.processes;
  function processOf(name) {
    const p = placements(name).find((x) => isProcess(x.dashboard));
    return p ? p.dashboard : R.data.measures[name]?.process || null;
  }
  const onDashboard = (code) => Object.entries(R.data.measures)
    .filter(([, m]) => m.placements.some((p) => p.dashboard === code))
    .sort((a, b) => slotNo(a[1], code) - slotNo(b[1], code)).map(([n]) => n);
  const slotNo = (m, code) => +(m.placements.find((p) => p.dashboard === code)?.slot || "M99").slice(1);

  /* ----------------------------------------------------------- the server */
  async function call(method, path, body) {
    const headers = { "Content-Type": "application/json" };
    if (R.editor) headers["X-Editor"] = encodeURIComponent(R.editor);
    const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    if (!r.ok) {
      const d = (await r.json().catch(() => ({}))).detail;
      throw new Error(typeof d === "string" ? d : d?.message || r.statusText);
    }
    return r.json();
  }

  function editorOk() {
    if (R.editor) return true;
    const name = (prompt("Who's editing? Each change is saved as a commit in this name.") || "").trim();
    if (!name) { toast("Not saved: say who's editing first."); return false; }
    setEditor(name);
    return true;
  }
  function setEditor(name) {
    R.editor = name.trim();
    remember("studio.editor", R.editor || null);
    const el = $("#rq-editor");
    if (el && el !== document.activeElement) el.value = R.editor;
    if (R.filter === "mine") draw();
  }

  function busy(n, error) {
    R.saving += n;
    if (error) R.failed = error.message;
    else if (n < 0 && !R.saving) R.failed = "";
    const el = $("#rq-saved");
    if (!el) return;
    el.className = "rq-saved" + (R.failed ? " bad" : "");
    el.textContent = R.saving ? "Saving…" : R.failed ? "Not saved" : R.data?.last ? "Saved" : "";
    el.title = R.failed || (R.data?.last ? `Last change: ${R.data.last.message}, by ${R.data.last.author}` : "");
  }

  /* --------------------------------------------- saving: debounced, merged */
  function merge(a, b) {
    const out = { ...a };
    for (const [k, v] of Object.entries(b)) {
      out[k] = (k === "answers" || k === "unknown") && v && typeof v === "object" && out[k] ? { ...out[k], ...v } : v;
    }
    return out;
  }

  /** The change made here at once, as the store will make it, so the page redraws before the save lands. */
  function apply(kind, key, patch) {
    const file = R.data[FILES[kind]];
    if (LISTS.has(kind)) {
      if (patch.length) file[key] = patch; else delete file[key];
      return;
    }
    const e = file[key] ||= kind === "measure" ? { definition: {}, placements: [] } : {};
    let touched = false;
    for (const [k, v] of Object.entries(patch)) {
      if (kind === "measure" && DEFINITION.includes(k)) {
        e.definition[k] = k === "owner" ? (v?.person ? person(v.person)?.role || "" : v || UNOWNED) : v;
        touched = true;
      } else if ((k === "answers" || k === "unknown") && v && typeof v === "object") {
        const sub = e[k] ||= {};
        for (const [sk, sv] of Object.entries(v)) {
          if (sv === null || (k === "answers" && empty(sv))) delete sub[sk]; else sub[sk] = sv;
        }
        touched = true;
      } else if (empty(v) || (k === "interview" && v === "not_started")) delete e[k];
      else {
        e[k] = v;
        if (k === "name") touched = true;
      }
    }
    if (!NOUN[kind]) return;
    if (touched && !("interview" in patch) && interview(e) === "not_started") e.interview = "in_progress";
    if (interview(e) === "complete" && done(kind, e) < Q(kind).length) e.interview = "in_progress";
    e.answered = answered(kind, e);
  }

  function save(kind, key, patch, delay = 600) {
    if (!editorOk()) { draw(); return; }
    const id = `${kind}/${key}`;
    const list = LISTS.has(kind);
    R.pending.set(id, list ? patch : merge(R.pending.get(id) || {}, patch));
    apply(kind, key, patch);
    clearTimeout(R.timers.get(id));
    R.timers.set(id, setTimeout(() => flush(id), delay));
    draw();
  }

  function flush(id) {
    clearTimeout(R.timers.get(id));
    R.timers.delete(id);
    const body = R.pending.get(id);
    if (body === undefined) return R.chains.get(id) || Promise.resolve();
    R.pending.delete(id);
    const [kind, key] = [id.slice(0, id.indexOf("/")), id.slice(id.indexOf("/") + 1)];
    busy(1);
    const c = (R.chains.get(id) || Promise.resolve())
      .then(() => call("PATCH", `/api/requirements/${kind}/${encodeURIComponent(key)}`, body))
      .then(() => { busy(-1); if (R.open && openId() === id) loadHistory(); })
      .catch((e) => { busy(-1, e); toast(`Not saved: ${e.message}`); reload(); });
    R.chains.set(id, c);
    return c;
  }
  const flushAll = () => Promise.all([...R.pending.keys()].map(flush));
  window.addEventListener("beforeunload", () => { flushAll(); });

  /** Anything other than a field edit (add, remove, move, place, undo): saved at once, then redrawn from the files. */
  async function act(method, path, body, ok) {
    if (!editorOk()) return null;
    await flushAll();
    busy(1);
    try {
      const out = await call(method, path, body);
      busy(-1);
      if (ok) toast(ok);
      await reload();
      return out;
    } catch (e) {
      busy(-1, e);
      toast(e.message);
      await reload();
      return null;
    }
  }

  /* ------------------------------------------------- reading, and live */
  async function reload() {
    const data = await api("/api/requirements");
    R.data = data;
    for (const [id, body] of R.pending) {
      const i = id.indexOf("/");
      apply(id.slice(0, i), id.slice(i + 1), body);
    }
    draw();
    busy(0);
  }

  // One stream for the whole page: this tab reloads from it, and other screens (Governance) listen through onChange.
  // A hidden tab lets go of it (a browser allows a host only a few open connections) and catches up when shown.
  const listeners = [];
  const onChange = (fn) => listeners.push(fn);
  let es = null, timer, sections = new Set();
  function changed(list) {
    list.forEach((x) => sections.add(x));
    clearTimeout(timer);
    timer = setTimeout(() => {
      const all = [...sections];
      sections = new Set();
      for (const fn of listeners) { try { fn(all); } catch (e) { console.error(e); } }
      if (R.data) reload().then(() => { if (R.open) loadHistory(); }).catch(() => {});
    }, 120);
  }
  function live() {
    if (es || document.hidden) return;
    es = new EventSource("/api/requirements/events");
    es.onmessage = (msg) => {
      const ev = JSON.parse(msg.data);
      if (ev.project && R.data && ev.project !== R.data.project.slug) { location.reload(); return; }
      changed(ev.sections);
    };
  }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { es?.close(); es = null; return; }
    live();
    changed(["all"]);
  });

  /* ---------------------------------------------------------- drawing */
  const visible = () => $("#view-req")?.classList.contains("active");
  const typing = (root) => {
    const a = document.activeElement;
    return a && root?.contains(a) && (a.tagName === "TEXTAREA" || (a.tagName === "INPUT" && !["checkbox", "radio"].includes(a.type)));
  };

  /** Redraw what shows. A screen or drawer being typed in is left alone, and redrawn when the typing stops. */
  function draw() {
    if (!R.data || !visible()) return;
    drawBar();
    if (typing($("#rq-main")) || R.pages[R.screen]?.busy?.()) R.stale = true;
    else { R.stale = false; drawScreen(); }
    drawDrawer();
  }

  function drawScreen() {
    const main = $("#rq-main");
    if (!R.data.project.has_requirements) {
      main.innerHTML = `<div class="panel empty-state"><b>This project has no requirements yet</b>
        <p>Its <span class="mono">requirements/</span> folder doesn't exist. Projects made with the Studio start with one.</p></div>`;
      return;
    }
    const page = R.pages[R.screen];
    const y = window.scrollY;
    try { page.draw(main); } catch (e) {
      main.innerHTML = `<div class="panel empty-state"><b>Could not draw this screen</b><p>${esc(e.message)}</p></div>`;
      console.error(e);
    }
    if (Math.abs(window.scrollY - y) > 1) window.scrollTo(0, y);
  }

  function drawBar() {
    const bar = $("#rq-bar");
    if (!bar.firstElementChild) {
      bar.innerHTML = `<div class="segmented" id="rq-nav">${SCREENS.map(([k, l]) => `<button data-rq="screen" data-k="${k}">${l}</button>`).join("")}</div>
        <div class="rq-tools">
          <label class="rq-who" title="Each change is saved as a git commit in this name.">Who's editing?
            <input class="rq-in" id="rq-editor" data-rq="editor" list="rq-people" placeholder="Your name" value="${esc(R.editor)}"></label>
          <datalist id="rq-people"></datalist>
          <span class="rq-saved" id="rq-saved"></span>
          <button class="btn sm ghost" data-rq="undo" id="rq-undo">Undo</button>
          <button class="btn sm" data-rq="people">People</button>
          <button class="btn sm" data-rq="systems">Source systems</button>
        </div>`;
    }
    bar.querySelectorAll("#rq-nav button").forEach((b) => b.classList.toggle("active", b.dataset.k === R.screen));
    $("#rq-people").innerHTML = Object.values(R.data.people).map((p) => `<option value="${esc(p.name)}">`).join("");
    const last = R.data.last, undo = $("#rq-undo");
    undo.hidden = !last || last.undoable === false;
    if (last) undo.title = `Undo the last change: ${last.message} (${last.author}, ${rel(last.date)})`;
    busy(0);
  }

  function setScreen(k) {
    if ($("#rq-main").contains(document.activeElement)) document.activeElement.blur();
    R.screen = k;
    remember("studio.req.screen", k);
    draw();
    window.scrollTo(0, 0);
  }

  /* ============================================================ the drawer */
  const openId = () => (R.open ? `${R.open.kind}/${R.open.key}` : "");
  const drawerShown = () => $("#drawer").classList.contains("open") && $("#drawer-body .rq-drawer");

  function openEntry(kind, key, opts = {}) {
    if (R.open && openId() !== `${kind}/${key}`) flush(openId());
    R.open = { kind, key, ...opts };
    R.other = {};
    openDrawer2(`<div class="rq-drawer"></div>`, true);
    drawDrawer(true);
    loadHistory();
    if (opts.focus) requestAnimationFrame(() => $(`#rqs-${opts.focus}`)?.scrollIntoView({ block: "start" }));
    draw();
  }

  function drawDrawer(force) {
    if (!R.open || (!force && !drawerShown())) { if (!drawerShown()) R.open = null; return; }
    const body = $("#drawer-body");
    if (!force && typing(body)) { R.drawerStale = true; drawState(); return; }
    R.drawerStale = false;
    const a = document.activeElement, focus = body.contains(a) ? a.id : null, top = $("#drawer").scrollTop;
    const { kind, key } = R.open;
    let html;
    if (kind === "slot") html = R.pages.measures.slotDrawer(R.open);
    else if (kind === "people") html = peopleHTML();
    else if (kind === "systems") html = systemsHTML();
    else if (!entry(kind, key)) html = `<div class="empty">This ${esc(NOUN[kind] || kind)} is no longer in the files.</div>`;
    else html = entryHTML(kind, key);
    body.innerHTML = `<div class="rq-drawer" data-kind="${esc(kind)}" data-key="${esc(key || "")}">${html}</div>`;
    $("#drawer").scrollTop = top;
    if (focus) document.getElementById(focus)?.focus({ preventScroll: true });
  }

  /* ---------------------------------------------- one process, dimension or measure */
  function entryHTML(kind, key) {
    const e = entry(kind, key), def = e.definition || {}, n = done(kind, e), total = Q(kind).length;
    const list = Object.keys(R.data[FILES[kind]]), at = list.indexOf(key);
    const people = Object.entries(R.data.people);
    const crumb = kind === "measure" ? measureCrumb(key) : `${kind === "process" ? "Business process" : "Dimension"} · <span class="mono nocase">${esc(key)}</span>`;
    const move = kind === "measure" ? "" : `<button class="btn sm ghost" data-rq="move" data-v="${at - 1}" ${at <= 0 ? "disabled" : ""} title="Move earlier">↑</button>
      <button class="btn sm ghost" data-rq="move" data-v="${at + 1}" ${at >= list.length - 1 ? "disabled" : ""} title="Move later">↓</button>`;
    const proc = kind !== "measure" ? "" : (() => {
      const from = placements(key).find((p) => isProcess(p.dashboard));
      if (from) return `<div class="rq-full"><span class="rq-lbl">Business process</span> ${esc(label("process", from.dashboard))}
        <span class="faint">(it's on the ${esc(from.dashboard)} dashboard)</span></div>`;
      return `<div class="rq-full"><label class="rq-lbl" for="rq-process">Business process</label>
        <select id="rq-process" data-rq="f" data-q="process"><option value="">${Object.keys(R.data.processes).length ? "Not linked" : "No processes yet"}</option>
        ${Object.keys(R.data.processes).map((c) => `<option value="${esc(c)}" ${e.process === c ? "selected" : ""}>${esc(label("process", c))}</option>`).join("")}</select>
        <p class="rq-hint">The process that produces this number. It places the measure on the bus matrix.</p></div>`;
    })();
    return `<div class="rq-dtop"><div class="eyebrow">${crumb}</div><span class="rq-dtools">${move}</span></div>
      <h2 class="rq-dh">${esc(label(kind, key))}</h2>
      <div class="rq-dmeta" id="rq-state">${stateHTML(kind, key)}</div>
      ${kind === "measure" ? definitionNote(key) : ""}
      <div class="rq-panel">
        <div><label class="rq-lbl" for="rq-assignee">Assigned to</label>
          <select id="rq-assignee" data-rq="f" data-q="assignee"><option value="">Unassigned</option>
          ${people.map(([id, p]) => `<option value="${esc(id)}" ${e.assignee === id ? "selected" : ""}>${esc(p.name)}${p.role ? ` · ${esc(p.role)}` : ""}</option>`).join("")}</select></div>
        <div class="rq-complete" id="rq-complete">${completeHTML(kind, e, n, total)}</div>
        <div class="rq-full"><label class="rq-check"><input type="checkbox" id="rq-followup" data-rq="f" data-q="followup" ${e.followup ? "checked" : ""}> Flag for follow-up</label>
          <p class="rq-hint">Answering "I don't know" to a question flags it too.</p>
          ${e.followup ? `<input class="rq-in" id="rq-followup-note" data-rq="f" data-q="followup_note" value="${esc(e.followup_note || "")}" placeholder="What needs following up, and with whom?">` : ""}</div>
        ${proc}
      </div>
      ${kind === "measure" ? onDashboardsHTML(key) : ""}
      ${Q(kind).map((q, i) => questionHTML(kind, e, q, i)).join("")}
      ${kind === "measure"
        ? `<div class="rq-sec">Caveats</div><p class="rq-hint">Published with the number on every route. One per line.</p>
           <textarea class="rq-in" id="rq-caveats" data-rq="caveats" rows="2" placeholder="e.g. Excludes drop-shipped orders.">${esc((def.caveats || []).join("\n"))}</textarea>`
        : `<div class="rq-sec">Notes for the project team</div>
           <textarea class="rq-in" id="rq-notes" data-rq="f" data-q="notes" rows="2" placeholder="Anything you're unsure about, or context we should know.">${esc(e.notes || "")}</textarea>`}
      <div class="rq-danger">${kind === "measure" && def.file !== "backlog.yml"
        ? `<span class="faint">It has a formula in <span class="mono">${esc(def.file)}</span>: removing it is an engineering change.</span>`
        : `<button class="btn sm ghost rq-bad" data-rq="remove">Delete ${esc(NOUN[kind])}</button>`}</div>
      <div class="rq-sec">History</div><div id="rq-history">${historyHTML()}</div>`;
  }

  function measureCrumb(key) {
    const via = R.open.via;
    if (!via) return `Measure · <span class="mono nocase">${esc(key)}</span>`;
    const d = R.data.dashboards[via.dashboard];
    return `${esc(via.dashboard)}${d?.name ? ` · ${esc(d.name)}` : ""} · Measure ${esc(via.slot.slice(1))}`;
  }

  function definitionNote(key) {
    const d = R.data.measures[key].definition;
    return `<div class="rq-defnote">${mstat(d.status)} <span>${d.file === "backlog.yml"
      ? `In the backlog: no formula yet.${d.reason ? ` ${esc(d.reason)}` : ""}`
      : `Built: its formula is in <span class="mono">${esc(d.file)}</span>.`} Its name, definition, owner and caveats are the same
      lines the Governance page shows.</span></div>`;
  }

  function stateHTML(kind, key) {
    const e = entry(kind, key), h = R.history[`${kind}/${key}`]?.[0];
    return `${istat(e)}${e.followup ? `<span class="rq-flag">Follow-up</span>` : ""}${meter(kind, e)}
      <span class="faint">${h ? `Last edited ${esc(rel(h.date))} by ${esc(h.author)}` : ""}</span>`;
  }

  function completeHTML(kind, e, n, total) {
    if (interview(e) === "complete") return `<button class="btn sm" data-rq="complete">Reopen</button><span class="rq-hint">Complete</span>`;
    return `<button class="btn sm primary" data-rq="complete" ${n < total ? "disabled" : ""}>Mark complete</button>
      <span class="rq-hint">${n < total ? `${total - n} left` : "Every question answered"}</span>`;
  }

  function qmark(e, q, i, ans) {
    const unk = q.key in (e.unknown || {});
    return { cls: unk ? "unk" : ans[q.key] ? "done" : "", text: unk ? "?" : ans[q.key] ? "✓" : String(i + 1).padStart(2, "0") };
  }

  /** While a field is being typed in, update only the parts that follow from it. */
  function drawState() {
    const { kind, key } = R.open || {};
    const e = entry(kind, key);
    if (!e || !NOUN[kind]) return;
    $("#rq-state").innerHTML = stateHTML(kind, key);
    $("#rq-complete").innerHTML = completeHTML(kind, e, done(kind, e), Q(kind).length);
    const ans = answered(kind, e);
    Q(kind).forEach((q, i) => {
      const el = $(`#rqn-${q.key}`), m = qmark(e, q, i, ans);
      if (el) { el.className = `rq-qn ${m.cls}`; el.textContent = m.text; }
    });
  }

  function onDashboardsHTML(key) {
    const ps = placements(key);
    if (!ps.length) return `<div class="rq-share"><b>Not on a dashboard.</b> Put it in an empty slot on the Measures grid.</div>`;
    if (ps.length === 1 && !R.open.via) return "";
    return `<div class="rq-share"><b>On ${plural(ps.length, "dashboard")}.</b> One definition: a change here shows everywhere it's used.
      <ul>${ps.map((p) => `<li><span>${esc(p.dashboard)} · Measure ${esc(p.slot.slice(1))}</span>
        <button class="linkbtn" data-rq="unplace" data-k="${esc(p.dashboard)}" data-v="${esc(p.slot)}">Take it off ${esc(p.dashboard)}</button></li>`).join("")}</ul></div>`;
  }

  /* ------------------------------------------------------------ questions */
  function questionHTML(kind, e, q, i) {
    const m = qmark(e, q, i, answered(kind, e));
    const unk = e.unknown || {}, isUnk = q.key in unk;
    const dontKnow = q.unknown === false ? "" : `<div class="rq-dk"><label class="rq-check"><input type="checkbox" id="rq-unk-${q.key}" data-rq="unk" data-q="${q.key}" ${isUnk ? "checked" : ""}> I don't know</label>
      ${isUnk ? `<input class="rq-in" id="rq-unkwho-${q.key}" data-rq="unkwho" data-q="${q.key}" value="${esc(unk[q.key] || "")}" placeholder="Who might know? (optional)">` : ""}</div>`;
    return `<section class="rq-q" id="rqs-${q.key}"><div class="rq-qn ${m.cls}" id="rqn-${q.key}">${m.text}</div>
      <div><h3>${esc(q.title)}</h3>${q.why ? `<p class="rq-why">${esc(q.why)}</p>` : ""}
        <div class="rq-qb">${answerHTML(kind, e, q)}${dontKnow}</div></div></section>`;
  }

  const textHTML = (id, rq, k, value, q, area) => area
    ? `<textarea class="rq-in" id="${id}" data-rq="${rq}" data-q="${k}" rows="2" placeholder="${esc(q.placeholder || "")}">${esc(value || "")}</textarea>`
    : `<input class="rq-in" id="${id}" data-rq="${rq}" data-q="${k}" value="${esc(value || "")}" placeholder="${esc(q.placeholder || "")}">`;

  function answerHTML(kind, e, q) {
    const a = e.answers || {}, def = e.definition || {};
    if (q.home === "name") return textHTML("rq-name", "f", "name", e.name, q);
    if (q.home === "label") return textHTML("rq-label", "def", "label", def.label, q);
    if (q.home === "description") return textHTML("rq-description", "def", "description", def.description, q, true);
    if (q.home === "owner") return ownerHTML(e);
    const box = q.box ? `<label class="rq-check"><input type="checkbox" id="rq-box-${q.key}" data-rq="box" data-q="${q.box.key}" ${a[q.box.key] ? "checked" : ""}> ${esc(q.box.label)}</label>` : "";
    const other = !q.other ? "" : q.other.type === "dimensions" ? dimsHTML(a[q.other.key] || [])
      : textHTML(`rq-a-${q.other.key}`, "a", q.other.key, a[q.other.key], q.other);
    const note = q.note ? textHTML(`rq-a-${q.note.key}`, "a", q.note.key, a[q.note.key], q.note) : "";
    switch (q.type) {
      case "text": return textHTML(`rq-a-${q.key}`, "a", q.key, a[q.key], q) + box;
      case "textarea":
        return q.other?.type === "dimensions" ? other + textHTML(`rq-a-${q.key}`, "a", q.key, a[q.key], q, true) + box
          : textHTML(`rq-a-${q.key}`, "a", q.key, a[q.key], q, true) + box;
      case "choice":
        return `<div class="rq-radios">${q.choices.map(([v, t, sub]) => `<label class="rq-radio"><input type="radio" name="rq-${q.key}" id="rq-${q.key}-${v}" data-rq="a" data-q="${q.key}" value="${esc(v)}" ${a[q.key] === v ? "checked" : ""}>
          <span><b>${esc(t)}</b><small>${esc(sub)}</small></span></label>`).join("")}</div>${note}`;
      case "systems": return systemsChips(q.key, a[q.key] || []) + other;
      case "steps": return stepsHTML(a.steps || []);
      case "who": return whoHTML(q.key, a[q.key]);
    }
    return "";
  }

  function systemsChips(key, chosen) {
    const all = [...systems(), ...chosen.filter((s) => !systems().includes(s))];
    if (!all.length) return `<div class="faint">No source systems listed yet: add them under Source systems.</div>`;
    return `<div class="rq-chips">${all.map((s, i) => `<label class="rq-chip"><input type="checkbox" id="rq-sys-${key}-${i}" data-rq="sys" data-q="${key}" value="${esc(s)}" ${chosen.includes(s) ? "checked" : ""}><span>${esc(s)}</span></label>`).join("")}</div>`;
  }

  function dimsHTML(chosen) {
    const dims = Object.entries(R.data.dimensions);
    if (!dims.length) return "";
    return `<div class="rq-chips">${dims.map(([code, d]) => `<label class="rq-chip"><input type="checkbox" id="rq-dim-${code}" data-rq="dims" value="${esc(code)}" ${chosen.includes(code) ? "checked" : ""}><span>${esc(d.name || code)}</span></label>`).join("")}</div>`;
  }

  function whoOptions(value, emptyLabel, people = true, departments = true) {
    return `<option value="">${esc(emptyLabel)}</option>
      ${departments && depts().length ? `<optgroup label="Departments">${depts().map((d) => `<option value="d:${esc(d.department_code)}" ${value === "d:" + d.department_code ? "selected" : ""}>${esc(d.department_name)}</option>`).join("")}</optgroup>` : ""}
      ${people && Object.keys(R.data.people).length ? `<optgroup label="People">${Object.entries(R.data.people).map(([id, p]) => `<option value="p:${esc(id)}" ${value === "p:" + id ? "selected" : ""}>${esc(p.name)}${p.role ? ` · ${esc(p.role)}` : ""}</option>`).join("")}</optgroup>` : ""}`;
  }

  function whoHTML(key, w) {
    const value = w?.person ? "p:" + w.person : w?.department ? "d:" + w.department : w?.note || R.other[key] ? "other" : "";
    return `<select id="rq-who-${key}" data-rq="who" data-q="${key}">${whoOptions(value, "Choose a department or person")}
      <option value="other" ${value === "other" ? "selected" : ""}>Someone not listed…</option></select>
      ${value === "other" ? `<input class="rq-in" id="rq-whonote-${key}" data-rq="whonote" data-q="${key}" value="${esc(w?.note || "")}" placeholder="Name and role, e.g. Jordan Lee, Director of Logistics">` : ""}`;
  }

  // A metric's owner is a role (what dbt, Power BI and the catalogue show). Picking a person writes theirs.
  function ownerHTML(e) {
    const owner = e.definition.owner || "", set = owner && owner !== UNOWNED;
    const match = Object.entries(R.data.people).find(([, p]) => set && p.role === owner);
    const value = R.other.owner ? "other" : match ? "p:" + match[0] : set ? "other" : "";
    return `<select id="rq-owner" data-rq="owner">${whoOptions(value, "Not decided (TBD)", true, false)}
      <option value="other" ${value === "other" ? "selected" : ""}>A role not listed…</option></select>
      ${value === "other" ? `<input class="rq-in" id="rq-owner-role" data-rq="def" data-q="owner" value="${esc(set ? owner : "")}" placeholder="The owning role, e.g. Logistics Lead">` : ""}
      <p class="rq-hint">${set ? `Owner: <b>${esc(owner)}</b>${match ? ` (${esc(match[1].name)})` : ""}. ` : ""}The definition records the role, so it outlasts the person.</p>`;
  }

  function stepsHTML(steps) {
    const sys = systems();
    return `<div class="rq-steps">${steps.map((s, i) => {
      const who = s.department ? "d:" + s.department : s.person ? "p:" + s.person : "";
      const opts = [...sys, ...(s.system && !sys.includes(s.system) ? [s.system] : [])];
      return `<div class="rq-steprow"><span class="rq-stepn">${i + 1}</span>
        <input class="rq-in" id="rq-step-${i}" data-rq="stepname" data-i="${i}" value="${esc(s.name || "")}" placeholder="e.g. Take the order">
        <select id="rq-stepwho-${i}" data-rq="stepwho" data-i="${i}">${whoOptions(who, "Who does it?")}</select>
        <select id="rq-stepsys-${i}" data-rq="stepsys" data-i="${i}"><option value="">System</option>${opts.map((x) => `<option ${s.system === x ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
        <span class="rq-steptools"><button class="btn sm ghost" data-rq="stepmove" data-i="${i}" data-v="-1" ${i ? "" : "disabled"} title="Move up">↑</button><button class="btn sm ghost" data-rq="stepmove" data-i="${i}" data-v="1" ${i < steps.length - 1 ? "" : "disabled"} title="Move down">↓</button><button class="btn sm ghost rq-bad" data-rq="stepdel" data-i="${i}" title="Remove step">×</button></span></div>`;
    }).join("")}<button class="btn sm" data-rq="stepadd">+ Add a step</button></div>`;
  }

  /* -------------------------------------------------------------- history */
  async function loadHistory() {
    const { kind, key } = R.open || {};
    if (!["process", "dimension", "measure"].includes(kind)) return;
    try {
      const out = await api(`/api/requirements/history/${kind}/${encodeURIComponent(key)}`);
      R.history[`${kind}/${key}`] = out.history;
      if (R.open?.key !== key) return;
      const el = $("#rq-history");
      if (el) el.innerHTML = historyHTML();
      if ($("#rq-state")) $("#rq-state").innerHTML = stateHTML(kind, key);
    } catch { /* the server may be restarting */ }
  }

  function historyHTML() {
    const h = R.history[openId()];
    if (!h) return `<div class="faint">Loading…</div>`;
    if (!h.length) return `<div class="faint">No changes saved here yet. Changes made in an editor show in the file's git log.</div>`;
    return `<ul class="rq-log">${h.map((x) => `<li><span>${esc(x.message)}<span class="faint"> · ${esc(x.author)}</span></span>
      <span class="faint" title="${esc(x.date)} · ${esc(x.commit.slice(0, 8))}">${esc(rel(x.date))}${x.commit === R.data.last?.commit
        ? ` <button class="linkbtn" data-rq="undo">Undo</button>` : ""}</span></li>`).join("")}</ul>`;
  }

  /* ---------------------------------------------------------------- people */
  function peopleHTML() {
    const used = (id) => {
      let n = 0, c = 0;
      for (const f of ["processes", "dimensions", "measures"]) for (const e of Object.values(R.data[f])) {
        if (e.assignee === id) { n++; if (e.interview === "complete") c++; }
      }
      return [n, c];
    };
    const deptSel = (id, value) => `<select data-rq="persondept" data-k="${esc(id)}"><option value="">No department</option>
      ${depts().map((d) => `<option value="${esc(d.department_code)}" ${value === d.department_code ? "selected" : ""}>${esc(d.department_name)}</option>`).join("")}</select>`;
    const rows = Object.entries(R.data.people).map(([id, p]) => {
      const [n, c] = used(id);
      return `<tr><td><input class="rq-in" id="rq-pname-${id}" data-rq="personf" data-k="${esc(id)}" data-q="name" value="${esc(p.name)}"></td>
        <td><input class="rq-in" id="rq-prole-${id}" data-rq="personf" data-k="${esc(id)}" data-q="role" value="${esc(p.role || "")}" placeholder="Role"></td>
        <td>${deptSel(id, p.department)}</td>
        <td><input class="rq-in" id="rq-pemail-${id}" data-rq="personf" data-k="${esc(id)}" data-q="email" value="${esc(p.email || "")}" placeholder="Email"></td>
        <td class="num">${n ? `${c}/${n}` : `<span class="faint">–</span>`}</td>
        <td><button class="btn sm ghost rq-bad" data-rq="personrm" data-k="${esc(id)}" title="Remove">×</button></td></tr>`;
    }).join("");
    return `<div class="eyebrow">Requirements</div><h2>People</h2>
      <p>Everyone who answers or signs off on anything here. <span class="mono">requirements/people.yml</span> is the only file with
        names in it; everything else refers to a person by id. A measure's owner is the role, so give owners one.</p>
      <div class="rq-tablewrap"><table class="rq-table"><thead><tr><th>Name</th><th>Role</th><th>Department</th><th>Email</th><th class="num">Done</th><th></th></tr></thead>
        <tbody>${rows || `<tr><td colspan="6" class="faint">No one yet. Add the people who will fill this in.</td></tr>`}</tbody></table></div>
      <form class="rq-addform" data-rq="personadd"><input class="rq-in" name="name" placeholder="Full name" required>
        <input class="rq-in" name="role" placeholder="Role"><button class="btn sm primary">Add person</button></form>`;
  }

  /* ------------------------------------------------------- source systems */
  function systemsHTML() {
    const map = R.data.project.business_systems || {};
    return `<div class="eyebrow">Requirements</div><h2>Source systems</h2>
      <p>The systems the business names in its answers: offered on every measure, process, step and dimension. One per line.
        Each maps to a system in the architecture, which the engineers set in <span class="mono">project.yml</span>.</p>
      <textarea class="rq-in mono" id="rq-systems" rows="8">${esc(Object.keys(map).join("\n"))}</textarea>
      <div class="rq-row"><button class="btn sm primary" data-rq="systemssave">Save</button>
        <span class="faint">A system still named in an answer can't be removed.</span></div>
      <h4>In the architecture</h4>
      <table class="rq-table"><tbody>${Object.entries(map).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v ? `<span class="mono">${esc(v)}</span>` : `<span class="faint">Not connected yet</span>`}</td></tr>`).join("")}</tbody></table>`;
  }

  /* ================================================================ events */
  const root = () => $("#view-req");
  const inDrawer = (t) => $("#drawer").contains(t) && t.closest(".rq-drawer");
  const ours = (t) => t && (root().contains(t) || inDrawer(t));
  const current = () => R.open && entry(R.open.kind, R.open.key);
  const steps = () => (current()?.answers?.steps || []).map((s) => ({ ...s }));
  const saveSteps = (list, delay = 0) => save(R.open.kind, R.open.key, { answers: { steps: list } }, delay);

  async function onClick(e) {
    const t = e.target.closest("[data-rq]");
    if (!ours(t) || ["INPUT", "SELECT", "TEXTAREA", "FORM", "LABEL"].includes(t.tagName)) return;
    const { rq, k, v, i } = t.dataset;
    const o = R.open;
    switch (rq) {
      case "screen": return setScreen(k);
      case "people": R.open = null; openDrawer2(`<div class="rq-drawer"></div>`, true); R.open = { kind: "people" }; return drawDrawer(true);
      case "systems": R.open = null; openDrawer2(`<div class="rq-drawer"></div>`, true); R.open = { kind: "systems" }; return drawDrawer(true);
      case "systemssave": {
        const list = $("#rq-systems").value.split("\n").map((x) => x.trim()).filter(Boolean);
        return act("PUT", "/api/requirements/settings", { business_systems: list }, "Source systems saved");
      }
      case "undo": {
        const last = R.data.last;
        if (!last || !confirm(`Undo "${last.message}" (${last.author}, ${rel(last.date)})?`)) return;
        return act("POST", "/api/requirements/undo", { commit: last.commit }, "Undone");
      }
      case "complete": {
        await flush(openId());
        const reopen = interview(current()) === "complete";
        save(o.kind, o.key, { interview: reopen ? "in_progress" : "complete" }, 0);
        return toast(reopen ? "Reopened" : "Marked complete");
      }
      case "move": return act("POST", `/api/requirements/${o.kind}/${encodeURIComponent(o.key)}/move`, { position: +v });
      case "remove": {
        if (!confirm(`Delete ${label(o.kind, o.key)}? Its answers go with it; git keeps them, and Undo puts them back.`)) return;
        const out = await act("DELETE", `/api/requirements/${o.kind}/${encodeURIComponent(o.key)}`, undefined, `Deleted ${label(o.kind, o.key)}`);
        if (out) closeDrawer();
        return;
      }
      case "unplace":
        return act("PUT", `/api/requirements/slots/${k}/${v}`, { metric: null }, `Taken off ${k}`);
      case "personrm": {
        if (!confirm(`Remove ${person(k)?.name}?`)) return;
        return act("DELETE", `/api/requirements/person/${k}`, undefined, "Removed");
      }
      case "stepadd": {
        const list = steps();
        list.push({ name: "" });
        saveSteps(list);
        return requestAnimationFrame(() => $(`#rq-step-${list.length - 1}`)?.focus());
      }
      case "stepmove": {
        const list = steps(), a = +i, b = a + +v;
        [list[a], list[b]] = [list[b], list[a]];
        return saveSteps(list);
      }
      case "stepdel": {
        const list = steps();
        list.splice(+i, 1);
        return saveSteps(list);
      }
    }
    for (const page of Object.values(R.pages)) if (page.click && (await page.click(rq, t, e)) !== undefined) return;
  }

  function onField(e) {
    const t = e.target;
    if (!t.dataset?.rq || !ours(t)) return;
    const { rq, q, k, i } = t.dataset;
    for (const page of Object.values(R.pages)) if (page.field && page.field(rq, t, e) !== undefined) return;
    // Text saves as it's typed; a tick, a choice or a pick when it changes.
    const o = R.open, text = e.type === "input";
    const isText = t.tagName === "TEXTAREA" || (t.tagName === "INPUT" && !["checkbox", "radio"].includes(t.type));
    if (text !== isText) return;
    switch (rq) {
      case "editor": return setEditor(t.value);
      case "f": {
        const v = t.type === "checkbox" ? t.checked : t.value || null;
        return save(o.kind, o.key, { [q]: v }, isText ? 600 : 0);
      }
      case "a": return save(o.kind, o.key, { answers: { [q]: t.value } }, isText ? 600 : 100);
      case "box": return save(o.kind, o.key, { answers: { [q]: t.checked } }, 100);
      case "sys": {
        const list = [...document.querySelectorAll(`#drawer [data-rq="sys"][data-q="${q}"]`)].filter((x) => x.checked).map((x) => x.value);
        return save(o.kind, o.key, { answers: { [q]: list } }, 250);
      }
      case "dims": {
        const list = [...document.querySelectorAll(`#drawer [data-rq="dims"]`)].filter((x) => x.checked).map((x) => x.value);
        return save(o.kind, o.key, { answers: { dimensions: list } }, 250);
      }
      case "unk": {
        const who = $(`#rq-unkwho-${q}`)?.value || "";
        save(o.kind, o.key, { unknown: { [q]: t.checked ? who : null }, ...(t.checked ? { followup: true } : {}) }, 100);
        if (t.checked) requestAnimationFrame(() => $(`#rq-unkwho-${q}`)?.focus());
        return;
      }
      case "unkwho": return save(o.kind, o.key, { unknown: { [q]: t.value } });
      case "def": return save(o.kind, o.key, { [q]: t.value });
      case "caveats": return save(o.kind, o.key, { caveats: t.value.split("\n").map((x) => x.trim()).filter(Boolean) });
      case "who": {
        if (t.value === "other") {
          R.other[q] = true;
          drawDrawer();
          return requestAnimationFrame(() => $(`#rq-whonote-${q}`)?.focus());
        }
        R.other[q] = false;
        const w = t.value.startsWith("p:") ? { person: t.value.slice(2) } : t.value.startsWith("d:") ? { department: t.value.slice(2) } : null;
        return save(o.kind, o.key, { answers: { [q]: w } }, 0);
      }
      case "whonote": return save(o.kind, o.key, { answers: { [q]: t.value.trim() ? { note: t.value } : null } });
      case "owner": {
        if (t.value === "other") {
          R.other.owner = true;
          drawDrawer();
          return requestAnimationFrame(() => $("#rq-owner-role")?.focus());
        }
        R.other.owner = false;
        return save(o.kind, o.key, { owner: t.value ? { person: t.value.slice(2) } : "" }, 0);
      }
      case "stepname": case "stepwho": case "stepsys": {
        const list = steps(), s = list[+i];
        if (rq === "stepname") s.name = t.value;
        if (rq === "stepsys") { if (t.value) s.system = t.value; else delete s.system; }
        if (rq === "stepwho") {
          delete s.department; delete s.person;
          if (t.value.startsWith("d:")) s.department = t.value.slice(2);
          if (t.value.startsWith("p:")) s.person = t.value.slice(2);
        }
        return saveSteps(list, isText ? 600 : 0);
      }
      case "personf": return save("person", k, { [q]: t.value }, isText ? 800 : 0);
      case "persondept": return save("person", k, { department: t.value || null }, 0);
    }
  }

  document.addEventListener("click", (e) => { onClick(e); });
  document.addEventListener("input", onField);
  document.addEventListener("change", onField);
  document.addEventListener("submit", async (e) => {
    const f = e.target;
    if (!f.dataset?.rq || !ours(f)) return;
    e.preventDefault();
    // A form sent is typing done: let the page redraw what it adds.
    if (f.contains(document.activeElement)) document.activeElement.blur();
    const data = Object.fromEntries(new FormData(f));
    if (f.dataset.rq === "personadd") {
      const out = await act("POST", "/api/requirements/person", { value: { name: data.name.trim(), role: data.role.trim() } }, `Added ${data.name}`);
      if (out && !R.editor) setEditor(data.name);
      return;
    }
    for (const page of Object.values(R.pages)) if (page.submit && (await page.submit(f.dataset.rq, data, f)) !== undefined) return;
  });
  // Typing done: flush the save, and redraw what was held back while typing.
  document.addEventListener("focusout", (e) => {
    if (!ours(e.target)) return;
    if (e.target.dataset?.rq && R.open && inDrawer(e.target)) flush(openId());
    setTimeout(() => {
      if (R.stale && !typing($("#rq-main"))) draw();
      else if (R.drawerStale && !typing($("#drawer-body"))) drawDrawer();
    }, 0);
  });

  /* ---------------------------------------------------------------- entry */
  async function show() {
    if (!R.data) {
      $("#rq-main").innerHTML = `<div class="faint">Reading the requirements…</div>`;
      try { R.data = await api("/api/requirements"); }
      catch (e) { $("#rq-main").innerHTML = `<div class="panel empty-state"><b>Not available</b><p>${esc(e.message)}</p></div>`; return; }
    }
    draw();
  }
  live();

  return {
    R, show, save, flush, act, reload, draw, setScreen, openEntry, drawDrawer, entry, label, answered, done, meter, istat, mstat,
    interview, plural, person, depts, deptName, whoText, whoDept, placements, processOf, onDashboard, isProcess,
    systems, rel, me, UNOWNED, editorOk, setEditor, call, onChange,
  };
})();
window.Req = Req;
