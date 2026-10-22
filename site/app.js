// Static viewer for the "Native Land Cessions" atlas.
// No build step, no CDN, no map tiles: hand-rolled SVG only.

const SVG_NS = "http://www.w3.org/2000/svg";
const LIST_LIMIT = 2000;

const state = {
  meta: null,
  polities: [],
  series: new Map(),
  shardCache: new Map(),
  selected: null,
  shard: null,
  intervals: [],
  letter: "",
  year: 0,
  playing: false,
  timer: null,
  showAll: false,
  map: null,
  terrain: {},
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

function initialOf(name) {
  const match = name.match(/[a-z]/i);
  return match ? match[0].toUpperCase() : "#";
}

function cacheDom() {
  const ids = [
    "landing", "app", "enter", "enter-link", "back-link", "alpha", "plates",
    "search", "list-meta", "polity-list", "index-view", "detail-view", "back-to-index",
    "polity-name", "polity-meta", "stat-area", "stat-share", "stat-window",
    "map", "map-note", "cession-rows", "play", "year", "year-label", "show-all",
    "footer-credit",
  ];
  for (const id of ids) dom[id] = document.getElementById(id);
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
    try {
      state.terrain = await loadJson("data/terrain.json");
    } catch (error) {
      state.terrain = {};
    }
  } catch (error) {
    openApp();
    showError(error);
    return;
  }

  const meta = state.meta || {};
  if (meta.attribution) dom["footer-credit"].textContent = meta.attribution;
  if (meta.counts) {
    const counts = meta.counts;
    const bits = [];
    if (counts.polities) bits.push(`${(counts.polities - 1).toLocaleString()} nations`);
    if (counts.polygons) bits.push(`${counts.polygons.toLocaleString()} cession polygons`);
    bits.push(`${meta.yearRange[0]} to ${meta.yearRange[1]}`);
    dom["list-meta"].textContent = bits.join(" · ");
  }

  renderAlpha();
  renderList("");
  wireEvents();
  renderPlates();

  const initial = decodeURIComponent(location.hash.slice(1));
  if (initial && state.polities.some((polity) => polity.key === initial)) {
    openApp();
    selectPolity(initial);
  } else if (new URLSearchParams(location.search).has("atlas")) {
    openApp();
  }
}

function showError(error) {
  const list = dom["polity-list"];
  clear(list);
  const li = document.createElement("li");
  li.className = "hint";
  li.textContent = `Dataset not built yet (${error.message}).`;
  list.appendChild(li);
}

function renderList(query) {
  const needle = query.trim().toLowerCase();
  const matches = state.polities.filter(
    (p) =>
      (!state.letter || initialOf(p.name) === state.letter) &&
      (!needle || p.name.toLowerCase().includes(needle)),
  );
  const list = dom["polity-list"];
  clear(list);

  if (!matches.length) {
    const li = document.createElement("li");
    li.className = "hint";
    li.textContent = "No match.";
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
  state.shard = state.shardCache.get(polity.shard) || {};
  state.intervals = state.series.get(key) || [];

  dom["index-view"].hidden = true;
  dom["detail-view"].hidden = false;
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

  renderCessionTable();
  renderMap();
  setYear(focus);
  window.scrollTo({ top: 0 });
}

function showIndex() {
  dom["detail-view"].hidden = true;
  dom["index-view"].hidden = false;
  state.selected = null;
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
}

function focusYear(polity) {
  const known = state.intervals.filter((item) => item.area !== null);
  if (!known.length) return polity.from;
  return known.reduce((best, item) => (item.to > best.to ? item : best), known[0]).to;
}

function describePolity(polity) {
  const bits = [
    `${state.intervals.length} cession${state.intervals.length === 1 ? "" : "s"} on record`,
  ];
  if (polity.totalArea) bits.push(`${formatArea(polity.totalArea)} ceded in total`);
  bits.push("Royce 1899, digitised by the U.S. Forest Service");
  return bits.join(" · ");
}

function currentArea(year) {
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

function setYear(year) {
  state.year = year;
  dom.year.value = String(year);
  dom["year-label"].textContent = formatYear(year);

  const { area, count, latest } = currentArea(year);
  dom["stat-area"].textContent = formatArea(area);
  dom["stat-share"].textContent = count ? count.toLocaleString() : "—";
  dom["stat-window"].textContent = latest ? formatYear(latest.to) : "none yet";

  updateMapVisibility();
}

function renderCessionTable() {
  const body = dom["cession-rows"];
  clear(body);
  const rows = [...state.intervals].sort((a, b) => a.to - b.to);
  for (const item of rows) {
    const tr = document.createElement("tr");
    const year = document.createElement("td");
    year.className = "cell-year";
    year.textContent = formatYear(item.to);
    const area = document.createElement("td");
    area.className = "cell-area";
    area.textContent = formatArea(item.area);
    const states = document.createElement("td");
    states.className = "cell-states";
    states.textContent = (item.s || []).join(", ") || "—";
    tr.append(year, area, states);
    body.appendChild(tr);
  }
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

function stateOutlines() {
  const bucket = state.shard ? state.shard["us-states"] : null;
  return Array.isArray(bucket) ? bucket : [];
}

function renderMap() {
  const node = dom.map;
  clear(node);
  const width = node.clientWidth || 900;
  const height = Math.max(360, Math.min(560, Math.round(width * 0.52)));
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
  const toWorld = (lon, lat) => [lon, -lat];

  const relief = svg("g", { class: "map-relief" });
  for (const entry of state.terrain[state.selected ? state.selected.key : ""] || []) {
    const image = svg("image", {
      x: entry.lon0,
      y: -entry.lat1,
      width: entry.lon1 - entry.lon0,
      height: entry.lat1 - entry.lat0,
      preserveAspectRatio: "none",
      href: `data/${entry.file}`,
    });
    relief.appendChild(image);
  }
  clipped.appendChild(relief);

  const stateGroup = svg("g", { class: "map-states" });
  for (const entry of stateOutlines()) {
    const path = svg("path", { d: geometryPath(entry.geometry, toWorld), class: "state-outline" });
    path.dataset.name = entry.name;
    path.bounds = geometryBounds(entry.geometry);
    stateGroup.appendChild(path);
  }
  clipped.appendChild(stateGroup);

  const group = svg("g", { id: "territories" });
  for (const item of state.intervals) {
    if (item.i === null) continue;
    const geometry = (state.shard[item.g] || [])[item.i];
    if (!geometry) continue;
    const path = svg("path", { d: geometryPath(geometry, toWorld), class: "cession-outline" });
    path.dataset.to = String(item.to);
    path.dataset.states = (item.s || []).join("|");
    path.bounds = geometryBounds(geometry);
    group.appendChild(path);
  }
  clipped.appendChild(group);
  node.appendChild(clipped);

  const labels = svg("g", { class: "map-labels" });
  node.appendChild(labels);

  node.appendChild(svg("rect", { x: 0.5, y: 0.5, width: width - 1, height: height - 1, class: "map-frame" }));

  state.map = { group, stateGroup, relief, labels, width, height, pad: 26 };
  updateMapVisibility();
}

function fitMap(visible) {
  if (!state.map) return;
  const { group, stateGroup, relief, labels, width, height, pad } = state.map;
  let minLon = Infinity;
  let maxLon = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;

  const include = (bounds) => {
    if (!bounds) return;
    minLon = Math.min(minLon, bounds[0]);
    minLat = Math.min(minLat, bounds[1]);
    maxLon = Math.max(maxLon, bounds[2]);
    maxLat = Math.max(maxLat, bounds[3]);
  };

  for (const path of visible) include(path.bounds);

  const touched = new Set();
  for (const path of visible) {
    for (const name of (path.dataset.states || "").split("|")) if (name) touched.add(name);
  }

  if (!Number.isFinite(minLon)) {
    group.removeAttribute("transform");
    stateGroup.removeAttribute("transform");
    relief.removeAttribute("transform");
    return;
  }

  const midLat = (minLat + maxLat) / 2;
  const lonScale = Math.max(0.15, Math.cos((midLat * Math.PI) / 180));
  const spanX = Math.max(1.2, (maxLon - minLon) * lonScale);
  const spanY = Math.max(0.9, maxLat - minLat);
  const cap = Math.min(width, height) / 0.12;
  const scale = Math.min((width - 2 * pad) / spanX, (height - 2 * pad) / spanY, cap);
  const centerLon = (minLon + maxLon) / 2;
  const centerLat = (minLat + maxLat) / 2;
  const xScale = lonScale * scale;
  const tx = width / 2 - xScale * centerLon;
  const ty = height / 2 + scale * centerLat;
  const transform = `matrix(${xScale.toFixed(4)} 0 0 ${scale.toFixed(4)} ${tx.toFixed(2)} ${ty.toFixed(2)})`;
  group.setAttribute("transform", transform);
  stateGroup.setAttribute("transform", transform);
  relief.setAttribute("transform", transform);

  clear(labels);
  for (const path of stateGroup.querySelectorAll("path")) {
    if (!touched.has(path.dataset.name)) continue;
    const bounds = path.bounds;
    if (!bounds) continue;
    const x = xScale * ((bounds[0] + bounds[2]) / 2) + tx;
    const y = -scale * ((bounds[1] + bounds[3]) / 2) + ty;
    if (x < 12 || x > width - 12 || y < 12 || y > height - 12) continue;
    const label = svg("text", { x, y, "text-anchor": "middle", class: "state-label" });
    label.textContent = path.dataset.name.toUpperCase();
    labels.appendChild(label);
  }
}

function updateMapVisibility() {
  if (!state.map) return;
  const year = state.year;
  let latestTo = -Infinity;
  for (const item of state.intervals) if (item.to <= year) latestTo = Math.max(latestTo, item.to);

  const shown = [];
  for (const path of state.map.group.querySelectorAll("path")) {
    const to = Number(path.dataset.to);
    const done = year >= to;
    path.style.display = state.showAll || done ? "" : "none";
    path.style.opacity = to === latestTo ? "1" : done ? "0.85" : "0.4";
    if (done) shown.push(path);
  }

  if (state.showAll) {
    shown.length = 0;
    for (const path of state.map.group.querySelectorAll("path")) shown.push(path);
  }
  fitMap(shown);

  const count = shown.length;
  const states = new Set();
  for (const path of shown) {
    for (const name of (path.dataset.states || "").split("|")) if (name) states.add(name);
  }
  const list = [...states].sort();
  dom["map-note"].textContent = state.showAll
    ? `${count} cession${count === 1 ? "" : "s"} on record.`
    : `Ceded by ${formatYear(year)}: ${count} cession${count === 1 ? "" : "s"}, falling in `
      + `${list.length ? list.join(", ") : "no mapped state"}.`;
}

function startPlay() {
  if (state.playing || !state.selected) return;
  state.playing = true;
  dom.play.textContent = "❚❚";
  state.timer = window.setInterval(tick, 80);
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
  const step = Math.max(1, Math.round(span / 300));
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

function footprintOf(geometries) {
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
  return {
    lon: (minLon + maxLon) / 2,
    lat: (minLat + maxLat) / 2,
    spanX: maxLon - minLon,
    spanY: maxLat - minLat,
  };
}

function sameFootprint(first, second) {
  return (
    Math.abs(first.lon - second.lon) < 0.6 &&
    Math.abs(first.lat - second.lat) < 0.6 &&
    Math.abs(first.spanX - second.spanX) < 1.2 &&
    Math.abs(first.spanY - second.spanY) < 1.2
  );
}

async function renderPlates() {
  const plates = [...document.querySelectorAll(".plate")];
  if (!plates.length) return;
  const anchor = state.polities.find((polity) => polity.key === "royce-all");
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
    .filter((polity) => polity.key !== "royce-all" && polity.totalArea)
    .sort((a, b) => b.totalArea - a.totalArea);

  const chosen = [];
  for (const polity of picks) {
    const geometries = (state.series.get(polity.key) || [])
      .map((item) => bucket[item.i])
      .filter(Boolean);
    if (!geometries.length) continue;
    const footprint = footprintOf(geometries);
    if (chosen.some((entry) => sameFootprint(entry.footprint, footprint))) continue;
    chosen.push({ polity, geometries, footprint });
    if (chosen.length === plates.length) break;
  }

  chosen.forEach((entry, index) => {
    const project = plateProjection(entry.geometries);
    if (!project) return;

    const node = document.createElementNS(SVG_NS, "svg");
    node.setAttribute("viewBox", "0 0 120 90");
    node.setAttribute("aria-hidden", "true");
    for (const geometry of entry.geometries) {
      const path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", geometryPath(geometry, project));
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "currentColor");
      path.setAttribute("stroke-width", "0.5");
      node.appendChild(path);
    }

    const plate = plates[index];
    plate.textContent = "";
    plate.appendChild(node);
    plate.setAttribute("aria-label", entry.polity.name);
    plate.dataset.key = entry.polity.key;
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
  dom["back-to-index"].addEventListener("click", (event) => {
    event.preventDefault();
    showIndex();
  });
}

function wireEvents() {
  dom.search.addEventListener("input", (event) => renderList(event.target.value));
  dom.play.addEventListener("click", () => (state.playing ? stopPlay() : startPlay()));
  dom.year.addEventListener("input", (event) => {
    stopPlay();
    setYear(Number(event.target.value));
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
      renderMap();
      setYear(state.year);
    }, 150);
  });
}

boot();
