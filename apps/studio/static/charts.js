/* Small SVG charts for the preview screens. No library. */
"use strict";

const Charts = (() => {
  const W = 640;
  const monthLabel = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short" });

  function sparkline(values, width = 120, height = 30) {
    const pts = values.map((v, i) => [i, v]).filter(([, v]) => typeof v === "number");
    if (pts.length < 2) return "";
    const ys = pts.map(([, v]) => v), lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
    const x = (i) => (i / (values.length - 1)) * (width - 4) + 2;
    const y = (v) => height - 3 - ((v - lo) / span) * (height - 6);
    const d = pts.map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
    const [li, lv] = pts[pts.length - 1];
    return `<svg class="spark" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">
      <path d="${d}" fill="none" stroke="currentColor" stroke-width="1.6"/>
      <circle cx="${x(li)}" cy="${y(lv)}" r="2.4" fill="currentColor"/></svg>`;
  }

  function line(points, fmt, height = 240) {
    const vals = points.map((p) => p.value).filter((v) => typeof v === "number");
    if (!vals.length) return "";
    const pad = { l: 64, r: 16, t: 14, b: 28 };
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (lo === hi) { lo -= Math.abs(lo) * 0.1 || 1; hi += Math.abs(hi) * 0.1 || 1; }
    const span = hi - lo; lo -= span * 0.12; hi += span * 0.12;
    if (fmt !== "percent" && fmt !== "days" && lo < 0 && Math.min(...vals) >= 0) lo = 0;
    const x = (i) => pad.l + (i / Math.max(points.length - 1, 1)) * (W - pad.l - pad.r);
    const y = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * (height - pad.t - pad.b);
    let grid = "";
    for (let k = 0; k <= 3; k++) {
      const v = lo + ((hi - lo) * k) / 3, yy = y(v);
      grid += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${yy}" y2="${yy}" class="grid"/>
        <text x="${pad.l - 8}" y="${yy + 4}" text-anchor="end" class="axis">${fmtNum(v, fmt)}</text>`;
    }
    const xl = points.map((p, i) => `<text x="${x(i)}" y="${height - 8}" text-anchor="middle" class="axis">${monthLabel(p.month)}${p.partial ? "*" : ""}</text>`).join("");
    // A month still in progress is drawn dashed, apart from the complete months.
    const last = points[points.length - 1];
    const partial = last && last.partial && typeof last.value === "number" ? [x(points.length - 1), y(last.value), last] : null;
    const full = partial ? points.slice(0, -1) : points;
    const segs = [];
    let cur = [];
    full.forEach((p, i) => { if (typeof p.value === "number") cur.push([x(i), y(p.value), p]); else if (cur.length) { segs.push(cur); cur = []; } });
    if (cur.length) segs.push(cur);
    const paths = segs.map((sg) => {
      const d = sg.map(([xx, yy], k) => `${k ? "L" : "M"}${xx.toFixed(1)} ${yy.toFixed(1)}`).join(" ");
      const area = `${d} L${sg[sg.length - 1][0].toFixed(1)} ${height - pad.b} L${sg[0][0].toFixed(1)} ${height - pad.b} Z`;
      return `<path d="${area}" class="area"/><path d="${d}" class="ln"/>`;
    }).join("");
    const dots = segs.flat().map(([xx, yy, p]) => `<circle cx="${xx}" cy="${yy}" r="3.2" class="dot"><title>${monthLabel(p.month)}: ${fmtNum(p.value, fmt)}</title></circle>`).join("");
    let tail = "";
    const prev = segs.length ? segs[segs.length - 1][segs[segs.length - 1].length - 1] : null;
    if (partial) {
      tail = (prev ? `<path d="M${prev[0]} ${prev[1]} L${partial[0]} ${partial[1]}" class="ln partial"/>` : "") +
        `<circle cx="${partial[0]}" cy="${partial[1]}" r="3.2" class="dot partial"><title>${monthLabel(last.month)} to date: ${fmtNum(last.value, fmt)}</title></circle>`;
    }
    const note = partial ? `<text x="${W - pad.r}" y="${pad.t - 2}" text-anchor="end" class="axis">* ${monthLabel(last.month)} to date</text>` : "";
    return `<svg class="chart" viewBox="0 0 ${W} ${height}" preserveAspectRatio="xMidYMid meet">${grid}${xl}${paths}${dots}${tail}${note}</svg>`;
  }

  function bars(rows, fmt) {
    const vals = rows.map((r) => r.value).filter((v) => typeof v === "number");
    if (!vals.length) return "";
    const hi = Math.max(...vals.map(Math.abs)) || 1;
    return `<div class="bars">${rows.map((r) => `<div class="barrow"><span class="bl" title="${esc(r.label)}">${esc(r.label ?? "(none)")}</span>
      <span class="bt"><i style="width:${(100 * Math.abs(r.value ?? 0)) / hi}%"></i></span><span class="bv">${fmtNum(r.value, fmt)}</span></div>`).join("")}</div>`;
  }

  /* ------------------------------------------------- dashboard visuals */
  const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"];
  const tip = (rows) => esc(JSON.stringify(rows));
  const monthTick = (iso) => {
    const d = new Date(iso + "T00:00:00");
    return d.getMonth() === 0 ? `Jan '${String(d.getFullYear()).slice(2)}` : d.toLocaleDateString("en-US", { month: "short" });
  };
  const monthLong = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" });

  function niceTicks(lo, hi, n = 4) {
    const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw || 1));
    const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((k) => k >= raw) || mag * 10;
    const start = Math.floor(lo / step) * step, out = [];
    for (let v = start; v <= hi + step * 0.001; v += step) out.push(+v.toFixed(10));
    if (out[out.length - 1] < hi) out.push(out[out.length - 1] + step);
    return out;
  }

  /* A monthly trend: this period, the same months a year earlier, or one line per member.
     series: [{label, values, color?, dash?, muted?}]; months: ISO firsts; partial: ISO of the month in progress. */
  function trend({ months, series, fmt, partial, band, width = 760, height = 260, additive = false }) {
    const pi0 = months.indexOf(partial);
    const all = series.flatMap((s) => s.values.filter((_, i) => !(additive && i === pi0))).filter((v) => typeof v === "number");
    if (!all.length) return "";
    const W2 = width, pad = { l: 58, r: series.length > 2 ? 132 : 70, t: 16, b: 30 };
    let lo = Math.min(...all), hi = Math.max(...all);
    if (fmt === "usd" || fmt === "int") lo = Math.min(0, lo);
    if (lo === hi) { lo -= Math.abs(lo) * 0.1 || 1; hi += Math.abs(hi) * 0.1 || 1; }
    const ticks = niceTicks(lo, hi);
    lo = ticks[0]; hi = ticks[ticks.length - 1];
    const step = (W2 - pad.l - pad.r) / Math.max(months.length - 1, 1);
    const x = (i) => pad.l + i * step;
    const y = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * (height - pad.t - pad.b);
    let out = "";
    if (band) {
      const a = months.indexOf(band[0]), b = months.indexOf(band[1]);
      if (a >= 0 || b >= 0) {
        const x0 = a >= 0 ? x(a) - step / 2 : pad.l, x1 = b >= 0 ? x(b) + step / 2 : W2 - pad.r;
        out += `<rect x="${Math.max(x0, pad.l - 6)}" y="${pad.t - 6}" width="${Math.min(x1, W2 - pad.r + 6) - Math.max(x0, pad.l - 6)}" height="${height - pad.t - pad.b + 6}" class="band" rx="6"/>`;
      }
    }
    out += ticks.map((v) => `<line x1="${pad.l}" x2="${W2 - pad.r}" y1="${y(v)}" y2="${y(v)}" class="grid"/>
      <text x="${pad.l - 10}" y="${y(v) + 4}" text-anchor="end" class="axis">${esc(fmtAxis(v, fmt))}</text>`).join("");
    out += months.map((m, i) => `<text x="${x(i)}" y="${height - 9}" text-anchor="middle" class="axis ${m === partial ? "dim" : ""}">${monthTick(m)}</text>`).join("");
    const pi = months.indexOf(partial);
    const labels = [];
    series.forEach((s, si) => {
      const color = s.color || "var(--accent)";
      const pts = s.values.map((v, i) => (typeof v === "number" ? [x(i), y(v), i] : null));
      const segs = [];
      let cur = [];
      pts.forEach((p) => { if (p && p[2] !== pi) cur.push(p); else { if (cur.length) segs.push(cur); cur = []; } });
      if (cur.length) segs.push(cur);
      const path = (sg) => sg.map(([xx, yy], k) => `${k ? "L" : "M"}${xx.toFixed(1)} ${yy.toFixed(1)}`).join(" ");
      if (s.area) for (const sg of segs) out += `<path d="${path(sg)} L${sg[sg.length - 1][0].toFixed(1)} ${y(lo)} L${sg[0][0].toFixed(1)} ${y(lo)} Z" class="area"/>`;
      for (const sg of segs) out += `<path d="${path(sg)}" class="ln ${s.dash ? "dash" : ""}" style="stroke:${color}"/>`;
      // The month in progress: a dashed tail and a hollow marker.
      if (pi >= 0 && pts[pi]) {
        const before = pts[pi - 1];
        if (before && !additive) out += `<path d="M${before[0]} ${before[1]} L${pts[pi][0]} ${pts[pi][1]}" class="ln dash faded" style="stroke:${color}"/>`;
        if (!s.dash && !additive) out += `<circle cx="${pts[pi][0]}" cy="${pts[pi][1]}" r="4" class="pt hollow" style="stroke:${color}"/>`;
      }
      const lastFull = [...pts].reverse().find((p) => p && p[2] !== pi);
      if (lastFull && !s.dash) {
        out += `<circle cx="${lastFull[0]}" cy="${lastFull[1]}" r="4.5" class="pt" style="fill:${color}"/>`;
        labels.push({ y: lastFull[1], x: lastFull[0], text: series.length > 2 ? `${s.label}` : fmtNum(s.values[lastFull[2]], fmt), color, sub: series.length > 2 ? fmtNum(s.values[lastFull[2]], fmt) : "" });
      }
    });
    // Direct labels at the right edge, nudged apart so they never collide.
    labels.sort((a, b) => a.y - b.y);
    for (let i = 1; i < labels.length; i++) if (labels[i].y - labels[i - 1].y < 26) labels[i].y = labels[i - 1].y + 26;
    const lx = W2 - pad.r + 12;
    out += labels.map((l) => `<text x="${lx}" y="${l.y + 4}" class="dlabel">${esc(l.text.length > 18 ? l.text.slice(0, 17) + "…" : l.text)}</text>` +
      (l.sub ? `<text x="${lx}" y="${l.y + 17}" class="axis">${esc(l.sub)}</text>` : "")).join("");
    // The hover layer: one column per month, the crosshair snaps to it, the readout lists every series.
    out += `<line class="xhair" x1="0" x2="0" y1="${pad.t}" y2="${height - pad.b}" />`;
    out += months.map((m, i) => {
      const rows = series.map((s) => [s.label, fmtNum(s.values[i], fmt), s.color || "var(--accent)", s.dash ? 1 : 0]);
      return `<rect class="hit" x="${x(i) - step / 2}" y="${pad.t}" width="${step}" height="${height - pad.t - pad.b}" data-x="${x(i)}"
        data-tip="${tip({ title: monthLong(m) + (m === partial ? " (to date)" : ""), rows })}"/>`;
    }).join("");
    return `<svg class="chart trend" viewBox="0 0 ${W2} ${height}" width="${W2}" height="${height}">${out}</svg>`;
  }

  /* Horizontal bars, one per member, with last period's value as a tick and the total as a reference line. */
  function hbars({ rows, fmt, better, reference, refLabel, selected, cmpLabel }) {
    const vals = rows.flatMap((r) => [r.value, r.prev]).concat(reference).filter((v) => typeof v === "number");
    if (!vals.length) return "";
    const hi = Math.max(...vals.map(Math.abs), 0) * 1.08 || 1;
    const pct = (v) => (100 * Math.abs(v ?? 0)) / hi;
    const ref = typeof reference === "number" ? `<span class="hb-ref" style="left:${pct(reference)}%"><em>${esc(refLabel)} ${esc(fmtNum(reference, fmt))}</em></span>` : "";
    return `<div class="hbars">${rows.map((r) => {
      const d = change(r.value, r.prev, fmt, better);
      const on = selected === undefined || selected === r.label;
      return `<button class="hb ${on ? "" : "off"} ${selected === r.label ? "sel" : ""}" data-xfilter="${esc(JSON.stringify(r.label))}"
        data-tip="${tip({ title: r.label ?? "(blank)", rows: [["This period", fmtNum(r.value, fmt)], [cmpLabel, fmtNum(r.prev, fmt)], ...(r.weightLabel ? [[r.weightLabel, fmtNum(r.weight, "int")]] : [])] })}">
        <span class="hb-l">${esc(r.label ?? "(blank)")}</span>
        <span class="hb-t"><i style="width:${pct(r.value)}%"></i>${typeof r.prev === "number" ? `<b style="left:${pct(r.prev)}%"></b>` : ""}${ref}</span>
        <span class="hb-v">${fmtNum(r.value, fmt)}</span><span class="hb-d">${d ? `<span class="chg ${d.tone}">${d.arrow} ${esc(d.text)}</span>` : ""}</span></button>`;
    }).join("")}</div>`;
  }

  /* A grid of members by column (months, or a second dimension). Rates diverge from the all-members value
     of the same column, blue better and red worse; sums shade one hue by size. cols: [{label, title, dim}]. */
  function heatmap({ cols, rows, overall, fmt, better, kind, allLabel }) {
    const isRate = kind === "ratio" || kind === "fixed";
    const vals = rows.flatMap((r) => r.values).filter((v) => typeof v === "number");
    if (!vals.length) return "";
    const ref = (i) => (Array.isArray(overall) ? overall[i] : overall);
    const dev = rows.flatMap((r) => r.values.map((v, i) => (typeof v === "number" && typeof ref(i) === "number" ? v - ref(i) : null))).filter((v) => v !== null);
    const maxDev = Math.max(...dev.map(Math.abs), 1e-9), maxVal = Math.max(...vals.map(Math.abs), 1e-9);
    const cell = (v, i) => {
      if (typeof v !== "number") return `<td class="hm-c empty">–</td>`;
      let bg = "var(--surface-2)", ink = "var(--ink)";
      if (isRate && typeof ref(i) === "number") {
        let t = (v - ref(i)) / maxDev;
        if (better === "down") t = -t;
        const a = Math.min(Math.abs(t), 1) * 0.85;
        bg = t >= 0 ? `rgba(42,120,214,${a.toFixed(3)})` : `rgba(227,73,72,${a.toFixed(3)})`;
        ink = a > 0.5 ? "#fff" : "var(--ink)";
      } else if (!isRate) {
        const a = 0.08 + (Math.abs(v) / maxVal) * 0.8;
        bg = `rgba(42,120,214,${a.toFixed(3)})`; ink = a > 0.5 ? "#fff" : "var(--ink)";
      }
      const rowsTip = [["Value", fmtNum(v, fmt)], ...(isRate && typeof ref(i) === "number" ? [[allLabel, fmtNum(ref(i), fmt)]] : [])];
      return `<td class="hm-c" style="background:${bg};color:${ink}" data-tip="${tip({ title: cols[i].title, rows: rowsTip })}">${esc(fmtCompact(v, fmt))}</td>`;
    };
    const allRow = isRate && Array.isArray(overall)
      ? `<tr class="hm-all"><th>${esc(allLabel)}</th>${overall.map((v) => `<td class="hm-c">${esc(fmtCompact(v, fmt))}</td>`).join("")}</tr>` : "";
    return `<div class="hm-wrap"><table class="hm"><thead><tr><th></th>${cols.map((c) => `<th class="${c.dim ? "dim" : ""}" title="${esc(c.title)}">${esc(c.label)}</th>`).join("")}</tr></thead>
      <tbody>${allRow}${rows.map((r) => `<tr><th title="${esc(r.label ?? "(blank)")}">${esc(r.label ?? "(blank)")}</th>${r.values.map(cell).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function spark2(values, { width = 132, height = 34, color = "currentColor" } = {}) {
    const pts = values.map((v, i) => [i, v]).filter(([, v]) => typeof v === "number");
    if (pts.length < 3) return `<svg class="spark" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}"></svg>`;
    const ys = pts.map(([, v]) => v), lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
    const x = (i) => (i / (values.length - 1)) * (width - 6) + 3;
    const y = (v) => height - 4 - ((v - lo) / span) * (height - 8);
    const d = pts.map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
    const [li, lv] = pts[pts.length - 1];
    const area = `${d} L${x(li).toFixed(1)} ${height} L${x(pts[0][0]).toFixed(1)} ${height} Z`;
    return `<svg class="spark" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" style="color:${color}">
      <path d="${area}" fill="currentColor" opacity=".08"/><path d="${d}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
      <circle cx="${x(li)}" cy="${y(lv)}" r="2.6" fill="currentColor"/></svg>`;
  }

  /* How a value moved: points for rates, days for days, percent change for amounts and counts. */
  function change(cur, prev, fmt, better) {
    if (typeof cur !== "number" || typeof prev !== "number") return null;
    const d = cur - prev;
    let text;
    if (fmt === "percent") text = `${Math.abs(d * 100).toFixed(1)} pts`;
    else if (fmt === "days") text = `${Math.abs(d).toFixed(1)} days`;
    else {
      if (!prev) return null;
      const rel = Math.abs(d / Math.abs(prev));
      text = rel >= 3 ? `${(cur / prev).toFixed(1)}×` : `${(rel * 100).toFixed(1)}%`;
    }
    const flat = fmt === "percent" ? Math.abs(d) < 0.0005 : fmt === "days" ? Math.abs(d) < 0.05 : Math.abs(d / prev) < 0.0005;
    if (flat) return { text: "no change", arrow: "→", tone: "flat" };
    const tone = !better ? "flat" : (d > 0) === (better === "up") ? "good" : "bad";
    return { text, arrow: d > 0 ? "▲" : "▼", tone };
  }

  function fmtAxis(v, fmt) {
    if (fmt === "percent") return `${+(v * 100).toFixed(1)}%`;
    if (fmt === "days") return `${+v.toFixed(1)}`;
    return fmtCompact(v, fmt);
  }

  function fmtCompact(v, fmt) {
    if (typeof v !== "number") return "–";
    if (fmt === "percent") return (v * 100).toFixed(1) + "%";
    if (fmt === "days") return v.toFixed(1);
    const a = Math.abs(v), p = fmt === "usd" ? "$" : "";
    if (a >= 1e6) return p + (v / 1e6).toFixed(1) + "M";
    if (a >= 1e3) return p + (v / 1e3).toFixed(a >= 1e4 ? 0 : 1) + "K";
    return p + v.toFixed(fmt === "usd" && a < 100 ? 2 : 0);
  }

  /* One floating readout for every chart. Labels are data: they go in with textContent. */
  const tipEl = document.createElement("div");
  tipEl.className = "ctip";
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(tipEl));
  function showTip(el, ev) {
    let data;
    try { data = JSON.parse(el.dataset.tip); } catch { return; }
    tipEl.replaceChildren();
    const h = document.createElement("div"); h.className = "ctip-h"; h.textContent = data.title; tipEl.appendChild(h);
    for (const [label, value, color, dash] of data.rows) {
      const r = document.createElement("div"); r.className = "ctip-r";
      if (color) { const k = document.createElement("i"); k.style.borderTopColor = color; if (dash) k.className = "dash"; r.appendChild(k); }
      const v = document.createElement("b"); v.textContent = value;
      const l = document.createElement("span"); l.textContent = label;
      r.append(v, l); tipEl.appendChild(r);
    }
    tipEl.classList.add("show");
    const pad = 14, w = tipEl.offsetWidth, h2 = tipEl.offsetHeight;
    let left = ev.clientX + pad, top = ev.clientY + pad;
    if (left + w > window.innerWidth - 8) left = ev.clientX - w - pad;
    if (top + h2 > window.innerHeight - 8) top = ev.clientY - h2 - pad;
    tipEl.style.left = left + "px"; tipEl.style.top = top + "px";
    const svg = el.ownerSVGElement, xh = svg && svg.querySelector(".xhair");
    if (xh && el.dataset.x) { xh.setAttribute("x1", el.dataset.x); xh.setAttribute("x2", el.dataset.x); xh.classList.add("on"); }
  }
  document.addEventListener("pointermove", (ev) => {
    const el = ev.target.closest && ev.target.closest("[data-tip]");
    if (el) return showTip(el, ev);
    tipEl.classList.remove("show");
    document.querySelectorAll(".xhair.on").forEach((x) => x.classList.remove("on"));
  });

  return { sparkline, line, bars, trend, hbars, heatmap, spark2, change, fmtCompact, monthLong, monthTick, SERIES };
})();
