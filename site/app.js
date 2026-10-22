// Static viewer for the "Nations' Land Over Time" dataset.
// No build step, no CDN, no map tiles: hand-rolled SVG only.

const SVG_NS = "http://www.w3.org/2000/svg";
const WORLD_LAND_KM2 = 148_940_000;
const LIST_LIMIT = 2000;

const state = {
  meta: null,
  polities: [],
  series: new Map(),
  shardCache: new Map(),
  selected: null,
  shard: null,
  intervals: [],
  filter: "all",
  letter: "",
  year: 0,
  playing: false,
  timer: null,
  logScale: false,
  showAll: false,
  chart: null,
  map: null,
};

const dom = {};

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function formatArea(value) {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value).toLocaleString()} km²`;
}

function formatYear(year) {
  return year < 0 ? `${Math.abs(year)} BCE` : `${year} CE`;
}

function formatShare(area) {
  if (!area) return "—";
  const pct = (area / WORLD_LAND_KM2) * 100;
  if (pct >= 1) return `${pct.toFixed(1)}%`;
  if (pct >= 0.01) return `${pct.toFixed(2)}%`;
  return `${pct.toFixed(4)}%`;
}

function niceTicks(min, max, count) {
  if (!(max > min)) return [min];
  const raw = (max - min) / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const candidates = [1, 2, 2.5, 5, 10].map((m) => m * magnitude);
  const step = candidates.find((c) => (max - min) / c <= count) || magnitude * 10;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-6; v += step) ticks.push(v);
  return ticks;
}

function logTicks(min, max) {
  const ticks = [];
  const lower = Math.max(1, min);
  const start = Math.floor(Math.log10(lower));
  const end = Math.ceil(Math.log10(Math.max(max, 10)));
  for (let e = start; e <= end; e += 1) {
    const value = Math.pow(10, e);
    if (value >= lower * 0.999 && value <= max * 1.001) ticks.push(value);
  }
  return ticks.length ? ticks : [lower, max];
}

function initialOf(name) {
  const match = name.match(/[a-z]/i);
  return match ? match[0].toUpperCase() : "#";
}

function cacheDom() {
  const ids = [
    "landing", "app", "enter", "enter-link", "back-link", "alpha", "plates",
    "search", "list-meta", "polity-list", "status", "detail", "polity-name", "polity-meta",
    "stat-area", "stat-share", "stat-window", "stat-area-label", "stat-share-label",
    "stat-window-label", "chart", "map", "chart-tooltip", "play",
    "year", "year-label", "log-scale", "show-all", "footer-credit",
  ];
  for (const id of ids) dom[id] = document.getElementById(id);
}

function showStatus(html, isError = false) {
  dom.status.innerHTML = html;
  dom.status.classList.toggle("error", isError);
  dom.status.hidden = false;
}

function hideStatus() {
  dom.status.hidden = true;
}

async function loadJson(url) {
  const response = await fetch(url, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${url} → HTTP ${response.status}`);
  return response.json();
}

async function boot() {
  cacheDom();
  wireChrome();
  try {
    const index = await loadJson("data/polities.json");
    state.meta = index.meta;
    state.polities = index.polities || [];
    const series = await loadJson("data/series.json");
    for (const [key, intervals] of Object.entries(series)) state.series.set(key, intervals);
  } catch (error) {
    openApp();
    showStatus(
      `Dataset not built yet (${error.message}).<br>` +
        `<code>py pipeline/fetch_cliopatria.py &amp;&amp; py pipeline/build_site_data.py</code>`,
      true,
    );
    return;
  }

  const meta = state.meta || {};
  if (meta.attribution) dom["footer-credit"].textContent = meta.attribution;
  if (meta.counts) {
    const counts = meta.counts;
    const bits = [];
    if (counts.extents) bits.push(`${counts.extents.toLocaleString()} nations`);
    if (counts.cessions) bits.push(`${counts.cessions.toLocaleString()} cession entities`);
    bits.push(`${counts.records.toLocaleString()} records`);
    bits.push(`${meta.yearRange[0]} to ${meta.yearRange[1]}`);
    dom["list-meta"].textContent = bits.join(" · ");
  }

  renderAlpha();
  renderList("");
  wireEvents();
  hideStatus();
  renderPlates();

  const initial = decodeURIComponent(location.hash.slice(1));
  if (initial && state.polities.some((polity) => polity.key === initial)) {
    openApp();
    selectPolity(initial);
  } else if (new URLSearchParams(location.search).has("atlas")) {
    openApp();
  }
}

function geometryFor(item) {
  if (!state.shard) return null;
  const key = item.g || (state.selected ? state.selected.key : null);
  const bucket = key ? state.shard[key] : null;
  if (!bucket) return null;
  return bucket[item.i] || null;
}

function renderList(query) {
  const needle = query.trim().toLowerCase();
  const matches = state.polities.filter(
    (p) =>
      (state.filter === "all" || p.kind === state.filter) &&
      (!state.letter || initialOf(p.name) === state.letter) &&
      (!needle || p.name.toLowerCase().includes(needle)),
  );
  const list = dom["polity-list"];
  clear(list);

  if (!matches.length) {
    const li = document.createElement("li");
    li.className = "hint";
    li.textContent = "No match.";
    li.style.padding = "0.5rem";
    list.appendChild(li);
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const polity of matches.slice(0, LIST_LIMIT)) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.key = polity.key;
    if (state.selected && state.selected.key === polity.key) button.setAttribute("aria-current", "true");

    const name = document.createElement("span");
    name.className = "row-name";
    name.textContent = polity.name;

    const years = document.createElement("span");
    years.className = "row-years";
    years.textContent = `${polity.from} … ${polity.to}`;

    button.append(name, years);
    button.addEventListener("click", () => selectPolity(polity.key));
    li.appendChild(button);
    fragment.appendChild(li);
  }
  list.appendChild(fragment);

  if (matches.length > LIST_LIMIT) {
    const li = document.createElement("li");
    li.className = "hint";
    li.style.padding = "0.5rem";
    li.textContent = `Showing first ${LIST_LIMIT} of ${matches.length.toLocaleString()} matches — refine your search.`;
    list.appendChild(li);
  }
}

async function selectPolity(key) {
  const polity = state.polities.find((p) => p.key === key);
  if (!polity) return;
  stopPlay();
  state.selected = polity;
  if (location.hash.slice(1) !== encodeURIComponent(key)) {
    history.replaceState(null, "", `#${encodeURIComponent(key)}`);
  }

  if (!state.shardCache.has(polity.shard)) {
    try {
      const shard = await loadJson(`data/geom/${polity.shard}.json`);
      state.shardCache.set(polity.shard, shard);
    } catch (error) {
      state.shardCache.set(polity.shard, {});
    }
  }
  const shard = state.shardCache.get(polity.shard) || {};
  state.shard = shard;
  state.intervals = state.series.get(key) || [];

  dom.detail.hidden = false;
  dom["polity-name"].textContent = polity.name;
  dom["polity-meta"].textContent = describePolity(polity);

  dom.year.min = String(polity.from);
  dom.year.max = String(polity.to);
  const focus = focusYear(polity);
  dom.year.value = String(focus);

  for (const button of dom["polity-list"].querySelectorAll("button")) {
    if (button.dataset.key === key) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  }

  renderChart();
  renderMap();
  setYear(focus);
}

function focusYear(polity) {
  const known = state.intervals.filter((item) => item.area !== null);
  if (!known.length) return polity.from;
  if (polity.kind === "cession") {
    return known.reduce((best, item) => (item.to > best.to ? item : best), known[0]).to;
  }
  const peak = known.reduce((best, item) => (item.area > best.area ? item : best), known[0]);
  return Math.round((peak.from + peak.to) / 2);
}

function describePolity(polity) {
  const bits = [];
  if (polity.kind === "cession") {
    bits.push("US land cession record");
    bits.push(`${state.intervals.length} cession${state.intervals.length === 1 ? "" : "s"}`);
    if (polity.totalArea) bits.push(`${formatArea(polity.totalArea)} ceded in total`);
    bits.push("Royce 1899, digitised by USFS");
  } else {
    bits.push(polity.type === "RELATION" ? "composite relation" : "polity");
    bits.push(`${state.intervals.length} source record${state.intervals.length === 1 ? "" : "s"}`);
    if (polity.peakArea) bits.push(`peak ${formatArea(polity.peakArea)}`);
    if (polity.wikidata) bits.push(polity.wikidata);
  }
  return bits.join(" · ");
}

function currentArea(year) {
  if (state.selected && state.selected.kind === "cession") {
    let total = 0.0;
    let count = 0;
    let latest = null;
    for (const item of state.intervals) {
      if (item.area === null || item.to > year) continue;
      total += item.area;
      count += 1;
      if (!latest || item.to > latest.to) latest = item;
    }
    return { area: count ? total : null, count, latest };
  }
  const active = state.intervals.filter((item) => year >= item.from && year <= item.to && item.area !== null);
  if (!active.length) return { area: null, count: 0, latest: null };
  const latest = active.reduce((best, item) => (!best || item.area > best.area ? item : best), null);
  return { area: latest.area, count: active.length, latest };
}

function setYear(year) {
  state.year = year;
  dom.year.value = String(year);
  dom["year-label"].textContent = formatYear(year);

  const cession = state.selected && state.selected.kind === "cession";
  const { area, count, latest } = currentArea(year);
  dom["stat-area-label"].textContent = cession ? "Cumulative ceded" : "Area at year";
  dom["stat-share-label"].textContent = cession ? "Cessions to date" : "Share of world land";
  dom["stat-area"].textContent = formatArea(area);

  if (cession) {
    dom["stat-share"].textContent = count ? count.toLocaleString() : "—";
    dom["stat-window"].textContent = latest ? formatYear(latest.to) : "none yet";
    dom["stat-window-label"].textContent = "Latest cession";
  } else {
    dom["stat-share"].textContent = formatShare(area);
    dom["stat-window"].textContent = latest
      ? `${formatYear(latest.from)} – ${formatYear(latest.to)}${count > 1 ? ` · ${count} records` : ""}`
      : "no record";
    dom["stat-window-label"].textContent = "Record window";
  }

  updateMapVisibility();
  updateChartCursor();
}

function chartSegments() {
  const years = new Set();
  for (const item of state.intervals) {
    years.add(item.from);
    years.add(item.to);
  }
  const sorted = [...years].sort((a, b) => a - b);
  const segments = [];
  for (let i = 0; i < sorted.length; i += 1) {
    const x0 = sorted[i];
    const x1 = i + 1 < sorted.length ? sorted[i + 1] : x0;
    const probe = x1 > x0 ? Math.floor((x0 + x1) / 2) : x0;
    segments.push({ x0, x1, area: currentArea(probe).area });
  }
  return segments;
}

function renderChart() {
  const node = dom.chart;
  clear(node);
  const isCession = Boolean(state.selected && state.selected.kind === "cession");
  node.classList.toggle("is-cession", isCession);

  const width = node.clientWidth || 640;
  const height = 240;
  const margin = { top: 22, right: 18, bottom: 30, left: 66 };
  const plotWidth = Math.max(10, width - margin.left - margin.right);
  const plotHeight = height - margin.top - margin.bottom;
  node.setAttribute("width", width);
  node.setAttribute("height", height);
  node.setAttribute("viewBox", `0 0 ${width} ${height}`);

  const segments = chartSegments();
  const values = segments.map((seg) => seg.area).filter((area) => area !== null);
  const rawMax = Math.max(1, ...values);
  let yMax = rawMax;
  if (!state.logScale) {
    const rough = niceTicks(0, rawMax, 4);
    const roundStep = rough.length > 1 ? rough[1] - rough[0] : rawMax;
    yMax = Math.max(roundStep, Math.ceil(rawMax / roundStep) * roundStep);
  }
  const yMin = state.logScale ? Math.max(1, values.length ? Math.min(...values) : 1) : 0;

  let xMin = state.selected ? state.selected.from : 0;
  let xMax = state.selected ? state.selected.to : 1;
  for (const seg of segments) {
    xMin = Math.min(xMin, seg.x0);
    xMax = Math.max(xMax, seg.x1);
  }
  if (xMax <= xMin) xMax = xMin + 1;

  const sx = (year) => margin.left + ((year - xMin) / (xMax - xMin)) * plotWidth;
  const sy = (area) => {
    if (state.logScale) {
      const lo = Math.log10(yMin);
      const hi = Math.log10(yMax);
      return margin.top + plotHeight - ((Math.log10(Math.max(area, yMin)) - lo) / Math.max(1e-9, hi - lo)) * plotHeight;
    }
    return margin.top + plotHeight - (area / yMax) * plotHeight;
  };

  state.chart = { sx, sy, margin, plotWidth, plotHeight, width, height, xMin, xMax, yMax, yMin };

  const grid = svg("g", { class: "chart-grid chart-axis" });
  const yTicks = state.logScale ? logTicks(yMin, yMax) : niceTicks(0, yMax, 4);
  for (const tick of yTicks) {
    const y = sy(tick);
    grid.appendChild(svg("line", { x1: margin.left, x2: margin.left + plotWidth, y1: y, y2: y }));
    const label = svg("text", { x: margin.left - 9, y: y + 4, "text-anchor": "end" });
    label.textContent =
      tick >= 1e6 ? `${(tick / 1e6).toFixed(tick >= 1e7 ? 0 : 1)}M`
        : tick >= 1000 ? `${Math.round(tick / 1000)}k`
          : String(Math.round(tick));
    grid.appendChild(label);
  }
  for (const tick of niceTicks(xMin, xMax, 6)) {
    const x = sx(tick);
    grid.appendChild(svg("line", { x1: x, x2: x, y1: margin.top, y2: margin.top + plotHeight }));
    const label = svg("text", { x, y: height - 10, "text-anchor": "middle" });
    label.textContent = tick < 0 ? `${Math.abs(tick)} BCE` : `${tick}`;
    grid.appendChild(label);
  }
  node.appendChild(grid);

  const unit = svg("text", { x: margin.left - 9, y: 11, "text-anchor": "end", class: "chart-axis-title" });
  unit.textContent = "km²";
  node.appendChild(unit);

  const fillGroup = svg("g");
  const lineGroup = svg("g");
  const runs = [];
  let run = null;
  for (const seg of segments) {
    if (seg.area === null) { run = null; continue; }
    if (!run) { run = []; runs.push(run); }
    run.push(seg);
  }
  const base = sy(state.logScale ? yMin : 0);
  for (const runSegs of runs) {
    let d = `M${sx(runSegs[0].x0).toFixed(1)},${sy(runSegs[0].area).toFixed(1)}`;
    for (let i = 0; i < runSegs.length; i += 1) {
      const seg = runSegs[i];
      if (i > 0) d += `H${sx(seg.x0).toFixed(1)}V${sy(seg.area).toFixed(1)}`;
      d += `H${sx(seg.x1).toFixed(1)}`;
    }
    const first = runSegs[0];
    const last = runSegs[runSegs.length - 1];
    const close = `L${sx(last.x1).toFixed(1)},${base.toFixed(1)}L${sx(first.x0).toFixed(1)},${base.toFixed(1)}Z`;
    fillGroup.appendChild(svg("path", { class: "chart-fill", d: d + close }));
    lineGroup.appendChild(svg("path", { class: "chart-line", d }));
  }
  node.append(fillGroup, lineGroup);

  const cursor = svg("g", { id: "chart-cursor", class: "chart-cursor" });
  cursor.appendChild(svg("line", { x1: 0, x2: 0, y1: margin.top, y2: margin.top + plotHeight }));
  cursor.appendChild(svg("circle", { cx: 0, cy: 0, r: 3 }));
  node.appendChild(cursor);

  const hit = svg("rect", { x: margin.left, y: margin.top, width: plotWidth, height: plotHeight, fill: "transparent" });
  hit.addEventListener("pointermove", onChartPointerMove);
  hit.addEventListener("pointerleave", () => { dom["chart-tooltip"].hidden = true; });
  node.appendChild(hit);
}

function updateChartCursor() {
  const cursor = dom.chart.querySelector("#chart-cursor");
  if (!cursor || !state.chart) return;
  const { sx, sy } = state.chart;
  const { area } = currentArea(state.year);
  const x = sx(state.year);
  const line = cursor.querySelector("line");
  const dot = cursor.querySelector("circle");
  line.setAttribute("x1", x);
  line.setAttribute("x2", x);
  if (area === null) {
    dot.setAttribute("opacity", 0);
    return;
  }
  dot.setAttribute("opacity", 1);
  dot.setAttribute("cx", x);
  dot.setAttribute("cy", sy(area));
}

function onChartPointerMove(event) {
  if (!state.chart) return;
  const rect = dom.chart.getBoundingClientRect();
  const { sx, xMin, xMax, margin, plotWidth, width } = state.chart;
  const ratio = (event.clientX - rect.left - margin.left) / Math.max(1, plotWidth);
  const year = Math.round(xMin + Math.min(Math.max(ratio, 0), 1) * (xMax - xMin));
  const { area, count, latest } = currentArea(year);
  const tooltip = dom["chart-tooltip"];
  if (area === null) {
    tooltip.hidden = true;
    return;
  }
  const cession = Boolean(state.selected && state.selected.kind === "cession");
  tooltip.hidden = false;
  if (cession) {
    tooltip.innerHTML =
      `<strong>${formatYear(year)}</strong><br>ceded to date ${formatArea(area)}` +
      `<br>${count.toLocaleString()} cession${count === 1 ? "" : "s"}`;
  } else {
    tooltip.innerHTML =
      `<strong>${formatYear(year)}</strong><br>${formatArea(area)}` +
      (latest && latest.type === "RELATION" ? "<br>composite relation" : "");
  }
  tooltip.style.left = `${Math.min(Math.max(sx(year), 80), width - 80)}px`;
  tooltip.style.top = `${margin.top - 4}px`;
}

function eachPoint(geometry, visit) {
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  for (const polygon of polygons) {
    for (const ring of polygon) {
      for (const point of ring) visit(point[0], point[1]);
    }
  }
}

function geometryPath(geometry, project) {
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  const parts = [];
  for (const polygon of polygons) {
    for (const ring of polygon) {
      ring.forEach((point, index) => {
        const [x, y] = project(point[0], point[1]);
        parts.push(`${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`);
      });
      parts.push("Z");
    }
  }
  return parts.join("");
}

function geometryBounds(geometry) {
  let minLon = Infinity;
  let maxLon = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;
  eachPoint(geometry, (lon, lat) => {
    if (lon < minLon) minLon = lon;
    if (lon > maxLon) maxLon = lon;
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
  });
  return Number.isFinite(minLon) ? [minLon, minLat, maxLon, maxLat] : null;
}

function renderMap() {
  const node = dom.map;
  clear(node);
  const width = node.clientWidth || 640;
  const height = 340;
  node.setAttribute("width", width);
  node.setAttribute("height", height);
  node.setAttribute("viewBox", `0 0 ${width} ${height}`);

  const clipId = "map-clip";
  const defs = svg("defs");
  const clip = svg("clipPath", { id: clipId });
  clip.appendChild(svg("rect", { x: 0, y: 0, width, height }));
  defs.appendChild(clip);
  node.appendChild(defs);

  const clipped = svg("g", { "clip-path": `url(#${clipId})` });
  const cession = Boolean(state.selected && state.selected.kind === "cession");
  const group = svg("g", { id: "territories" });
  const toWorld = (lon, lat) => [lon, -lat];

  for (const item of state.intervals) {
    if (item.i === null) continue;
    const geometry = geometryFor(item);
    if (!geometry) continue;
    const d = geometryPath(geometry, toWorld);
    if (!d) continue;
    const path = svg("path", { d, class: "territory", "vector-effect": "non-scaling-stroke" });
    if (item.type === "RELATION") path.classList.add("is-relation");
    if (cession) path.classList.add("is-cession");
    path.dataset.from = String(item.from);
    path.dataset.to = String(item.to);
    path.bounds = geometryBounds(geometry);
    group.appendChild(path);
  }

  clipped.appendChild(group);
  node.appendChild(clipped);
  node.appendChild(svg("rect", { x: 0.5, y: 0.5, width: width - 1, height: height - 1, class: "map-frame" }));

  const empty = svg("text", { x: width / 2, y: height / 2, "text-anchor": "middle", class: "map-empty" });
  empty.textContent = "No record for this year";
  node.appendChild(empty);

  state.map = { group, width, height, pad: 20, empty };
  updateMapVisibility();
}

function fitMap(paths) {
  if (!state.map) return;
  const { group, width, height, pad } = state.map;
  let minLon = Infinity;
  let maxLon = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;
  for (const path of paths) {
    const bounds = path.bounds;
    if (!bounds) continue;
    minLon = Math.min(minLon, bounds[0]);
    minLat = Math.min(minLat, bounds[1]);
    maxLon = Math.max(maxLon, bounds[2]);
    maxLat = Math.max(maxLat, bounds[3]);
  }
  if (!Number.isFinite(minLon)) {
    group.removeAttribute("transform");
    return;
  }

  const midLat = (minLat + maxLat) / 2;
  const lonScale = Math.max(0.15, Math.cos((midLat * Math.PI) / 180));
  const spanX = Math.max(0.02, (maxLon - minLon) * lonScale);
  const spanY = Math.max(0.02, maxLat - minLat);
  const cap = Math.min(width, height) / 0.2;
  const scale = Math.min((width - 2 * pad) / spanX, (height - 2 * pad) / spanY, cap);
  const centerLon = (minLon + maxLon) / 2;
  const centerLat = (minLat + maxLat) / 2;
  const xScale = lonScale * scale;
  const tx = width / 2 - xScale * centerLon;
  const ty = height / 2 + scale * centerLat;
  group.setAttribute(
    "transform",
    `matrix(${xScale.toFixed(4)} 0 0 ${scale.toFixed(4)} ${tx.toFixed(2)} ${ty.toFixed(2)})`,
  );
}

function updateMapVisibility() {
  if (!state.map) return;
  const year = state.year;
  const cession = Boolean(state.selected && state.selected.kind === "cession");

  let latestTo = -Infinity;
  if (cession) {
    for (const item of state.intervals) if (item.to <= year) latestTo = Math.max(latestTo, item.to);
  }

  const shown = [];
  for (const path of dom.map.querySelectorAll("#territories path")) {
    const from = Number(path.dataset.from);
    const to = Number(path.dataset.to);
    if (cession) {
      const done = year >= to;
      path.style.display = state.showAll || done ? "" : "none";
      path.style.opacity = to === latestTo ? "1" : done ? "0.6" : "0.25";
      if (done) shown.push(path);
      continue;
    }
    const inside = year >= from && year <= to;
    path.style.display = state.showAll || inside ? "" : "none";
    path.style.opacity = inside ? "1" : "0.18";
    if (inside) shown.push(path);
  }

  if (state.showAll) {
    shown.length = 0;
    for (const path of dom.map.querySelectorAll("#territories path")) shown.push(path);
  }
  state.map.empty.style.display = shown.length ? "none" : "";
  fitMap(shown);
}

function startPlay() {
  if (state.playing || !state.selected) return;
  state.playing = true;
  dom.play.textContent = "❚❚";
  state.timer = window.setInterval(tick, 60);
}

function stopPlay() {
  state.playing = false;
  if (state.timer) window.clearInterval(state.timer);
  state.timer = null;
  dom.play.textContent = "▶";
}

function tick() {
  const polity = state.selected;
  if (!polity) return stopPlay();
  const span = polity.to - polity.from;
  const step = Math.max(1, Math.round(span / 400));
  const next = state.year + step > polity.to ? polity.from : state.year + step;
  setYear(next);
}

function openApp() {
  dom.landing.hidden = true;
  dom.app.hidden = false;
}

function showLanding() {
  dom.app.hidden = true;
  dom.landing.hidden = false;
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
}

function renderAlpha() {
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
  clear(dom.alpha);
  for (const letter of letters) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = letter;
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", () => {
      state.letter = state.letter === letter ? "" : letter;
      for (const other of dom.alpha.querySelectorAll("button")) {
        other.setAttribute("aria-pressed", String(other.textContent === state.letter));
      }
      renderList(dom.search.value);
    });
    dom.alpha.appendChild(button);
  }
}

function plateProjection(geometries) {
  let minLon = Infinity;
  let maxLon = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;
  for (const geometry of geometries) {
    eachPoint(geometry, (lon, lat) => {
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    });
  }
  if (!Number.isFinite(minLon)) return null;

  const width = 120;
  const height = 90;
  const pad = 6;
  const midLat = (minLat + maxLat) / 2;
  const lonScale = Math.max(0.15, Math.cos((midLat * Math.PI) / 180));
  const spanX = Math.max(0.05, (maxLon - minLon) * lonScale);
  const spanY = Math.max(0.05, maxLat - minLat);
  const scale = Math.min((width - 2 * pad) / spanX, (height - 2 * pad) / spanY);
  const centerLon = (minLon + maxLon) / 2;
  const centerLat = (minLat + maxLat) / 2;
  return (lon, lat) => [
    width / 2 + (lon - centerLon) * lonScale * scale,
    height / 2 - (lat - centerLat) * scale,
  ];
}

async function renderPlates() {
  const plates = [...document.querySelectorAll(".plate")];
  if (!plates.length) return;
  const anchor = state.polities.find((polity) => polity.key === "royce-all")
    || state.polities.find((polity) => polity.kind === "cession");
  if (!anchor) return;

  let shard = state.shardCache.get(anchor.shard);
  if (!shard) {
    try {
      shard = await loadJson(`data/geom/${anchor.shard}.json`);
      state.shardCache.set(anchor.shard, shard);
    } catch (error) {
      return;
    }
  }

  const all = state.series.get("royce-all") || [];
  const bucket = shard[all.length ? all[0].g : "royce-cessions"] || [];
  const picks = state.polities
    .filter((polity) => polity.kind === "cession" && polity.totalArea)
    .sort((a, b) => b.totalArea - a.totalArea)
    .slice(0, plates.length);

  picks.forEach((polity, index) => {
    const geometries = (state.series.get(polity.key) || [])
      .map((item) => bucket[item.i])
      .filter(Boolean);
    if (!geometries.length) return;

    const project = plateProjection(geometries);
    if (!project) return;

    const node = document.createElementNS(SVG_NS, "svg");
    node.setAttribute("viewBox", "0 0 120 90");
    node.setAttribute("aria-hidden", "true");
    for (const geometry of geometries) {
      const path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", geometryPath(geometry, project));
      path.setAttribute("fill", "currentColor");
      path.setAttribute("fill-opacity", "0.34");
      path.setAttribute("stroke", "currentColor");
      path.setAttribute("stroke-width", "0.4");
      node.appendChild(path);
    }

    const plate = plates[index];
    plate.textContent = "";
    plate.appendChild(node);
    plate.setAttribute("aria-label", polity.name);
    plate.dataset.key = polity.key;
  });

  for (const plate of dom.plates.querySelectorAll(".plate")) {
    plate.addEventListener("click", () => {
      if (!plate.dataset.key) return;
      openApp();
      selectPolity(plate.dataset.key);
    });
  }
}

function wireChrome() {
  dom.enter.addEventListener("click", openApp);
  dom["enter-link"].addEventListener("click", (event) => {
    event.preventDefault();
    openApp();
  });
  dom["back-link"].addEventListener("click", (event) => {
    event.preventDefault();
    showLanding();
  });
}

function wireEvents() {
  dom.search.addEventListener("input", (event) => renderList(event.target.value));
  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => {
      state.filter = tab.dataset.filter;
      for (const other of document.querySelectorAll(".tab")) {
        other.setAttribute("aria-pressed", String(other === tab));
      }
      renderList(dom.search.value);
    });
  }
  dom.play.addEventListener("click", () => (state.playing ? stopPlay() : startPlay()));
  dom.year.addEventListener("input", (event) => {
    stopPlay();
    setYear(Number(event.target.value));
  });
  dom["log-scale"].addEventListener("change", (event) => {
    state.logScale = event.target.checked;
    renderChart();
    updateChartCursor();
  });
  dom["show-all"].addEventListener("change", (event) => {
    state.showAll = event.target.checked;
    updateMapVisibility();
  });

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    if (resizeTimer) window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      if (!state.selected) return;
      renderChart();
      renderMap();
      updateChartCursor();
    }, 150);
  });
}

boot();
