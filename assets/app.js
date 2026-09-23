/* Condo price monitor — reads the JSON the scraper commits, draws the dashboard.
   No build step and no dependencies: the charts are hand-rolled SVG. */

const SOURCE_LABELS = { ddproperty: "DDproperty", livinginsider: "Livinginsider", hipflat: "Hipflat" };
// Fixed slot per source, assigned by identity and never by rank, so a source
// dropping out never repaints the others.
const SOURCE_VARS = { ddproperty: "--series-1", livinginsider: "--series-2", hipflat: "--series-3" };

const state = { index: null, watchId: null, days: 90, history: null, snapshot: null, sort: "price", dir: 1 };

const $ = (sel) => document.querySelector(sel);
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
const colorFor = (src) => cssVar(SOURCE_VARS[src] || "--text-secondary");
const labelFor = (src) => SOURCE_LABELS[src] || src;

const baht = (n) => (n || n === 0 ? "฿" + Math.round(n).toLocaleString("en-US") : "—");
const bahtShort = (n) => {
  if (!n && n !== 0) return "—";
  if (n >= 1e6) return "฿" + (n / 1e6).toFixed(n >= 1e7 ? 1 : 2) + "M";
  if (n >= 1e3) return "฿" + Math.round(n / 1e3) + "k";
  return "฿" + n;
};
const shortDate = (iso) =>
  new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

async function getJSON(path, fallback) {
  try {
    const res = await fetch(path, { cache: "no-store" });
    if (!res.ok) return fallback;
    return await res.json();
  } catch {
    return fallback;
  }
}

/* ---------------------------------------------------------------- charts */

const PAD = { top: 16, right: 92, bottom: 28, left: 58 };

function niceTicks(min, max, count) {
  if (min === max) {
    const pad = Math.abs(min || 1) * 0.1;
    min -= pad;
    max += pad;
  }
  const raw = (max - min) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || mag * 10;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return ticks;
}

function tooltipEl() {
  let tip = document.getElementById("tooltip");
  if (!tip) {
    tip = document.createElement("div");
    tip.id = "tooltip";
    tip.className = "tooltip";
    document.body.appendChild(tip);
  }
  return tip;
}

/**
 * Draw a multi-series time line chart into an <svg>.
 * series: [{ key, label, color, points: [{date, value}] }]
 */
function drawLineChart(svgEl, series, opts) {
  const format = opts.format;
  const formatShort = opts.formatShort;
  const height = opts.height || 260;
  const width = Math.max(svgEl.clientWidth || svgEl.parentElement.clientWidth || 640, 460);

  svgEl.setAttribute("viewBox", "0 0 " + width + " " + height);
  svgEl.innerHTML = "";

  const ns = "http://www.w3.org/2000/svg";
  const add = (tag, attrs, text) => {
    const el = document.createElementNS(ns, tag);
    Object.keys(attrs).forEach((k) => el.setAttribute(k, attrs[k]));
    if (text != null) el.textContent = text;
    svgEl.appendChild(el);
    return el;
  };

  const live = series.filter((s) => s.points.length);
  if (!live.length) {
    add("text", { x: width / 2, y: height / 2, "text-anchor": "middle" },
      "No history yet — a trend line appears after the second run.");
    return;
  }

  const dates = Array.from(new Set(live.flatMap((s) => s.points.map((p) => p.date)))).sort();
  const values = live.flatMap((s) => s.points.map((p) => p.value));
  const ticks = niceTicks(Math.min.apply(null, values), Math.max.apply(null, values), 4);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];

  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const x = (d) => PAD.left + (dates.length === 1 ? plotW / 2 : (dates.indexOf(d) / (dates.length - 1)) * plotW);
  const y = (v) => PAD.top + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;

  // Recessive grid, then the baseline.
  ticks.forEach((t) => {
    add("line", { class: "grid-line", x1: PAD.left, x2: PAD.left + plotW, y1: y(t), y2: y(t) });
    add("text", { x: PAD.left - 8, y: y(t) + 4, "text-anchor": "end" }, formatShort(t));
  });
  add("line", { class: "axis-line", x1: PAD.left, x2: PAD.left + plotW, y1: y(yMin), y2: y(yMin) });

  const step = Math.max(1, Math.ceil(dates.length / 6));
  dates.forEach((d, i) => {
    if (i % step === 0 || i === dates.length - 1) {
      add("text", { x: x(d), y: height - 8, "text-anchor": "middle" }, shortDate(d));
    }
  });

  live.forEach((s) => {
    const pts = s.points.slice().sort((a, b) => a.date.localeCompare(b.date));
    const d = pts.map((p, i) => (i ? "L" : "M") + x(p.date).toFixed(1) + "," + y(p.value).toFixed(1)).join(" ");
    add("path", { class: "series-line", d: d, stroke: s.color });
    if (pts.length === 1) {
      add("circle", { class: "dot", cx: x(pts[0].date), cy: y(pts[0].value), r: 4, fill: s.color });
    }
    // Direct label at the last point — identity is never colour alone.
    const last = pts[pts.length - 1];
    add("text", { class: "end-label", x: x(last.date) + 8, y: y(last.value) + 4 }, s.label);
  });

  // Hover layer: crosshair + tooltip, snapped to the nearest date.
  const tip = tooltipEl();
  tip.style.display = "none";

  const cross = add("line", { class: "crosshair", y1: PAD.top, y2: PAD.top + plotH, x1: 0, x2: 0, opacity: 0 });
  const dots = live.map((s) => add("circle", { class: "dot", r: 4, fill: s.color, opacity: 0 }));
  const hit = add("rect", { class: "hit", x: PAD.left, y: PAD.top, width: plotW, height: plotH });

  const hide = () => {
    tip.style.display = "none";
    cross.setAttribute("opacity", 0);
    dots.forEach((d) => d.setAttribute("opacity", 0));
  };

  hit.addEventListener("pointermove", (ev) => {
    const box = svgEl.getBoundingClientRect();
    const px = ((ev.clientX - box.left) / box.width) * width;
    const raw = dates.length === 1 ? 0 : Math.round(((px - PAD.left) / plotW) * (dates.length - 1));
    const date = dates[Math.min(Math.max(raw, 0), dates.length - 1)];
    if (!date) return;

    cross.setAttribute("x1", x(date));
    cross.setAttribute("x2", x(date));
    cross.setAttribute("opacity", 1);

    const rows = [];
    live.forEach((s, i) => {
      const p = s.points.find((q) => q.date === date);
      const dot = dots[i];
      if (!p) {
        dot.setAttribute("opacity", 0);
        return;
      }
      dot.setAttribute("cx", x(date));
      dot.setAttribute("cy", y(p.value));
      dot.setAttribute("opacity", 1);
      rows.push(
        '<div class="t-row"><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' +
        s.color + '"></span>' + s.label + "<b>" + format(p.value) + "</b></div>"
      );
    });

    tip.innerHTML = '<div class="t-date">' + shortDate(date) + "</div>" + rows.join("");
    tip.style.display = "block";
    tip.style.left = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 12) + "px";
    tip.style.top = Math.max(ev.clientY - tip.offsetHeight - 12, 8) + "px";
  });
  hit.addEventListener("pointerleave", hide);
}

function renderLegend(el, series) {
  // Always present for two or more series; a single series is named by the title.
  el.innerHTML = series.length < 2 ? "" : series.map((s) =>
    '<span><span class="swatch" style="background:' + s.color + '"></span>' + s.label + "</span>"
  ).join("");
}

/* --------------------------------------------------------------- sections */

function seriesFrom(points, pick) {
  const sources = Array.from(new Set(points.flatMap((p) => Object.keys(p.by_source || {}))));
  return sources.map((src) => ({
    key: src,
    label: labelFor(src),
    color: colorFor(src),
    points: points
      .map((p) => ({ date: p.date, value: ((p.by_source || {})[src] || {})[pick] }))
      .filter((p) => p.value != null),
  })).filter((s) => s.points.length);
}

function renderTiles(points) {
  const latest = points[points.length - 1] || {};
  const prior = points.length > 1 ? points[points.length - 2] : null;

  const delta = (now, then) => {
    if (now == null || then == null || !then || !prior) return "";
    const pct = ((now - then) / then) * 100;
    if (Math.abs(pct) < 0.05) return '<div class="sub">unchanged since ' + shortDate(prior.date) + "</div>";
    // For a buyer, a falling asking price is the good direction.
    const cls = pct < 0 ? "down" : "";
    const arrow = pct > 0 ? "▲" : "▼";
    return '<div class="sub"><span class="' + cls + '">' + arrow + " " +
      Math.abs(pct).toFixed(1) + "%</span> since " + shortDate(prior.date) + "</div>";
  };

  const spread = latest.min_price ? bahtShort(latest.min_price) + " – " + bahtShort(latest.max_price) : "";

  $("#tiles").innerHTML =
    '<div class="tile"><div class="label">Median ฿/sqm</div><div class="value">' +
      baht(latest.median_ppsqm) + "</div>" + delta(latest.median_ppsqm, prior && prior.median_ppsqm) + "</div>" +
    '<div class="tile"><div class="label">Median asking price</div><div class="value">' +
      bahtShort(latest.median_price) + "</div>" + delta(latest.median_price, prior && prior.median_price) + "</div>" +
    '<div class="tile"><div class="label">Units listed</div><div class="value">' +
      (latest.listings != null ? latest.listings : "—") + '</div><div class="sub">' + spread + "</div></div>" +
    '<div class="tile"><div class="label">Tracking since</div><div class="value" style="font-size:1.1rem">' +
      (points.length ? shortDate(points[0].date) : "—") + '</div><div class="sub">' +
      points.length + " run" + (points.length === 1 ? "" : "s") + " recorded</div></div>";
}

function renderAlerts(alerts, watchId) {
  const mine = alerts.filter((a) => a.watch_id === watchId).slice(0, 25);
  const el = $("#alerts");
  if (!mine.length) {
    el.innerHTML = '<li class="empty">No alerts yet. New listings and price drops appear here from the second run onwards.</li>';
    return;
  }
  el.innerHTML = mine.map((a) => {
    const isDrop = a.type === "price_drop";
    const head = isDrop
      ? '<span class="down">▼ ' + baht(a.drop) + " (" + a.drop_pct + "%)</span> — " +
        baht(a.previous_price) + " → <strong>" + baht(a.price) + "</strong>"
      : "<strong>New listing</strong> — " + baht(a.price) +
        (a.price_per_sqm ? " · " + baht(a.price_per_sqm) + "/sqm" : "");
    const size = a.area_sqm ? " · " + a.area_sqm + " sqm" : "";
    return '<li class="' + (isDrop ? "drop" : "new") + '">' + head +
      '<div class="meta">' + shortDate(a.date) + " · " + labelFor(a.source) + size +
      ' · <a href="' + a.url + '" target="_blank" rel="noopener">open listing ↗</a></div></li>';
  }).join("");
}

function renderTable(listings) {
  const key = state.sort;
  const valueOf = (r) => {
    if (key === "change") return r.first_price && r.price ? r.price - r.first_price : 0;
    const v = r[key];
    return v == null ? (state.dir === 1 ? Infinity : -Infinity) : v;
  };

  const rows = listings.slice().sort((a, b) => {
    const va = valueOf(a);
    const vb = valueOf(b);
    if (typeof va === "string" || typeof vb === "string") {
      return state.dir * String(va).localeCompare(String(vb));
    }
    return state.dir * (va - vb);
  });

  $("#listing-count").textContent = "(" + rows.length + ")";
  const body = $("#listings tbody");
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="8" class="empty">No listings matched this watch on the last run.</td></tr>';
    return;
  }

  body.innerHTML = rows.map((r) => {
    const change = r.first_price && r.price && r.price !== r.first_price ? r.price - r.first_price : null;
    const changeCell = change == null ? "—"
      : '<span class="' + (change < 0 ? "down" : "") + '">' + (change < 0 ? "▼" : "▲") + " " +
        baht(Math.abs(change)) + "</span>";
    return "<tr>" +
      '<td class="num"><a href="' + r.url + '" target="_blank" rel="noopener">' + baht(r.price) + "</a></td>" +
      '<td class="num">' + (r.price_per_sqm ? baht(r.price_per_sqm) : "—") + "</td>" +
      '<td class="num">' + (r.area_sqm != null ? r.area_sqm : "—") + "</td>" +
      '<td class="num">' + (r.bedrooms != null ? r.bedrooms : "—") + "</td>" +
      '<td class="num">' + (r.floor != null ? r.floor : "—") + "</td>" +
      '<td class="num">' + changeCell + "</td>" +
      "<td>" + (r.first_seen ? shortDate(r.first_seen) : "—") + "</td>" +
      '<td><span class="src"><span class="swatch" style="background:' + colorFor(r.source) + '"></span>' +
        labelFor(r.source) + "</span></td>" +
      "</tr>";
  }).join("");
}

function renderSources(sources) {
  // Status is icon + label, never colour alone.
  const ICONS = { ok: "✓", blocked: "⚠", error: "✕", skipped: "–", disabled: "○" };
  const list = sources || [];
  if (!list.length) {
    $("#sources").innerHTML = '<span class="empty">No source information recorded yet.</span>';
    return;
  }
  $("#sources").innerHTML = list.map((s) => {
    const why = s.detail ? '<span class="why">' + s.detail + "</span>" : "";
    const found = s.status === "ok" ? '<span class="why">' + s.listings_found + " matched</span>" : "";
    return '<span class="pill ' + s.status + '"><span class="icon">' + (ICONS[s.status] || "?") +
      "</span><strong>" + labelFor(s.source) + "</strong> " + s.status + " " + found + why + "</span>";
  }).join("");
}

/* ------------------------------------------------------------------ wiring */

function withinRange(points) {
  if (!state.days) return points;
  const cutoff = new Date(Date.now() - state.days * 864e5).toISOString().slice(0, 10);
  return points.filter((p) => p.date >= cutoff);
}

function redraw() {
  const points = withinRange((state.history && state.history.points) || []);
  renderTiles(points);

  const ppsqm = seriesFrom(points, "median_ppsqm");
  renderLegend($("#legend-ppsqm"), ppsqm);
  drawLineChart($("#chart-ppsqm"), ppsqm, {
    format: (v) => baht(v) + "/sqm",
    formatShort: bahtShort,
  });

  const counts = seriesFrom(points, "listings");
  renderLegend($("#legend-count"), counts);
  drawLineChart($("#chart-count"), counts, {
    format: (v) => v + " listed",
    formatShort: (v) => String(Math.round(v)),
  });
}

async function loadWatch(id) {
  state.watchId = id;
  const results = await Promise.all([
    getJSON("data/history/" + id + ".json", { points: [] }),
    getJSON("data/snapshots/" + id + ".json", { listings: [], sources: [] }),
    getJSON("data/alerts.json", { alerts: [] }),
  ]);
  state.history = results[0];
  state.snapshot = results[1];

  const entry = state.index.watches.find((w) => w.id === id) || {};
  $("#subtitle").textContent = (entry.project || id) + " · " + (entry.room_type || "") +
    " · " + (entry.deal === "rent" ? "for rent" : "for sale");

  redraw();
  renderAlerts(results[2].alerts || [], id);
  renderSources(state.snapshot.sources);
  renderTable(state.snapshot.listings || []);
}

const prefersDark = () =>
  window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;

/** The theme actually on screen: an explicit choice, else the OS preference. */
function effectiveTheme() {
  return document.documentElement.getAttribute("data-theme") || (prefersDark() ? "dark" : "light");
}

function syncToggleLabel(theme) {
  const dark = theme === "dark";
  const btn = $("#theme-toggle");
  // The button offers the *other* theme, so its label must be driven by what
  // is currently on screen — including the OS default, before any click.
  btn.textContent = dark ? "Light mode" : "Dark mode";
  btn.setAttribute("aria-pressed", String(dark));
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  syncToggleLabel(theme);
  try {
    localStorage.setItem("theme", theme);
  } catch (e) { /* private mode — the toggle still works for this visit */ }
  if (state.history) redraw();
}

async function init() {
  let saved = null;
  try {
    saved = localStorage.getItem("theme");
  } catch (e) { /* storage unavailable; fall back to the OS setting */ }
  if (saved) {
    applyTheme(saved);
  } else {
    // No stored choice: leave the OS in charge, but label the button correctly.
    syncToggleLabel(effectiveTheme());
  }

  state.index = await getJSON("data/watches.json", null);
  if (!state.index || !state.index.watches || !state.index.watches.length) {
    $("#main").innerHTML = '<p class="empty">No data yet. Run <code>python -m scraper.main</code> ' +
      "(or wait for the scheduled workflow) to populate <code>data/</code>.</p>";
    return;
  }

  const select = $("#watch-select");
  select.innerHTML = state.index.watches.map((w) =>
    '<option value="' + w.id + '">' + w.project + " — " + w.room_type + "</option>"
  ).join("");
  select.addEventListener("change", () => loadWatch(select.value));

  $("#range-select").addEventListener("change", (e) => {
    state.days = Number(e.target.value);
    redraw();
  });

  $("#theme-toggle").addEventListener("click", () => {
    applyTheme(effectiveTheme() === "dark" ? "light" : "dark");
  });

  document.querySelectorAll("#listings th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      state.dir = state.sort === key ? -state.dir : 1;
      state.sort = key;
      document.querySelectorAll("#listings th").forEach((h) => h.removeAttribute("aria-sort"));
      th.setAttribute("aria-sort", state.dir === 1 ? "ascending" : "descending");
      renderTable((state.snapshot && state.snapshot.listings) || []);
    });
  });

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(redraw, 150);
  });

  if (state.index.generated_at) {
    $("#footer-note").textContent = "Last updated " + new Date(state.index.generated_at).toLocaleString() +
      ". Asking prices only — not transaction prices. Scraped from public listing pages; " +
      "duplicate listings across sites are not merged.";
  }

  await loadWatch(state.index.watches[0].id);
}

init();
