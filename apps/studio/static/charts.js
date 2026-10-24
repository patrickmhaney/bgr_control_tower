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

  return { sparkline, line, bars };
})();
