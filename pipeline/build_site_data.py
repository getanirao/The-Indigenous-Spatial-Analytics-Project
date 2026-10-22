#!/usr/bin/env python3
"""Turn data/raw/cliopatria.geojson into the static dataset consumed by site/.

Outputs (all under --out, default site/data):

    polities.json      index: key, name, type, year span, peak area, shard id, meta block
    series.json        {key: [{from, to, area, type, i}]}
    geom/<shard>.json  {key: [<GeoJSON geometry>, ...]}, addressed by the `i` field above

Geometry is simplified with a pure-python Douglas-Peucker pass, so this needs no shapely,
pyproj, GDAL, or geopandas. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

EARTH_RADIUS_KM = 6371.0088
WORLD_LAND_KM2 = 148_940_000

DEFAULT_TOLERANCE = 0.08  # degrees; ~9 km at the equator
DEFAULT_CESSION_TOLERANCE = 0.01  # cessions are parcel-sized; 0.08 erases many of them
DEFAULT_PRECISION = 3

# This project looks at land after European contact, so the default window starts at 1492.
# Contact dates differ by region (Australia 1770, Aotearoa 1769, and so on); narrow the window
# per region rather than treating 1492 as universal. Records that straddle the cutoff are
# clamped, not dropped, so nothing that was still standing in 1492 disappears.
DEFAULT_MIN_YEAR = 1492
DEFAULT_MAX_YEAR: int | None = None

CESSION_GEOM_KEY = "royce-cessions"

FIELD_ALIASES = {
    "name": ("name", "polity", "title"),
    "from": ("fromyear", "from", "startyear", "start"),
    "to": ("toyear", "to", "endyear", "end"),
    "area": ("area", "areakm2", "area_km2", "surface"),
    "type": ("type", "politytype", "entitytype"),
    "wikipedia": ("wikipedia", "wikipediaurl", "wiki"),
    "wikidata": ("wikidata", "wikidataid", "qid"),
    "seshat": ("seshatid", "seshat", "seshatpolityid"),
    "memberof": ("memberof", "member"),
}


def log(message: str) -> None:
    print(f"[build] {message}", flush=True)


def normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def property_map(props: dict) -> dict:
    return {normalize_key(k): v for k, v in props.items()}


def pick(props: dict, field: str, default=None):
    for alias in FIELD_ALIASES[field]:
        value = props.get(normalize_key(alias))
        if value not in (None, ""):
            return value
    return default


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "unnamed"


def to_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def ring_area_km2(ring: list) -> float:
    """Spherical-excess area of a single linear ring, in km²."""
    if len(ring) < 3:
        return 0.0
    total = 0.0
    for i in range(len(ring) - 1):
        lon1, lat1 = math.radians(ring[i][0]), math.radians(ring[i][1])
        lon2, lat2 = math.radians(ring[i + 1][0]), math.radians(ring[i + 1][1])
        total += (lon2 - lon1) * (2 + math.sin(lat1) + math.sin(lat2))
    return abs(total) * EARTH_RADIUS_KM**2 / 2.0


def polygon_area_km2(polygon: list) -> float:
    if not polygon:
        return 0.0
    area = ring_area_km2(polygon[0])
    for hole in polygon[1:]:
        area -= ring_area_km2(hole)
    return max(area, 0.0)


def geometry_area_km2(geometry: dict | None) -> float | None:
    if not geometry:
        return None
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon":
        return polygon_area_km2(coords)
    if gtype == "MultiPolygon":
        return sum(polygon_area_km2(poly) for poly in coords)
    return None


def perpendicular_distance(point, start, end) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    if dx == 0 and dy == 0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(point[0] - (start[0] + t * dx), point[1] - (start[1] + t * dy))


def simplify_ring(points: list, tolerance: float) -> list:
    """Douglas-Peucker, iterative to avoid recursion limits on long rings."""
    if len(points) <= 3 or tolerance <= 0:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        farthest, index = 0.0, -1
        for i in range(first + 1, last):
            distance = perpendicular_distance(points[i], points[first], points[last])
            if distance > farthest:
                farthest, index = distance, i
        if farthest > tolerance and index > 0:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, k in zip(points, keep) if k]


def round_point(point, precision: int) -> list:
    return [round(float(point[0]), precision), round(float(point[1]), precision)]


def simplify_geometry(geometry: dict | None, tolerance: float, precision: int):
    if not geometry:
        return None

    def simplify_ring_safe(ring: list) -> list:
        simplified = simplify_ring(ring, tolerance)
        if len(simplified) < 4:
            # A coarse tolerance can erase a small cession entirely; keep the original ring
            # rather than dropping the feature.
            simplified = ring
        return [round_point(point, precision) for point in simplified]

    gtype = geometry.get("type")
    if gtype == "Polygon":
        rings = [simplify_ring_safe(ring) for ring in geometry["coordinates"]]
        rings = [ring for ring in rings if len(ring) >= 4]
        if not rings:
            return None
        return {"type": "Polygon", "coordinates": rings}
    if gtype == "MultiPolygon":
        polygons = []
        for polygon in geometry["coordinates"]:
            rings = [simplify_ring_safe(ring) for ring in polygon]
            rings = [ring for ring in rings if len(ring) >= 4]
            if rings:
                polygons.append(rings)
        if not polygons:
            return None
        return {"type": "MultiPolygon", "coordinates": polygons}
    return None


def shard_for(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:2]


def load_features(path: Path) -> list[dict]:
    log(f"reading {path} ({path.stat().st_size / 1e6:,.1f} MB)")
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("type") == "FeatureCollection":
        return payload.get("features", [])
    if payload.get("type") == "Feature":
        return [payload]
    raise SystemExit(f"Unsupported GeoJSON root type: {payload.get('type')!r}")


def resolve_keys(records: list[dict]) -> dict[str, str]:
    """Pick one stable key per source name so a polity's records do not fragment.

    Identifier-bearing records win; when a name appears with and without an identifier,
    the whole name is keyed by the identifier that most of its records carry.
    """
    per_name: dict[str, Counter] = defaultdict(Counter)
    for record in records:
        if not record.get("resolve", True):
            continue
        per_name[record["name"]][record["key"]] += 1
    resolved: dict[str, str] = {}
    for name, counter in per_name.items():
        resolved[name] = counter.most_common(1)[0][0]
    return resolved


def load_cessions(
    path: Path,
    tolerance: float,
    precision: int,
    min_year: int,
    max_year: int | None,
) -> tuple[list[dict], dict[str, list], int]:
    """Turn joined Royce/USFS cession polygons into records plus shared geometry.

    Every cession polygon is stored once under CESSION_GEOM_KEY. A cession jointly made by
    several nations is credited in full to each named nation; it is not divided between them,
    so per-nation totals are not a partition of the whole.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    seed: list = []
    records: list[dict] = []
    skipped = 0

    for feature in features:
        properties = feature.get("properties") or {}
        year = to_int(properties.get("year"))
        if year is None:
            skipped += 1
            continue
        if year < min_year or (max_year is not None and year > max_year):
            continue
        geometry = feature.get("geometry")
        simplified = simplify_geometry(geometry, tolerance, precision)
        area = geometry_area_km2(geometry)
        if simplified is None or not area:
            skipped += 1
            continue

        index = len(seed)
        seed.append(simplified)
        common = {
            "from": year,
            "to": year,
            "area": area,
            "type": "CESSION",
            "kind": "cession",
            "source": "royce",
            "i": index,
            "g": CESSION_GEOM_KEY,
            "resolve": False,
            "wikipedia": None,
            "wikidata": None,
            "seshat": None,
            "memberof": None,
            "geometry": None,
        }
        for tribe in properties.get("tribes") or []:
            tribe = str(tribe).strip()
            if tribe:
                records.append({**common, "name": tribe, "key": f"royce-{slugify(tribe)}"})
        records.append(
            {
                **common,
                "name": "United States — all recorded cessions",
                "key": "royce-all",
            }
        )

    return records, {CESSION_GEOM_KEY: seed}, skipped


def build(
    records: list[dict],
    seed_geometry: dict[str, list],
    tolerance: float,
    precision: int,
    report: bool,
) -> dict:
    name_for_key = resolve_keys(records)

    series: dict[str, list[dict]] = defaultdict(list)
    geometry: dict[str, list] = {key: list(value) for key, value in seed_geometry.items()}
    stats: dict[str, dict] = {}
    missing_area = 0

    for record in records:
        key = name_for_key[record["name"]] if record.get("resolve", True) else record["key"]
        geom_key = record.get("g") or key
        index = record.get("i")
        if index is None:
            geom = simplify_geometry(record["geometry"], tolerance, precision)
            if geom is not None:
                geometry.setdefault(geom_key, [])
                index = len(geometry[geom_key])
                geometry[geom_key].append(geom)

        area = record["area"]
        if area is None:
            area = geometry_area_km2(record.get("geometry"))
        if area is None and index is not None:
            area = geometry_area_km2(geometry[geom_key][index])
        if area is None or area <= 0:
            missing_area += 1
            area = None

        series[key].append(
            {
                "from": record["from"],
                "to": record["to"],
                "area": round(area, 1) if area is not None else None,
                "type": record["type"],
                "i": index,
                "g": geom_key,
            }
        )

        entry = stats.setdefault(
            key,
            {
                "name": record["name"],
                "type": record["type"],
                "kind": record.get("kind", "extent"),
                "source": record.get("source", "cliopatria"),
                "wikipedia": record["wikipedia"],
                "wikidata": record["wikidata"],
                "seshat": record["seshat"],
                "memberof": record["memberof"],
                "names": Counter(),
                "types": Counter(),
            },
        )
        entry["names"][record["name"]] += 1
        entry["types"][record["type"] or "UNKNOWN"] += 1
        for field in ("wikipedia", "wikidata", "seshat", "memberof"):
            if entry[field] is None and record[field] is not None:
                entry[field] = record[field]

    polities = []
    for key, intervals in series.items():
        intervals.sort(key=lambda item: (item["from"], item["to"]))
        entry = stats[key]
        known = [i["area"] for i in intervals if i["area"] is not None]
        geom_key = Counter(item["g"] for item in intervals).most_common(1)[0][0]
        polity = {
            "key": key,
            "name": entry["names"].most_common(1)[0][0],
            "type": entry["types"].most_common(1)[0][0],
            "kind": entry["kind"],
            "source": entry["source"],
            "from": min(i["from"] for i in intervals),
            "to": max(i["to"] for i in intervals),
            "peakArea": max(known) if known else None,
            "totalArea": round(sum(known), 1) if known else None,
            "records": len(intervals),
            "shard": shard_for(geom_key),
            "wikipedia": entry["wikipedia"],
            "wikidata": entry["wikidata"],
            "seshatId": entry["seshat"],
            "memberOf": entry["memberof"],
        }
        polities.append(polity)

    def sort_key(item: dict) -> tuple:
        if item["key"] == "royce-all":
            return ("", "")
        return (item["name"].casefold(), item["key"])

    polities.sort(key=sort_key)

    shards: dict[str, dict] = defaultdict(dict)
    for key, geoms in geometry.items():
        if geoms:
            shards[shard_for(key)][key] = geoms

    if report:
        with_area = sum(1 for p in polities if p["peakArea"])
        log(f"records={len(records)} polities={len(polities)} shards={len(shards)}")
        log(f"polities without usable area: {missing_area} records")
        log(f"polities with a peak area: {with_area}/{len(polities)}")
        for kind in ("extent", "cession"):
            subset = [p for p in polities if p["kind"] == kind]
            log(f"  {kind}: {len(subset)} entities")
        top = [p for p in polities if p["kind"] == "extent"][:3] + [
            p for p in polities if p["kind"] == "cession"
        ][:3]
        for polity in top:
            log(
                f"  {polity['peakArea'] or 0:>12,.0f} km²  {polity['name']} "
                f"({polity['from']}..{polity['to']}) [{polity['kind']}]"
            )

    return {"polities": polities, "series": series, "shards": shards, "missing_area": missing_area}


def write_outputs(out_dir: Path, built: dict, meta: dict, pretty: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    geom_dir = out_dir / "geom"
    geom_dir.mkdir(parents=True, exist_ok=True)

    def dump(path: Path, payload) -> None:
        with path.open("w", encoding="utf-8") as fh:
            if pretty:
                json.dump(payload, fh, ensure_ascii=False, indent=1)
            else:
                json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        log(f"wrote {path} ({path.stat().st_size / 1e6:,.2f} MB)")

    dump(out_dir / "polities.json", {"meta": meta, "polities": built["polities"]})
    dump(out_dir / "series.json", built["series"])
    for shard, payload in sorted(built["shards"].items()):
        dump(geom_dir / f"{shard}.json", payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/raw/cliopatria.geojson")
    parser.add_argument("--out", default="site/data")
    parser.add_argument("--min-year", type=int, default=DEFAULT_MIN_YEAR,
                        help="window start; --min-year -4000 restores the full deep-time series")
    parser.add_argument("--max-year", type=int, default=DEFAULT_MAX_YEAR,
                        help="window end (default: no limit)")
    parser.add_argument("--cessions", default="data/raw/tribal_cessions.geojson",
                        help="joined Royce/USFS cession GeoJSON; skipped if absent")
    parser.add_argument("--no-cessions", action="store_true", help="ignore the cession layer")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                        help="simplification tolerance in degrees (0 disables)")
    parser.add_argument("--cession-tolerance", type=float, default=DEFAULT_CESSION_TOLERANCE,
                        help="tolerance for cession polygons, which are much smaller")
    parser.add_argument("--precision", type=int, default=DEFAULT_PRECISION,
                        help="decimal places kept for coordinates")
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    parser.add_argument("--report", action="store_true", help="print build statistics")
    args = parser.parse_args(argv)

    source = Path(args.input)
    if not source.exists():
        raise SystemExit(
            f"{source} not found. Run pipeline/fetch_cliopatria.py first, or pass --input."
        )

    raw_records = []
    skipped = 0
    windowed_out = 0
    for feature in load_features(source):
        props = property_map(feature.get("properties") or {})
        name = pick(props, "name")
        start = to_int(pick(props, "from"))
        end = to_int(pick(props, "to"))
        if not name or start is None or end is None:
            skipped += 1
            continue
        if end < start:
            start, end = end, start

        if args.max_year is not None and start > args.max_year:
            windowed_out += 1
            continue
        if end < args.min_year:
            windowed_out += 1
            continue
        start = max(start, args.min_year)
        if args.max_year is not None:
            end = min(end, args.max_year)
        if end < start:
            windowed_out += 1
            continue

        wikidata = pick(props, "wikidata")
        seshat = pick(props, "seshat")
        identifier = None
        if wikidata:
            identifier = slugify(wikidata)
        elif seshat:
            identifier = slugify(f"seshat-{seshat}")
        raw_records.append(
            {
                "name": str(name).strip(),
                "from": start,
                "to": end,
                "area": _as_float(pick(props, "area")),
                "type": pick(props, "type", "POLITY"),
                "wikipedia": pick(props, "wikipedia"),
                "wikidata": wikidata,
                "seshat": seshat,
                "memberof": pick(props, "memberof"),
                "geometry": feature.get("geometry"),
                "key": identifier or slugify(name),
            }
        )
    if skipped:
        log(f"skipped {skipped} features without a name or year range")
    if windowed_out:
        log(f"excluded {windowed_out} features outside the {args.min_year}..{args.max_year} window")

    cession_records: list[dict] = []
    cession_seed: dict[str, list] = {}
    cessions_path = Path(args.cessions)
    if not args.no_cessions and cessions_path.exists():
        cession_records, cession_seed, cession_skipped = load_cessions(
            cessions_path, args.cession_tolerance, args.precision, args.min_year, args.max_year
        )
        log(f"cessions: {len(cession_seed.get(CESSION_GEOM_KEY, []))} polygons, "
            f"{len(cession_records)} nation-cession links")
        if cession_skipped:
            log(f"cessions: skipped {cession_skipped} polygons without a date or area")
        raw_records.extend(cession_records)
    elif not args.no_cessions:
        log(f"no cession layer at {cessions_path} (run pipeline/fetch_tribal_cessions.py)")

    if not raw_records:
        raise SystemExit(
            f"No features fall inside the {args.min_year}..{args.max_year} window. "
            f"Try a wider window, e.g. --min-year -4000."
        )

    built = build(raw_records, cession_seed, args.tolerance, args.precision, args.report)

    sources = [
        {
            "name": "Cliopatria (Seshat: Global History Databank)",
            "doi": "10.5281/zenodo.20274630",
            "record": "20274630",
            "version": "v0.2.0",
            "license": "CC BY 4.0",
            "kind": "extent",
        },
    ]
    credit_extent = (
        "Data: Bennett, J., Mutch, E., & Chalstrey, E. (2024). Cliopatria — A geospatial "
        "database of world-wide political entities from 3400BCE to 2024CE. Zenodo. "
        "https://doi.org/10.5281/zenodo.20274630 (CC BY 4.0). "
    )
    figure_credit = "Visualization: The Indigenous Spatial Analytics Project (CC BY-SA 4.0)."
    credit_cession = (
        "Data: Royce, C. C. (1899). Indian Land Cessions in the United States, digitised by the "
        "U.S. Forest Service and Claudio Saunt (public domain, U.S. Government work). "
    )
    if cession_records:
        sources.append(
            {
                "name": "Tribal Ceded Lands (U.S. Forest Service)",
                "description": (
                    "Royce, C. C. Indian Land Cessions in the United States (1899), digitised "
                    "by the U.S. Forest Service with Claudio Saunt."
                ),
                "url": (
                    "https://apps.fs.usda.gov/arcx/rest/services/EDW/"
                    "EDW_TribalCessionLands_01/MapServer"
                ),
                "license": "Public domain (U.S. Government work)",
                "kind": "cession",
            }
        )
        attribution = credit_extent + credit_cession + figure_credit
    else:
        attribution = credit_extent + figure_credit

    years = [r["from"] for r in raw_records] + [r["to"] for r in raw_records]
    meta = {
        "title": "Nations' Land Over Time",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": {
            "from": args.min_year,
            "to": args.max_year,
            "note": (
                "Records overlapping this window are kept and clamped to it, so polities that "
                "predate European contact still appear for the years they were still standing. "
                "1492 is a European framing: contact dates differ by region."
            ),
        },
        "source": sources[0],
        "sources": sources,
        "attribution": attribution,
        "attributions": {
            "extent": credit_extent + figure_credit,
            "cession": (credit_cession + figure_credit) if cession_records else None,
        },
        "license": "CC BY-SA 4.0",
        "worldLandKm2": WORLD_LAND_KM2,
        "yearRange": [min(years), max(years)] if years else [0, 0],
        "counts": {
            "records": len(raw_records),
            "polities": len(built["polities"]),
            "shards": len(built["shards"]),
            "extents": sum(1 for p in built["polities"] if p["kind"] == "extent"),
            "cessions": sum(1 for p in built["polities"] if p["kind"] == "cession"),
            "cessionRecords": len(cession_records),
        },
        "simplification": {
            "toleranceDegrees": args.tolerance,
            "precision": args.precision,
        },
    }
    write_outputs(Path(args.out), built, meta, args.pretty)
    return 0


def _as_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


if __name__ == "__main__":
    sys.exit(main())
