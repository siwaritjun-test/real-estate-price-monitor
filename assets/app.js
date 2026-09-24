/* Condo price monitor — reads the JSON the scrapers commit and draws the dashboard.
   No build step and no dependencies: the charts are hand-rolled SVG.

   Two views:
   - market:  every Bangkok condo project from DDproperty (data/universe/, daily)
   - project: one project's listings. Pinned watches (data/, hourly, both sites)
              and universe projects (data/universe/) share the same file format.

   The room bucket drives every figure including history; the size range can
   only narrow what is on the market *now*, because history is stored per bucket. */

const SOURCE_LABELS = { ddproperty: "DDproperty", livinginsider: "Livinginsider", hipflat: "Hipflat" };
// Fixed slot per source, assigned by identity and never by rank, so a source
// dropping out never repaints the others.
const SOURCE_VARS = { ddproperty: "--series-1", livinginsider: "--series-2", hipflat: "--series-3" };

// Keys match scraper/models.py ROOM_BUCKETS.
const ROOMS = [
  { key: "all", label: "ทั้งหมด" },
  { key: "studio", label: "สตูดิโอ" },
  { key: "1br", label: "1 ห้องนอน" },
  { key: "2br", label: "2 ห้องนอน" },
  { key: "3br+", label: "3+ ห้องนอน" },
  { key: "unknown", label: "ไม่ระบุ" },
];
const ROOM_SHORT = { studio: "สตูดิโอ", "1br": "1 นอน", "2br": "2 นอน", "3br+": "3+ นอน", unknown: "—" };

const TABLE_PAGE = 20;
const PROJECT_PAGE = 50;
const DISTRICT_TOP = 15;
const DISTRICT_MIN_LISTINGS = 5;
const STATUS_TH = { ok: "ปกติ", blocked: "ถูกบล็อก", error: "ผิดพลาด", skipped: "ข้าม", disabled: "ปิดอยู่" };
const STATUS_ICON = { ok: "✓", blocked: "⚠", error: "✕", skipped: "–", disabled: "○" };

// DDproperty publishes romanised district names; show the Thai ones.
const DISTRICT_TH = {
  "Phra Nakhon": "พระนคร", "Dusit": "ดุสิต", "Nong Chok": "หนองจอก", "Bang Rak": "บางรัก",
  "Bang Khen": "บางเขน", "Bang Kapi": "บางกะปิ", "Pathum Wan": "ปทุมวัน",
  "Pom Prap Sattru Phai": "ป้อมปราบศัตรูพ่าย", "Phra Khanong": "พระโขนง", "Min Buri": "มีนบุรี",
  "Lat Krabang": "ลาดกระบัง", "Yan Nawa": "ยานนาวา", "Samphanthawong": "สัมพันธวงศ์",
  "Phaya Thai": "พญาไท", "Thon Buri": "ธนบุรี", "Bangkok Yai": "บางกอกใหญ่", "Huai Khwang": "ห้วยขวาง",
  "Khlong San": "คลองสาน", "Taling Chan": "ตลิ่งชัน", "Bangkok Noi": "บางกอกน้อย",
  "Bang Khun Thian": "บางขุนเทียน", "Phasi Charoen": "ภาษีเจริญ", "Nong Khaem": "หนองแขม",
  "Rat Burana": "ราษฎร์บูรณะ", "Bang Phlat": "บางพลัด", "Din Daeng": "ดินแดง", "Bueng Kum": "บึงกุ่ม",
  "Sathon": "สาทร", "Bang Sue": "บางซื่อ", "Chatuchak": "จตุจักร", "Bang Kho Laem": "บางคอแหลม",
  "Prawet": "ประเวศ", "Khlong Toei": "คลองเตย", "Suan Luang": "สวนหลวง", "Chom Thong": "จอมทอง",
  "Don Mueang": "ดอนเมือง", "Ratchathewi": "ราชเทวี", "Lat Phrao": "ลาดพร้าว", "Watthana": "วัฒนา",
  "Bang Khae": "บางแค", "Lak Si": "หลักสี่", "Sai Mai": "สายไหม", "Khan Na Yao": "คันนายาว",
  "Saphan Sung": "สะพานสูง", "Wang Thonglang": "วังทองหลาง", "Khlong Sam Wa": "คลองสามวา",
  "Bang Na": "บางนา", "Thawi Watthana": "ทวีวัฒนา", "Thung Khru": "ทุ่งครุ", "Bang Bon": "บางบอน",
};
const squash = (s) => String(s || "").toLowerCase().replace(/[^a-z]/g, "");
const DISTRICT_KEYED = Object.fromEntries(Object.entries(DISTRICT_TH).map(([k, v]) => [squash(k), v]));
const thDistrict = (d) => (d ? DISTRICT_KEYED[squash(d)] || d : "—");

const state = {
  view: "market",
  pinned: null,       // data/watches.json
  market: null,       // data/universe/index.json
  room: "all",
  // market view
  district: "",
  budget: 0,
  marketSort: "listings",
  marketDir: -1,
  marketShown: PROJECT_PAGE,
  allDistricts: false,
  // project view
  projectId: null,
  projectKind: null,  // "pinned" | "universe"
  sqm: null,          // [lo, hi] currently selected
  bounds: null,       // [lo, hi] of the project's listings
  days: 90,
  history: null,
  snapshot: null,
  alerts: [],
  sort: "price",
  dir: 1,
  showAll: false,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
const colorFor = (src) => cssVar(SOURCE_VARS[src] || "--text-secondary");
const labelFor = (src) => SOURCE_LABELS[src] || src;
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmt = (n) => Math.round(n).toLocaleString("en-US");
const baht = (n) => (n || n === 0 ? "฿" + fmt(n) : "—");
const bahtShort = (n) => {
  if (!n && n !== 0) return "—";
  if (Math.abs(n) >= 1e6) return "฿" + (n / 1e6).toFixed(n >= 1e7 ? 1 : 2).replace(/\.?0+$/, "") + "M";
  if (Math.abs(n) >= 1e3) return "฿" + Math.round(n / 1e3) + "k";
  return "฿" + n;
};
const sqmFmt = (a) => Math.round(a * 10) / 10;
const millions = (n) => (n ? (n / 1e6).toFixed(2) : "—");
const thDate = (iso, withYear) =>
  new Date(iso + (iso.length === 10 ? "T00:00:00Z" : "")).toLocaleDateString("th-TH",
    Object.assign({ day: "numeric", month: "short", timeZone: iso.length === 10 ? "UTC" : "Asia/Bangkok" },
      withYear ? { year: "numeric" } : {}));
const thDateTime = (iso) => new Date(iso).toLocaleString("th-TH", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Bangkok",
}) + " น.";

function roomOf(r) {
  if (r.room) return r.room;
  if (r.bedrooms == null) return "unknown";
  if (r.bedrooms <= 0) return "studio";
  return r.bedrooms >= 3 ? "3br+" : r.bedrooms + "br";
}

function median(values) {
  const v = values.filter((x) => x != null).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

async function getJSON(path, fallback) {
  try {
    const res = await fetch(path, { cache: "no-store" });
    if (!res.ok) return fallback;
    return await res.json();
  } catch {
    return fallback;
  }
}

/* ----------------------------------------------------------- filtering */

function sizeActive() {
  return state.sqm && state.bounds && (state.sqm[0] > state.bounds[0] || state.sqm[1] < state.bounds[1]);
}

function inRoom(r) {
  return state.room === "all" || roomOf(r) === state.room;
}

function inSize(r) {
  if (!sizeActive()) return true;
  // A unit with no size cannot be shown to fit a narrowed range.
  return r.area_sqm != null && r.area_sqm >= state.sqm[0] && r.area_sqm <= state.sqm[1];
}

function currentListings() {
  return ((state.snapshot && state.snapshot.listings) || []).filter((r) => inRoom(r) && inSize(r));
}

function summary(rows) {
  const prices = rows.map((r) => r.price).filter(Boolean);
  return {
    n: rows.length,
    medianPrice: median(prices),
    medianPpsqm: median(rows.map((r) => r.price_per_sqm).filter(Boolean)),
    min: prices.length ? Math.min.apply(null, prices) : null,
    max: prices.length ? Math.max.apply(null, prices) : null,
  };
}

/** History points reduced to the selected room bucket. */
function historyPoints() {
  const all = (state.history && state.history.points) || [];
  const cutoff = state.days ? new Date(Date.now() - state.days * 864e5).toISOString().slice(0, 10) : "";
  return all
    .filter((p) => p.date >= cutoff)
    .map((p) => {
      const agg = state.room === "all" ? p : (p.by_room || {})[state.room];
      return agg && agg.listings != null ? Object.assign({ date: p.date }, agg) : null;
    })
    .filter(Boolean);
}

/* ------------------------------------------------------------- URL state */

// #v=market&r=1br&d=Watthana&b=3000000   or   #p=<project>&r=1br&s=25-35
function readHash() {
  const q = new URLSearchParams(location.hash.slice(1));
  const size = (q.get("s") || "").split("-").map(Number);
  return {
    p: q.get("p"), r: q.get("r"), d: q.get("d") || "", b: Number(q.get("b")) || 0,
    s: size.length === 2 && size.every(isFinite) ? size : null,
  };
}

function writeHash() {
  const q = new URLSearchParams();
  if (state.view === "project") {
    q.set("p", state.projectId);
    if (sizeActive()) q.set("s", state.sqm[0] + "-" + state.sqm[1]);
  } else {
    q.set("v", "market");
    if (state.district) q.set("d", state.district);
    if (state.budget) q.set("b", state.budget);
  }
  if (state.room !== "all") q.set("r", state.room);
  const next = "#" + q.toString();
  if (location.hash !== next) history.replaceState(null, "", next);
}

/* ---------------------------------------------------------------- charts */

const NS = "http://www.w3.org/2000/svg";

function svgAdder(svgEl) {
  return (tag, attrs, text, parent) => {
    const el = document.createElementNS(NS, tag);
    Object.keys(attrs).forEach((k) => el.setAttribute(k, attrs[k]));
    if (text != null) el.textContent = text;
    (parent || svgEl).appendChild(el);
    return el;
  };
}

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
    tip.hidden = true;
    document.body.appendChild(tip);
  }
  return tip;
}

function placeTip(tip, ev) {
  tip.hidden = false;
  const w = tip.offsetWidth;
  const h = tip.offsetHeight;
  let left = ev.clientX + 16;
  if (left + w > window.innerWidth - 8) left = ev.clientX - w - 16;
  tip.style.left = Math.max(8, left) + "px";
  tip.style.top = Math.max(8, Math.min(ev.clientY - h / 2, window.innerHeight - h - 8)) + "px";
}

function chartWidth(svgEl) {
  return Math.max(svgEl.parentElement.clientWidth || 640, 300);
}

/** Show a message in place of a chart. HTML rather than SVG text so it wraps on a phone. */
function emptyChart(svgEl, height, msg) {
  svgEl.innerHTML = "";
  // SVG elements have no .hidden property; the attribute is what CSS sees.
  svgEl.setAttribute("hidden", "");
  let note = svgEl.parentElement.querySelector(".chart-empty");
  if (!note) {
    note = document.createElement("p");
    note.className = "chart-empty";
    svgEl.parentElement.appendChild(note);
  }
  note.textContent = msg;
  note.hidden = false;
}

function showChart(svgEl) {
  svgEl.removeAttribute("hidden");
  const note = svgEl.parentElement.querySelector(".chart-empty");
  if (note) note.hidden = true;
}

/** Price vs size, one dot per listing, with the median ฿/sqm as a reference ray. */
function drawScatter(svgEl, rows, medianPpsqm) {
  const height = 340;
  const pts = rows.filter((r) => r.price && r.area_sqm);
  if (!pts.length) {
    emptyChart(svgEl, height, "ไม่มีประกาศที่ตรงกับตัวกรองนี้");
    return;
  }
  showChart(svgEl);
  const width = chartWidth(svgEl);
  const PAD = { top: 18, right: 24, bottom: 42, left: 62 };
  svgEl.setAttribute("viewBox", "0 0 " + width + " " + height);
  svgEl.innerHTML = "";
  const add = svgAdder(svgEl);

  const areas = pts.map((r) => r.area_sqm);
  const prices = pts.map((r) => r.price);
  const xt = niceTicks(Math.min.apply(null, areas) - 1, Math.max.apply(null, areas) + 1, 6);
  const yt = niceTicks(Math.min.apply(null, prices) * 0.95, Math.max.apply(null, prices), 6);
  const [x0, x1] = [xt[0], xt[xt.length - 1]];
  const [y0, y1] = [yt[0], yt[yt.length - 1]];
  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const x = (v) => PAD.left + ((v - x0) / (x1 - x0 || 1)) * plotW;
  const y = (v) => PAD.top + plotH - ((v - y0) / (y1 - y0 || 1)) * plotH;

  yt.forEach((t) => {
    add("line", { class: "grid-line", x1: PAD.left, x2: PAD.left + plotW, y1: y(t), y2: y(t) });
    add("text", { x: PAD.left - 8, y: y(t) + 4, "text-anchor": "end" }, bahtShort(t));
  });
  add("line", { class: "axis-line", x1: PAD.left, x2: PAD.left + plotW, y1: y(y0), y2: y(y0) });
  xt.forEach((t) => add("text", { x: x(t), y: PAD.top + plotH + 17, "text-anchor": "middle" }, t));
  add("text", { class: "axis-title", x: PAD.left + plotW / 2, y: height - 4, "text-anchor": "middle" }, "ขนาด (ตร.ม.)");

  // Reference ray: price = median ฿/sqm × size, clipped to the plot.
  if (medianPpsqm) {
    const clip = add("clipPath", { id: "plot-clip" });
    add("rect", { x: PAD.left, y: PAD.top, width: plotW, height: plotH }, null, clip);
    add("line", {
      class: "ref-line", "clip-path": "url(#plot-clip)",
      x1: x(x0), y1: y(medianPpsqm * x0), x2: x(x1), y2: y(medianPpsqm * x1),
    });
    // Label where the ray is still inside the plot, near its right end.
    let lx = x1;
    if (medianPpsqm * lx > y1) lx = y1 / medianPpsqm;
    const ly = y(medianPpsqm * lx);
    if (lx > x0) {
      add("text", { class: "ref-label", x: x(lx) - 6, y: Math.max(ly - 8, PAD.top + 10), "text-anchor": "end" },
        "ราคากลาง " + baht(medianPpsqm) + "/ตร.ม.");
    }
  }

  // Draw larger clusters first so single points stay on top.
  const dots = pts.map((r) => {
    const el = add("circle", {
      class: "pt", cx: x(r.area_sqm), cy: y(r.price), r: 5.5, fill: colorFor(r.source),
      tabindex: "0", role: "link",
      "aria-label": baht(r.price) + " " + sqmFmt(r.area_sqm) + " ตร.ม. " + labelFor(r.source),
    });
    el.addEventListener("click", () => window.open(r.url, "_blank", "noopener"));
    el.addEventListener("keydown", (ev) => { if (ev.key === "Enter") window.open(r.url, "_blank", "noopener"); });
    return { el, r, cx: x(r.area_sqm), cy: y(r.price) };
  });

  const tip = tooltipEl();
  const clear = () => {
    tip.hidden = true;
    dots.forEach((d) => d.el.classList.remove("on", "dim"));
  };

  svgEl.onpointermove = (ev) => {
    const box = svgEl.getBoundingClientRect();
    const px = ((ev.clientX - box.left) / box.width) * width;
    const py = ((ev.clientY - box.top) / box.height) * height;
    let best = null;
    let bestD = 18 * 18;
    dots.forEach((d) => {
      const dd = (d.cx - px) ** 2 + (d.cy - py) ** 2;
      if (dd < bestD) { bestD = dd; best = d; }
    });
    if (!best) { clear(); return; }
    // Everything sitting on (almost) the same spot is shown together.
    const near = dots.filter((d) => Math.abs(d.cx - best.cx) < 3 && Math.abs(d.cy - best.cy) < 3);
    dots.forEach((d) => {
      d.el.classList.toggle("on", near.includes(d));
      d.el.classList.toggle("dim", !near.includes(d));
    });
    tip.innerHTML = near.slice(0, 4).map((d) => unitTip(d.r, medianPpsqm)).join("") +
      (near.length > 4 ? '<div class="t-meta">และอีก ' + (near.length - 4) + " ประกาศ</div>" : "");
    placeTip(tip, ev);
  };
  svgEl.onpointerleave = clear;
}

function vsMedian(r, medianPpsqm) {
  if (!r.price_per_sqm || !medianPpsqm) return null;
  return (r.price_per_sqm / medianPpsqm - 1) * 100;
}

function deltaSpan(pct, digits) {
  if (pct == null) return "—";
  if (Math.abs(pct) < 0.05) return '<span class="delta">0%</span>';
  // For a buyer, below the median is the good direction.
  return '<span class="delta ' + (pct < 0 ? "good" : "bad") + '">' + (pct < 0 ? "▼ " : "▲ ") +
    Math.abs(pct).toFixed(digits == null ? 1 : digits) + "%</span>";
}

function unitTip(r, medianPpsqm) {
  const vs = vsMedian(r, medianPpsqm);
  return '<div class="t-unit"><div class="t-price">' + baht(r.price) + "</div>" +
    '<div class="t-meta">' + sqmFmt(r.area_sqm) + " ตร.ม. · " + (ROOM_SHORT[roomOf(r)] || "") +
    (r.floor != null ? " · ชั้น " + r.floor : "") + "</div>" +
    '<div class="t-row">' + baht(r.price_per_sqm) + "/ตร.ม. <b>" + (vs == null ? "" : deltaSpan(vs) + " vs กลาง") + "</b></div>" +
    '<div class="t-row"><span class="sw" style="background:' + colorFor(r.source) + '"></span>' + labelFor(r.source) + "</div></div>";
}

/**
 * Multi-series time line chart. series: [{ key, label, color, points: [{date, value}] }]
 */
function drawLineChart(svgEl, series, opts) {
  const height = opts.height || 240;
  const live = series.filter((s) => s.points.length);
  const nDates = new Set(live.flatMap((s) => s.points.map((p) => p.date))).size;
  if (nDates < 2) {
    emptyChart(svgEl, Math.min(height, 120), nDates
      ? "ยังมีข้อมูลแค่ 1 วัน — เส้นแนวโน้มจะแสดงเมื่อเก็บข้อมูลครบ 2 วัน"
      : "ยังไม่มีข้อมูลในช่วงนี้");
    return;
  }
  showChart(svgEl);
  const width = chartWidth(svgEl);
  const PAD = { top: 16, right: 104, bottom: 28, left: 62 };
  svgEl.setAttribute("viewBox", "0 0 " + width + " " + height);
  svgEl.innerHTML = "";
  const add = svgAdder(svgEl);

  const dates = Array.from(new Set(live.flatMap((s) => s.points.map((p) => p.date)))).sort();
  const values = live.flatMap((s) => s.points.map((p) => p.value));
  const ticks = niceTicks(Math.min.apply(null, values), Math.max.apply(null, values), 4);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const x = (d) => PAD.left + (dates.length === 1 ? plotW / 2 : (dates.indexOf(d) / (dates.length - 1)) * plotW);
  const y = (v) => PAD.top + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;

  ticks.forEach((t) => {
    add("line", { class: "grid-line", x1: PAD.left, x2: PAD.left + plotW, y1: y(t), y2: y(t) });
    add("text", { x: PAD.left - 8, y: y(t) + 4, "text-anchor": "end" }, opts.formatShort(t));
  });
  add("line", { class: "axis-line", x1: PAD.left, x2: PAD.left + plotW, y1: y(yMin), y2: y(yMin) });

  const step = Math.max(1, Math.ceil(dates.length / 6));
  dates.forEach((d, i) => {
    if (i % step === 0 || i === dates.length - 1) {
      add("text", { x: x(d), y: height - 8, "text-anchor": "middle" }, thDate(d));
    }
  });

  // Direct labels at the last point, nudged apart so they never overlap.
  const labels = [];
  live.forEach((s) => {
    const pts = s.points.slice().sort((a, b) => a.date.localeCompare(b.date));
    const d = pts.map((p, i) => (i ? "L" : "M") + x(p.date).toFixed(1) + "," + y(p.value).toFixed(1)).join(" ");
    add("path", { class: "series-line", d: d, stroke: s.color });
    if (pts.length <= 2) {
      pts.forEach((p) => add("circle", { class: "dot", cx: x(p.date), cy: y(p.value), r: 4.5, fill: s.color }));
    }
    const last = pts[pts.length - 1];
    labels.push({ text: s.label, x: x(last.date) + 10, y: y(last.value) + 4 });
  });
  labels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i++) labels[i].y = Math.max(labels[i].y, labels[i - 1].y + 14);
  labels.forEach((l) => add("text", { class: "end-label", x: l.x, y: l.y }, l.text));

  const tip = tooltipEl();
  const cross = add("line", { class: "crosshair", y1: PAD.top, y2: PAD.top + plotH, x1: 0, x2: 0, opacity: 0 });
  const dots = live.map((s) => add("circle", { class: "dot", r: 4.5, fill: s.color, opacity: 0 }));
  const hit = add("rect", { class: "hit", x: PAD.left - 10, y: PAD.top, width: plotW + 20, height: plotH });

  hit.addEventListener("pointermove", (ev) => {
    const box = svgEl.getBoundingClientRect();
    const px = ((ev.clientX - box.left) / box.width) * width;
    const raw = dates.length === 1 ? 0 : Math.round(((px - PAD.left) / plotW) * (dates.length - 1));
    const date = dates[Math.min(Math.max(raw, 0), dates.length - 1)];
    cross.setAttribute("x1", x(date));
    cross.setAttribute("x2", x(date));
    cross.setAttribute("opacity", 1);
    const rows = [];
    live.forEach((s, i) => {
      const p = s.points.find((q) => q.date === date);
      if (!p) { dots[i].setAttribute("opacity", 0); return; }
      dots[i].setAttribute("cx", x(date));
      dots[i].setAttribute("cy", y(p.value));
      dots[i].setAttribute("opacity", 1);
      rows.push('<div class="t-row"><span class="sw" style="background:' + s.color + '"></span>' +
        s.label + "<b>" + opts.format(p.value) + "</b></div>");
    });
    tip.innerHTML = '<div class="t-date">' + thDate(date, true) + "</div>" + rows.join("");
    placeTip(tip, ev);
  });
  hit.addEventListener("pointerleave", () => {
    tip.hidden = true;
    cross.setAttribute("opacity", 0);
    dots.forEach((d) => d.setAttribute("opacity", 0));
  });
}

/** Horizontal bars, one per district, with the Bangkok median as a reference line. */
function drawDistrictBars(svgEl, items, reference) {
  if (!items.length) {
    emptyChart(svgEl, 120, "ยังไม่มีข้อมูลรายเขตสำหรับตัวกรองนี้");
    return;
  }
  showChart(svgEl);
  const width = chartWidth(svgEl);
  const ROW = 26;
  const PAD = { top: 22, right: 70, bottom: 8, left: width < 480 ? 96 : 130 };
  const height = PAD.top + items.length * ROW + PAD.bottom;
  svgEl.setAttribute("viewBox", "0 0 " + width + " " + height);
  svgEl.innerHTML = "";
  const add = svgAdder(svgEl);

  const max = Math.max.apply(null, items.map((d) => d.value).concat(reference || 0)) * 1.05;
  const plotW = width - PAD.left - PAD.right;
  const x = (v) => PAD.left + (v / max) * plotW;
  const anySelected = items.some((d) => d.selected);
  const tip = tooltipEl();

  items.forEach((d, i) => {
    const y = PAD.top + i * ROW;
    const g = add("g", { class: "bar-row", tabindex: "0", role: "button",
      "aria-label": thDistrict(d.name) + " " + baht(d.value) + " ต่อ ตร.ม." });
    add("rect", { class: "bar-hit", x: 0, y: y, width: width, height: ROW }, null, g);
    add("text", { class: "bar-label" + (d.selected ? " on" : ""), x: PAD.left - 10, y: y + ROW / 2 + 4,
      "text-anchor": "end" }, thDistrict(d.name), g);
    add("rect", {
      class: "bar", x: PAD.left, y: y + 5, height: ROW - 10, rx: 3,
      width: Math.max(2, x(d.value) - PAD.left),
      opacity: anySelected && !d.selected ? 0.35 : 1,
    }, null, g);
    add("text", { class: "bar-value", x: x(d.value) + 6, y: y + ROW / 2 + 4 }, bahtShort(d.value), g);
    g.addEventListener("click", () => setDistrict(d.selected ? "" : d.name));
    g.addEventListener("keydown", (ev) => { if (ev.key === "Enter") setDistrict(d.selected ? "" : d.name); });
    g.addEventListener("pointermove", (ev) => {
      tip.innerHTML = '<div class="t-date">เขต' + thDistrict(d.name) + "</div>" +
        '<div class="t-row">ราคากลาง/ตร.ม.<b>' + baht(d.value) + "</b></div>" +
        '<div class="t-row">ประกาศ<b>' + fmt(d.listings) + "</b></div>" +
        (d.projects ? '<div class="t-row">โครงการ<b>' + fmt(d.projects) + "</b></div>" : "");
      placeTip(tip, ev);
    });
    g.addEventListener("pointerleave", () => { tip.hidden = true; });
  });

  if (reference) {
    add("line", { class: "ref-line", x1: x(reference), x2: x(reference), y1: PAD.top - 6, y2: height - PAD.bottom });
    add("text", { class: "ref-label", x: x(reference), y: PAD.top - 10, "text-anchor": "middle" },
      "กทม. " + bahtShort(reference));
  }
}

function renderLegend(el, keys) {
  // Only for two or more series; a single series is named by the title.
  el.innerHTML = keys.length < 2 ? "" : keys.map((k) =>
    '<span><span class="sw" style="background:' + colorFor(k) + '"></span>' + labelFor(k) + "</span>"
  ).join("");
}

/* ------------------------------------------------------------ market view */

function statsFor(entry) {
  if (!entry) return null;
  return state.room === "all" ? entry : (entry.by_room || {})[state.room] || null;
}

function districtStats(name) {
  const m = state.market;
  return statsFor(name ? (m.districts || {})[name] : m.overall);
}

function searchQuery() {
  return state.view === "market" ? $("#search").value.trim().toLowerCase() : "";
}

function marketRows() {
  const q = searchQuery();
  return state.market.projects.map((p) => {
    const m = statsFor(p);
    if (!m || !m.listings) return null;
    if (state.district && p.district !== state.district) return null;
    if (state.budget && !(m.min_price && m.min_price <= state.budget)) return null;
    if (q && !p.project.toLowerCase().includes(q)) return null;
    const dm = districtStats(p.district);
    const vs = m.median_ppsqm && dm && dm.median_ppsqm ? (m.median_ppsqm / dm.median_ppsqm - 1) * 100 : null;
    return {
      id: p.id, project: p.project, district: p.district, pinned_as: p.pinned_as,
      listings: m.listings, min_price: m.min_price, median_price: m.median_price,
      median_ppsqm: m.median_ppsqm, vs: vs,
    };
  }).filter(Boolean);
}

function projectHref(row) {
  return "#p=" + encodeURIComponent(row.pinned_as || row.id) + (state.room !== "all" ? "&r=" + state.room : "");
}

function renderMarketHero() {
  $("#page-title").textContent = "คอนโดกรุงเทพฯ";
  document.title = "คอนโดกรุงเทพฯ · ราคาคอนโด";
  $("#crumb-market").hidden = true;
  $("#crumb-project").hidden = true;
  const m = state.market;
  if (!m) {
    $("#hero-meta").innerHTML = '<span class="muted-note">กำลังเก็บข้อมูลทั้งกรุงเทพฯ รอบแรก ' +
      "(ใช้เวลาประมาณ 1 ชั่วโมง) ระหว่างนี้ดูโครงการที่ติดตามใกล้ชิดได้ด้านล่าง</span>";
    return;
  }
  $("#hero-meta").innerHTML =
    "<span>" + fmt(m.projects.length) + " โครงการ · " + fmt(m.overall ? m.overall.listings : 0) + " ประกาศขาย</span>" +
    '<span class="live">อัปเดต ' + thDateTime(m.generated_at) + "</span>" +
    '<span class="muted-note">ข้อมูล DDproperty · อัปเดตวันละครั้ง</span>';
}

function renderPinned() {
  const list = (state.pinned && state.pinned.watches) || [];
  $("#pinned-card").hidden = !list.length;
  $("#pinned").innerHTML = list.map((w) => {
    const n = state.room === "all" ? w.listings : (w.rooms || {})[state.room] || 0;
    return '<a class="pin" href="#p=' + encodeURIComponent(w.id) + (state.room !== "all" ? "&r=" + state.room : "") + '">' +
      '<span class="pin-name">' + esc(w.project) + "</span>" +
      '<span class="pin-meta">' + n + " ประกาศ" + (state.room === "all" && w.median_ppsqm ? " · " + baht(w.median_ppsqm) + "/ตร.ม." : "") +
      " · อัปเดต " + (state.pinned.generated_at ? thDateTime(state.pinned.generated_at) : "—") + "</span>" +
      '<span class="pin-go" aria-hidden="true">→</span></a>';
  }).join("");
}

function renderMarketTiles(rows) {
  const ds = districtStats(state.district);
  const where = state.district ? "เขต" + thDistrict(state.district) : "ทั่วกรุงเทพฯ";
  const listings = rows.reduce((s, r) => s + (r.listings || 0), 0);
  const value = rows.filter((r) => r.listings >= 3 && r.median_ppsqm).sort((a, b) => a.median_ppsqm - b.median_ppsqm)[0];
  $("#market-tiles").innerHTML =
    '<div class="tile"><div class="label">โครงการที่ตรงเงื่อนไข</div><div class="value">' + fmt(rows.length) +
      ' <small>โครงการ</small></div><div class="sub">' + fmt(listings) + " ประกาศขาย</div></div>" +
    '<div class="tile"><div class="label">ราคากลางต่อ ตร.ม.</div><div class="value">' +
      baht(ds && ds.median_ppsqm) + '</div><div class="sub">' + where + "</div></div>" +
    '<div class="tile"><div class="label">ราคากลางต่อห้อง</div><div class="value">' +
      millions(ds && ds.median_price) + ' <small>ล้านบาท</small></div><div class="sub">' + where + "</div></div>" +
    '<div class="tile highlight"><div class="label">โครงการ ฿/ตร.ม. ต่ำสุด</div><div class="value">' +
      (value ? baht(value.median_ppsqm) : "—") + '</div><div class="sub">' +
      (value ? '<a href="' + projectHref(value) + '">' + esc(value.project) + "</a> · " + value.listings + " ประกาศ"
        : "ต้องมีอย่างน้อย 3 ประกาศ") + "</div></div>";
}

function renderDistricts() {
  const m = state.market;
  const all = Object.keys(m.districts || {}).map((name) => {
    const s = statsFor(m.districts[name]);
    return s && s.median_ppsqm && s.listings >= DISTRICT_MIN_LISTINGS
      ? { name, value: s.median_ppsqm, listings: s.listings, projects: m.districts[name].projects,
          selected: name === state.district }
      : null;
  }).filter(Boolean).sort((a, b) => b.value - a.value);

  let shown = state.allDistricts ? all : all.slice(0, DISTRICT_TOP);
  // Keep the selected district visible even when it is outside the top rows.
  const sel = all.find((d) => d.selected);
  if (sel && !shown.includes(sel)) shown = shown.concat(sel);
  const overall = statsFor(m.overall);
  drawDistrictBars($("#chart-districts"), shown, overall && overall.median_ppsqm);

  const more = $("#districts-more");
  more.hidden = all.length <= DISTRICT_TOP;
  more.textContent = state.allDistricts ? "แสดงเฉพาะ " + DISTRICT_TOP + " เขตแพงสุด" : "แสดงทุกเขต (" + all.length + ")";
}

function renderProjectsTable(rows) {
  const key = state.marketSort;
  const dir = state.marketDir;
  const sorted = rows.slice().sort((a, b) => {
    // Pinned projects always lead.
    if (!!a.pinned_as !== !!b.pinned_as) return a.pinned_as ? -1 : 1;
    const va = a[key];
    const vb = b[key];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === "string") return dir * (key === "district" ? thDistrict(va) : va).localeCompare(key === "district" ? thDistrict(vb) : vb, "th");
    return dir * (va - vb);
  });

  $("#project-count").textContent = "(" + fmt(sorted.length) + ")";
  const body = $("#projects tbody");
  if (!sorted.length) {
    body.innerHTML = '<tr><td colspan="7" class="empty">ไม่มีโครงการที่ตรงกับตัวกรองนี้ ลองเปลี่ยนเขต งบประมาณ หรือประเภทห้อง</td></tr>';
    $("#projects-more").hidden = true;
    return;
  }
  const shown = sorted.slice(0, state.marketShown);
  body.innerHTML = shown.map((r) =>
    "<tr>" +
      '<td class="proj"><a href="' + projectHref(r) + '">' + esc(r.project) + "</a>" +
        (r.pinned_as ? ' <span class="pin-tag" title="ติดตามใกล้ชิด ทุกชั่วโมง">ติดตาม</span>' : "") +
        '<span class="sm-only proj-sub">' + thDistrict(r.district) + " · เริ่ม " + bahtShort(r.min_price) + "</span></td>" +
      '<td class="hide-sm">' + thDistrict(r.district) + "</td>" +
      '<td class="num">' + fmt(r.listings) + "</td>" +
      '<td class="num hide-sm">' + bahtShort(r.min_price) + "</td>" +
      '<td class="num hide-sm">' + bahtShort(r.median_price) + "</td>" +
      '<td class="num">' + (r.median_ppsqm ? fmt(r.median_ppsqm) : "—") + "</td>" +
      '<td class="num">' + deltaSpan(r.vs, 0) + "</td>" +
    "</tr>"
  ).join("");
  const more = $("#projects-more");
  more.hidden = sorted.length <= state.marketShown;
  more.textContent = "แสดงเพิ่ม (" + fmt(Math.min(PROJECT_PAGE, sorted.length - state.marketShown)) +
    " จาก " + fmt(sorted.length - state.marketShown) + " ที่เหลือ)";
}

function renderDistrictSelect() {
  const m = state.market;
  const names = Object.keys((m && m.districts) || {}).sort((a, b) => thDistrict(a).localeCompare(thDistrict(b), "th"));
  $("#district-select").innerHTML = '<option value="">ทุกเขต</option>' +
    names.map((n) => '<option value="' + esc(n) + '">' + thDistrict(n) + " (" + m.districts[n].projects + ")</option>").join("");
  $("#district-select").value = state.district;
}

function renderMarket() {
  renderMarketHero();
  renderRoomChips();
  renderPinned();
  const hasMarket = !!(state.market && state.market.projects && state.market.projects.length);
  $$("#view-market > section:not(#pinned-card)").forEach((el) => { el.hidden = !hasMarket; });
  if (hasMarket) {
    $("#district-select").value = state.district;
    $("#budget-select").value = String(state.budget);
    const rows = marketRows();
    renderMarketTiles(rows);
    renderDistricts();
    renderProjectsTable(rows);
  }
  writeHash();
}

function setDistrict(name) {
  state.district = name;
  state.marketShown = PROJECT_PAGE;
  renderMarket();
}

/* ------------------------------------------------------------ project view */

function currentEntry() {
  if (state.projectKind === "pinned") return state.pinned.watches.find((w) => w.id === state.projectId) || {};
  return (state.market.projects || []).find((p) => p.id === state.projectId) || {};
}

function districtOfProject() {
  if (state.projectKind === "universe") return currentEntry().district;
  const u = state.market && state.market.projects.find((p) => p.pinned_as === state.projectId);
  return u ? u.district : null;
}

function renderProjectHero() {
  const entry = currentEntry();
  const name = entry.project || state.projectId;
  const district = districtOfProject();
  $("#page-title").textContent = name;
  document.title = name + " · ราคาคอนโด";
  const crumbMarket = $("#crumb-market");
  crumbMarket.hidden = false;
  crumbMarket.href = "#v=market" + (state.room !== "all" ? "&r=" + state.room : "");
  const crumb = $("#crumb-project");
  crumb.hidden = !district;
  crumb.innerHTML = district ? '<a href="#v=market&d=' + encodeURIComponent(district) +
    (state.room !== "all" ? "&r=" + state.room : "") + '">เขต' + thDistrict(district) + "</a>" : "";

  const updated = state.snapshot && state.snapshot.updated_at;
  const bits = ["<span>ประกาศขาย " + (((state.snapshot && state.snapshot.listings) || []).length) + " รายการ</span>"];
  if (updated) bits.push('<span class="live">อัปเดต ' + thDateTime(updated) + "</span>");
  bits.push(state.projectKind === "pinned"
    ? '<span class="muted-note">ติดตามใกล้ชิด · DDproperty + Livinginsider · อัปเดตทุกชั่วโมง</span>'
    : '<span class="muted-note">ข้อมูล DDproperty · อัปเดตวันละครั้ง</span>');
  $("#hero-meta").innerHTML = bits.join("");
}

function renderRoomChips() {
  const counts = { all: 0 };
  if (state.view === "project") {
    const all = (state.snapshot && state.snapshot.listings) || [];
    counts.all = all.length;
    all.forEach((r) => { const k = roomOf(r); counts[k] = (counts[k] || 0) + 1; });
  } else if (state.market) {
    // Market view: how many projects have at least one unit of each type.
    counts.all = state.market.projects.length;
    state.market.projects.forEach((p) => Object.keys(p.by_room || {}).forEach((k) => { counts[k] = (counts[k] || 0) + 1; }));
  }
  $("#room-chips").innerHTML = ROOMS
    .filter((r) => r.key !== "unknown" || counts.unknown)
    .map((r) => {
      const n = counts[r.key] || 0;
      return '<button type="button" class="chip" role="radio" data-room="' + r.key + '" aria-checked="' +
        (state.room === r.key) + '"' + (n || r.key === "all" ? "" : " disabled") + ">" + r.label +
        '<span class="n">' + fmt(n) + "</span></button>";
    }).join("");
}

function setupSizeSlider() {
  const areas = ((state.snapshot && state.snapshot.listings) || []).map((r) => r.area_sqm).filter((a) => a != null);
  const lo = areas.length ? Math.floor(Math.min.apply(null, areas)) : 0;
  const hi = areas.length ? Math.ceil(Math.max.apply(null, areas)) : 100;
  state.bounds = [lo, hi];
  const keep = state.sqm && state.sqm[0] >= lo && state.sqm[1] <= hi && state.sqm[0] <= state.sqm[1];
  if (!keep) state.sqm = [lo, hi];
  ["#size-min", "#size-max"].forEach((sel, i) => {
    const input = $(sel);
    input.min = lo;
    input.max = hi;
    input.step = 1;
    input.value = state.sqm[i];
  });
  $("#size-range").closest(".filter").hidden = !areas.length || lo === hi;
  syncSizeUI();
}

function syncSizeUI() {
  if (!state.bounds) return;
  const [lo, hi] = state.bounds;
  const span = hi - lo || 1;
  const fill = $("#size-fill");
  fill.style.left = ((state.sqm[0] - lo) / span) * 100 + "%";
  fill.style.right = ((hi - state.sqm[1]) / span) * 100 + "%";
  $("#size-readout").textContent = state.sqm[0] + "–" + state.sqm[1] + " ตร.ม.";
  $("#size-reset").hidden = !sizeActive();
}

function renderTiles(rows) {
  const now = summary(rows);
  // Day-on-day change comes from history, which is per room bucket; it only
  // describes the current view when the size range is not narrowed.
  const pts = historyPoints();
  const last = pts[pts.length - 1];
  const prior = pts.length > 1 ? pts[pts.length - 2] : null;
  const change = (key) => {
    if (sizeActive() || !prior || !last || !last[key] || !prior[key]) return null;
    return ((last[key] - prior[key]) / prior[key]) * 100;
  };
  const changeLine = (pct) => {
    if (sizeActive()) return "ขนาด " + state.sqm[0] + "–" + state.sqm[1] + " ตร.ม.";
    if (pct == null) return "เริ่มเก็บข้อมูล " + (pts.length ? thDate(pts[0].date) : "วันนี้");
    return deltaSpan(pct) + " จาก " + thDate(prior.date);
  };

  // Where the project sits against its district, same room type.
  let districtLine = "";
  const district = districtOfProject();
  if (state.market && district && now.medianPpsqm && !sizeActive()) {
    const ds = districtStats(district);
    if (ds && ds.median_ppsqm) {
      districtLine = deltaSpan((now.medianPpsqm / ds.median_ppsqm - 1) * 100, 0) + " เทียบเขต" + thDistrict(district);
    }
  }

  const cheapest = rows.filter((r) => r.price).sort((a, b) => a.price - b.price)[0];
  const bestValue = rows.filter((r) => r.price_per_sqm).sort((a, b) => a.price_per_sqm - b.price_per_sqm)[0];

  $("#tiles").innerHTML =
    '<div class="tile"><div class="label">ราคากลางต่อ ตร.ม.</div><div class="value">' +
      baht(now.medianPpsqm) + '</div><div class="sub">' + changeLine(change("median_ppsqm")) +
      (districtLine ? "<br>" + districtLine : "") + "</div></div>" +
    '<div class="tile"><div class="label">ราคากลาง</div><div class="value">' +
      millions(now.medianPrice) + ' <small>ล้านบาท</small></div><div class="sub">' +
      (now.min ? "ช่วง " + bahtShort(now.min) + " – " + bahtShort(now.max) : "—") + "</div></div>" +
    '<div class="tile"><div class="label">ประกาศขายตอนนี้</div><div class="value">' + now.n +
      ' <small>ห้อง</small></div><div class="sub">' +
      (last && !sizeActive() && prior ? (last.listings - prior.listings >= 0 ? "+" : "") +
        (last.listings - prior.listings) + " จาก " + thDate(prior.date) : "จาก " + new Set(rows.map((r) => r.source)).size + " เว็บไซต์") +
      "</div></div>" +
    '<div class="tile highlight"><div class="label">คุ้มสุดต่อ ตร.ม.</div><div class="value">' +
      (bestValue ? baht(bestValue.price_per_sqm) : "—") + '</div><div class="sub">' +
      (bestValue ? baht(bestValue.price) + " · " + sqmFmt(bestValue.area_sqm) + " ตร.ม. · " +
        '<a href="' + esc(bestValue.url) + '" target="_blank" rel="noopener">ดูประกาศ ↗</a>' : "—") +
      (cheapest && bestValue && cheapest !== bestValue ? "<br>ถูกสุด " + baht(cheapest.price) +
        ' · <a href="' + esc(cheapest.url) + '" target="_blank" rel="noopener">ดู ↗</a>' : "") +
      "</div></div>";
}

function renderTrend() {
  const pts = historyPoints();
  const sources = Array.from(new Set(pts.flatMap((p) => Object.keys(p.by_source || {})))).sort();
  const seriesOf = (pick) => sources.map((src) => ({
    key: src,
    label: labelFor(src),
    color: colorFor(src),
    points: pts.map((p) => ({ date: p.date, value: ((p.by_source || {})[src] || {})[pick] }))
      .filter((p) => p.value != null),
  })).filter((s) => s.points.length);

  const ppsqm = seriesOf("median_ppsqm");
  const multiDay = new Set(pts.map((p) => p.date)).size > 1;
  renderLegend($("#legend-ppsqm"), multiDay ? ppsqm.map((s) => s.key) : []);
  $("#count-h").hidden = !multiDay;
  $("#chart-count").parentElement.hidden = !multiDay;
  drawLineChart($("#chart-ppsqm"), ppsqm, { format: (v) => baht(v) + "/ตร.ม.", formatShort: bahtShort });
  drawLineChart($("#chart-count"), seriesOf("listings"), {
    height: 170, format: (v) => v + " ห้อง", formatShort: (v) => String(Math.round(v)),
  });

  const roomName = (ROOMS.find((r) => r.key === state.room) || ROOMS[0]).label;
  let cap = (sources.length > 1 ? "เส้นละ 1 เว็บไซต์ · " : "") + "ห้อง: " + roomName +
    " · เก็บประวัติเป็นรายวัน";
  if (sizeActive()) cap += " · กราฟนี้ไม่กรองตามขนาด (เก็บประวัติแยกตามจำนวนห้องนอนเท่านั้น)";
  $("#trend-caption").textContent = cap;
}

function describeRoomType(rt) {
  if (!rt) return "ทุกห้อง";
  const bits = [];
  if (rt.bedrooms != null) bits.push(rt.bedrooms === 0 ? "สตูดิโอ" : rt.bedrooms + " ห้องนอน");
  if (rt.min_sqm != null || rt.max_sqm != null) {
    bits.push((rt.min_sqm != null ? rt.min_sqm : "") + "–" + (rt.max_sqm != null ? rt.max_sqm : "") + " ตร.ม.");
  }
  return bits.join(" ") || "ทุกห้อง";
}

function renderAlerts() {
  const el = $("#alerts");
  if (state.projectKind !== "pinned") {
    $("#alert-scope").textContent = "แจ้งเตือนเปิดเฉพาะโครงการที่ติดตามใกล้ชิด";
    el.innerHTML = '<li class="empty">โครงการนี้อยู่ในภาพรวมตลาด (อัปเดตวันละครั้ง) ยังไม่ได้ตั้งแจ้งเตือน ' +
      "ถ้าต้องการติดตามทุกชั่วโมงพร้อมแจ้งเตือนราคาลด ให้เพิ่มโครงการนี้เป็นโครงการที่ติดตามใกล้ชิด</li>";
    return;
  }
  const entry = currentEntry();
  $("#alert-scope").textContent = "ประกาศใหม่และราคาลด · แจ้งเตือนเฉพาะห้อง " +
    describeRoomType(entry.alert_room_type) + " (ส่งเป็น GitHub issue)";

  const mine = state.alerts
    .filter((a) => a.watch_id === state.projectId && inRoom(a) && inSize(a))
    .slice(0, 12);
  if (!mine.length) {
    el.innerHTML = '<li class="empty">ยังไม่มีแจ้งเตือนสำหรับตัวกรองนี้ เมื่อมีประกาศใหม่หรือราคาลดจะแสดงที่นี่</li>';
    return;
  }
  el.innerHTML = mine.map((a) => {
    const drop = a.type === "price_drop";
    const head = drop
      ? baht(a.previous_price) + " → <strong>" + baht(a.price) + '</strong> <span class="delta good">▼ ' +
        a.drop_pct + "%</span>"
      : "<strong>" + baht(a.price) + "</strong>" + (a.price_per_sqm ? " · " + baht(a.price_per_sqm) + "/ตร.ม." : "");
    return '<li><span class="badge ' + (drop ? "drop" : "new") + '">' + (drop ? "ราคาลด" : "ใหม่") + "</span><div>" +
      head + '<div class="meta">' + thDate(a.date) + " · " + (ROOM_SHORT[roomOf(a)] || "") +
      (a.area_sqm ? " " + sqmFmt(a.area_sqm) + " ตร.ม." : "") + " · " + labelFor(a.source) +
      ' · <a href="' + esc(a.url) + '" target="_blank" rel="noopener">ดูประกาศ ↗</a></div></div></li>';
  }).join("");
}

function renderSources() {
  const list = (state.snapshot && state.snapshot.sources) || [];
  const all = (state.snapshot && state.snapshot.listings) || [];
  if (!list.length) {
    $("#sources").innerHTML = '<li class="empty">ยังไม่มีข้อมูลสถานะ</li>';
    return;
  }
  // Status is icon + label, never colour alone.
  $("#sources").innerHTML = list.map((s) => {
    const n = all.filter((r) => r.source === s.source).length;
    const why = s.status === "disabled"
      ? "เว็บนี้บล็อกการดึงข้อมูลอัตโนมัติทุกรูปแบบ จึงปิดไว้โดยตั้งใจ"
      : s.status !== "ok" && s.detail ? esc(s.detail) : "";
    return '<li class="' + s.status + '"><span class="icon">' + (STATUS_ICON[s.status] || "?") + "</span>" +
      "<span><strong>" + labelFor(s.source) + "</strong> · " + (STATUS_TH[s.status] || s.status) + "</span>" +
      '<span class="n">' + (s.status === "ok" ? n + " ห้อง" : "") + "</span>" +
      (why ? '<span class="why">' + why + "</span>" : "") + "</li>";
  }).join("");
}

function renderTable(rows, medianPpsqm) {
  const key = state.sort;
  const valueOf = (r) => {
    if (key === "change") return r.first_price && r.price ? r.price - r.first_price : 0;
    if (key === "vs") { const v = vsMedian(r, medianPpsqm); return v == null ? Infinity * state.dir : v; }
    const v = r[key];
    return v == null ? (state.dir === 1 ? Infinity : -Infinity) : v;
  };
  const sorted = rows.slice().sort((a, b) => {
    const va = valueOf(a);
    const vb = valueOf(b);
    if (typeof va === "string" || typeof vb === "string") return state.dir * String(va).localeCompare(String(vb));
    return state.dir * (va - vb);
  });

  $("#listing-count").textContent = "(" + sorted.length + ")";
  const body = $("#listings tbody");
  const more = $("#show-all");
  if (!sorted.length) {
    body.innerHTML = '<tr><td colspan="9" class="empty">ไม่มีประกาศที่ตรงกับตัวกรองนี้ ลองเลือกประเภทห้องอื่นหรือขยายช่วงขนาด</td></tr>';
    more.hidden = true;
    return;
  }
  const shown = state.showAll ? sorted : sorted.slice(0, TABLE_PAGE);
  more.hidden = sorted.length <= TABLE_PAGE;
  more.textContent = state.showAll ? "ย่อรายการ" : "แสดงทั้งหมด " + sorted.length + " ประกาศ";
  body.innerHTML = shown.map((r) => {
    const change = r.first_price && r.price && r.price !== r.first_price ? r.price - r.first_price : null;
    const changeCell = change == null ? '<span class="muted">—</span>'
      : '<span class="delta ' + (change < 0 ? "good" : "bad") + '">' + (change < 0 ? "▼ " : "▲ ") +
        bahtShort(Math.abs(change)) + "</span>";
    return "<tr>" +
      '<td class="num"><a class="price" href="' + esc(r.url) + '" target="_blank" rel="noopener"' +
        (r.title ? ' title="' + esc(r.title) + '"' : "") + ">" + baht(r.price) + "</a></td>" +
      '<td class="num">' + (r.price_per_sqm ? fmt(r.price_per_sqm) : "—") + "</td>" +
      '<td class="num">' + deltaSpan(vsMedian(r, medianPpsqm)) + "</td>" +
      '<td class="num">' + (r.area_sqm != null ? sqmFmt(r.area_sqm) + " ตร.ม." : "—") + "</td>" +
      '<td><span class="room-tag">' + (ROOM_SHORT[roomOf(r)] || "—") + "</span></td>" +
      '<td class="num' + (r.floor == null ? " muted" : "") + '">' + (r.floor != null ? r.floor : "—") + "</td>" +
      '<td class="num">' + changeCell + "</td>" +
      "<td>" + (r.first_seen ? thDate(r.first_seen) : "—") + "</td>" +
      '<td><span class="src"><span class="sw" style="background:' + colorFor(r.source) + '"></span>' +
        labelFor(r.source) + "</span></td>" +
      "</tr>";
  }).join("");
}

function renderProject() {
  const rows = currentListings();
  const med = summary(rows).medianPpsqm;
  renderProjectHero();
  renderRoomChips();
  syncSizeUI();
  renderTiles(rows);
  renderLegend($("#legend-scatter"), Array.from(new Set(rows.map((r) => r.source))).sort());
  drawScatter($("#chart-scatter"), rows, med);
  renderTrend();
  renderAlerts();
  renderTable(rows, med);
  writeHash();
}

/* ------------------------------------------------------------------ wiring */

function setView(view) {
  state.view = view;
  $("#view-market").hidden = view !== "market";
  $("#view-project").hidden = view !== "project";
  $$(".market-only").forEach((el) => { el.hidden = view !== "market" || !state.market; });
  $$(".project-only").forEach((el) => { el.hidden = view !== "project"; });
  $("#search").placeholder = view === "market" ? "กรองตามชื่อ หรือเลือกเพื่อเปิด…" : "ไปยังโครงการอื่น…";
}

function render() {
  if (state.view === "market") renderMarket();
  else if (state.snapshot) renderProject();
}

async function openProject(id, hash) {
  const pinned = ((state.pinned && state.pinned.watches) || []).find((w) => w.id === id);
  const uni = !pinned && state.market ? state.market.projects.find((p) => p.id === id) : null;
  if (!pinned && !uni) {
    location.hash = "#v=market";
    return;
  }
  if (id !== state.projectId) {
    const root = pinned ? "data/" : "data/universe/";
    const [hist, snap] = await Promise.all([
      getJSON(root + "history/" + id + ".json", { points: [] }),
      getJSON(root + "snapshots/" + id + ".json", { listings: [], sources: [] }),
    ]);
    state.projectId = id;
    state.projectKind = pinned ? "pinned" : "universe";
    state.history = hist;
    state.snapshot = snap;
    state.showAll = false;
    state.sqm = hash.s;
    setupSizeSlider();
    renderSources();
    window.scrollTo(0, 0);
  }
  $("#search").value = "";
  setView("project");
  renderProject();
}

function route() {
  const h = readHash();
  state.room = h.r && ROOMS.some((r) => r.key === h.r) ? h.r : "all";
  if (h.p) {
    openProject(h.p, h);
    return;
  }
  const wasProject = state.view === "project";
  state.district = h.d;
  state.budget = h.b;
  state.marketShown = PROJECT_PAGE;
  setView("market");
  renderMarket();
  if (wasProject) window.scrollTo(0, 0);
}

function fillDatalist() {
  const opts = [];
  ((state.pinned && state.pinned.watches) || []).forEach((w) => opts.push([w.project, "ติดตามใกล้ชิด"]));
  ((state.market && state.market.projects) || []).forEach((p) => {
    if (!p.pinned_as) opts.push([p.project, thDistrict(p.district) + " · " + p.listings + " ประกาศ"]);
  });
  $("#project-list").innerHTML = opts.map(([v, l]) => '<option value="' + esc(v) + '" label="' + esc(l) + '"></option>').join("");
}

function findProjectByName(name) {
  const n = name.trim().toLowerCase();
  if (!n) return null;
  const w = ((state.pinned && state.pinned.watches) || []).find((x) => x.project.toLowerCase() === n);
  if (w) return w.id;
  const p = ((state.market && state.market.projects) || []).find((x) => x.project.toLowerCase() === n);
  return p ? p.pinned_as || p.id : null;
}

function effectiveTheme() {
  const set = document.documentElement.getAttribute("data-theme");
  if (set) return set;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function syncThemeButton() {
  const dark = effectiveTheme() === "dark";
  document.documentElement.classList.toggle("is-dark", dark);
  $("#theme-toggle").setAttribute("aria-label", dark ? "เปลี่ยนเป็นโหมดสว่าง" : "เปลี่ยนเป็นโหมดมืด");
}

function syncRangeSeg() {
  $$("#range-seg button").forEach((b) => b.setAttribute("aria-checked", String(Number(b.dataset.days) === state.days)));
}

async function init() {
  syncThemeButton();
  syncRangeSeg();

  const [pinned, market, alerts] = await Promise.all([
    getJSON("data/watches.json", null),
    getJSON("data/universe/index.json", null),
    getJSON("data/alerts.json", { alerts: [] }),
  ]);
  state.pinned = pinned;
  state.market = market && market.projects && market.projects.length ? market : null;
  state.alerts = alerts.alerts || [];

  if (!state.pinned && !state.market) {
    $("#page-title").textContent = "ยังไม่มีข้อมูล";
    $("#view-market").hidden = false;
    $("#view-market").innerHTML = '<p class="empty">รัน <code>python -m scraper.main</code> และ ' +
      "<code>python -m scraper.universe</code> (หรือรอรอบอัตโนมัติ) เพื่อสร้างข้อมูลใน <code>data/</code></p>";
    return;
  }

  if (state.market) renderDistrictSelect();
  fillDatalist();

  $("#room-chips").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-room]");
    if (!btn || btn.disabled) return;
    state.room = btn.dataset.room;
    state.marketShown = PROJECT_PAGE;
    render();
  });

  $("#district-select").addEventListener("change", (ev) => setDistrict(ev.target.value));
  $("#budget-select").addEventListener("change", (ev) => {
    state.budget = Number(ev.target.value);
    state.marketShown = PROJECT_PAGE;
    renderMarket();
  });
  $("#districts-more").addEventListener("click", () => {
    state.allDistricts = !state.allDistricts;
    renderDistricts();
  });
  $("#projects-more").addEventListener("click", () => {
    state.marketShown += PROJECT_PAGE;
    renderProjectsTable(marketRows());
  });

  // Search: an exact name from the list opens that project; anything else
  // filters the market table as you type.
  $("#search").addEventListener("input", (ev) => {
    const id = findProjectByName(ev.target.value);
    if (id && (ev.inputType === "insertReplacementText" || ev.inputType == null || state.view === "project")) {
      location.hash = "#p=" + encodeURIComponent(id) + (state.room !== "all" ? "&r=" + state.room : "");
      return;
    }
    if (state.view === "market" && state.market) {
      state.marketShown = PROJECT_PAGE;
      const rows = marketRows();
      renderMarketTiles(rows);
      renderProjectsTable(rows);
    }
  });
  $("#search").addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter") return;
    const id = findProjectByName(ev.target.value);
    if (id) location.hash = "#p=" + encodeURIComponent(id);
  });

  const onSlide = (which) => (ev) => {
    const v = Number(ev.target.value);
    if (which === 0) state.sqm = [Math.min(v, state.sqm[1]), state.sqm[1]];
    else state.sqm = [state.sqm[0], Math.max(v, state.sqm[0])];
    ev.target.value = state.sqm[which];
    syncSizeUI();
  };
  $("#size-min").addEventListener("input", onSlide(0));
  $("#size-max").addEventListener("input", onSlide(1));
  // Redraw on release rather than on every pixel of drag.
  ["#size-min", "#size-max"].forEach((s) => $(s).addEventListener("change", renderProject));
  $("#size-reset").addEventListener("click", () => {
    state.sqm = state.bounds.slice();
    $("#size-min").value = state.sqm[0];
    $("#size-max").value = state.sqm[1];
    renderProject();
  });

  $("#range-seg").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-days]");
    if (!btn) return;
    state.days = Number(btn.dataset.days);
    syncRangeSeg();
    renderTrend();
    renderTiles(currentListings());
  });

  $("#theme-toggle").addEventListener("click", () => {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch (e) { /* private mode: this visit only */ }
    syncThemeButton();
    render();
  });
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      syncThemeButton();
      render();
    });
  }

  $$("#listings th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      state.dir = state.sort === key ? -state.dir : 1;
      state.sort = key;
      $$("#listings th").forEach((h) => h.removeAttribute("aria-sort"));
      th.setAttribute("aria-sort", state.dir === 1 ? "ascending" : "descending");
      const rows = currentListings();
      renderTable(rows, summary(rows).medianPpsqm);
    });
  });
  $$("#projects th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      // Text columns start A→Z, numbers start high→low except price-like ones.
      const firstDir = ["project", "district", "min_price", "median_price", "median_ppsqm", "vs"].includes(key) ? 1 : -1;
      state.marketDir = state.marketSort === key ? -state.marketDir : firstDir;
      state.marketSort = key;
      $$("#projects th").forEach((h) => h.removeAttribute("aria-sort"));
      th.setAttribute("aria-sort", state.marketDir === 1 ? "ascending" : "descending");
      renderProjectsTable(marketRows());
    });
  });

  $("#show-all").addEventListener("click", () => {
    state.showAll = !state.showAll;
    const rows = currentListings();
    renderTable(rows, summary(rows).medianPpsqm);
  });

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 150);
  });

  window.addEventListener("hashchange", route);
  route();
}

init();
