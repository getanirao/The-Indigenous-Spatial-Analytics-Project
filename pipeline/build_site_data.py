#!/usr/bin/env python3
"""Build the static dataset consumed by site/ from the Royce/USFS cession layer.

Outputs (all under --out, default site/data):

    polities.json      index: key, name, year span, total ceded, shard id, meta block
    series.json        {key: [{from, to, area, type, i, g}]}
    geom/<shard>.json  {key: [<GeoJSON geometry>, ...]}, addressed by the `i` field above

Every cession polygon is stored once under CESSION_GEOM_KEY and referenced by each nation
that signed it, so joint cessions are credited in full to each signatory and per-nation
totals do not partition the national total.

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

DEFAULT_CESSION_TOLERANCE = 0.01  # cessions are parcel-sized; 0.08 erases many of them
DEFAULT_PRECISION = 3

CESSION_GEOM_KEY = "royce-cessions"
AGGREGATE_KEY = "royce-all"
AGGREGATE_NAME = "United States — all recorded cessions"


def log(message: str) -> None:
    print(f"[build] {message}", flush=True)


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


def load_cessions(
    path: Path,
    tolerance: float,
    precision: int,
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
            "wikipedia": None,
            "wikidata": None,
            "seshat": None,
            "memberof": None,
        }
        for tribe in properties.get("tribes") or []:
            tribe = str(tribe).strip()
            if tribe:
                records.append({**common, "name": tribe, "key": f"royce-{slugify(tribe)}"})
        records.append({**common, "name": AGGREGATE_NAME, "key": AGGREGATE_KEY})

    return records, {CESSION_GEOM_KEY: seed}, skipped


def build(records: list[dict], seed_geometry: dict[str, list], report: bool) -> dict:
    series: dict[str, list[dict]] = defaultdict(list)
    geometry: dict[str, list] = {key: list(value) for key, value in seed_geometry.items()}
    stats: dict[str, dict] = {}

    for record in records:
        key = record["key"]
        series[key].append(
            {
                "from": record["from"],
                "to": record["to"],
                "area": round(record["area"], 1) if record["area"] is not None else None,
                "type": record["type"],
                "i": record["i"],
                "g": record["g"],
            }
        )
        entry = stats.setdefault(key, {"names": Counter()})
        entry["names"][record["name"]] += 1

    polities = []
    for key, intervals in series.items():
        intervals.sort(key=lambda item: (item["from"], item["to"]))
        known = [i["area"] for i in intervals if i["area"] is not None]
        geom_key = Counter(item["g"] for item in intervals).most_common(1)[0][0]
        polities.append(
            {
                "key": key,
                "name": stats[key]["names"].most_common(1)[0][0],
                "type": "CESSION",
                "kind": "cession",
                "source": "royce",
                "from": min(i["from"] for i in intervals),
                "to": max(i["to"] for i in intervals),
                "totalArea": round(sum(known), 1) if known else None,
                "peakArea": max(known) if known else None,
                "records": len(intervals),
                "shard": shard_for(geom_key),
                "wikipedia": None,
                "wikidata": None,
                "seshatId": None,
                "memberOf": None,
            }
        )

    def sort_key(item: dict) -> tuple:
        if item["key"] == AGGREGATE_KEY:
            return ("", "")
        return (item["name"].casefold(), item["key"])

    polities.sort(key=sort_key)

    shards: dict[str, dict] = defaultdict(dict)
    for key, geoms in geometry.items():
        if geoms:
            shards[shard_for(key)][key] = geoms

    if report:
        log(f"records={len(records)} nations={len(polities)} shards={len(shards)}")
        log(f"cession polygons: {len(geometry.get(CESSION_GEOM_KEY, []))}")
        for polity in polities[:5]:
            log(
                f"  {polity['totalArea'] or 0:>12,.0f} km²  {polity['name']} "
                f"({polity['from']}..{polity['to']}, {polity['records']} records)"
            )

    return {"polities": polities, "series": series, "shards": shards}


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
    parser.add_argument("--cessions", default="data/raw/tribal_cessions.geojson",
                        help="joined Royce/USFS cession GeoJSON")
    parser.add_argument("--out", default="site/data")
    parser.add_argument("--cession-tolerance", type=float, default=DEFAULT_CESSION_TOLERANCE,
                        help="tolerance for cession polygons, which are much smaller")
    parser.add_argument("--precision", type=int, default=DEFAULT_PRECISION,
                        help="decimal places kept for coordinates")
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    parser.add_argument("--report", action="store_true", help="print build statistics")
    args = parser.parse_args(argv)

    cessions_path = Path(args.cessions)
    if not cessions_path.exists():
        raise SystemExit(
            f"{cessions_path} not found. Run pipeline/fetch_tribal_cessions.py first."
        )

    records, seed, skipped = load_cessions(
        cessions_path, args.cession_tolerance, args.precision
    )
    log(f"cessions: {len(seed.get(CESSION_GEOM_KEY, []))} polygons, "
        f"{len(records)} nation-cession links")
    if skipped:
        log(f"cessions: skipped {skipped} polygons without a date or area")
    if not records:
        raise SystemExit(f"No usable cession features in {cessions_path}.")

    built = build(records, seed, args.report)

    source = {
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
    attribution = (
        "Data: Royce, C. C. (1899). Indian Land Cessions in the United States, digitised by "
        "the U.S. Forest Service and Claudio Saunt (public domain, U.S. Government work). "
        "Visualization: The Indigenous Spatial Analytics Project (CC BY-SA 4.0)."
    )

    years = [r["from"] for r in records] + [r["to"] for r in records]
    meta = {
        "title": "Native Land Cessions",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "sources": [source],
        "attribution": attribution,
        "license": "CC BY-SA 4.0",
        "yearRange": [min(years), max(years)] if years else [0, 0],
        "counts": {
            "records": len(records),
            "polities": len(built["polities"]),
            "shards": len(built["shards"]),
            "polygons": len(seed.get(CESSION_GEOM_KEY, [])),
        },
        "simplification": {
            "toleranceDegrees": args.cession_tolerance,
            "precision": args.precision,
        },
    }
    write_outputs(Path(args.out), built, meta, args.pretty)
    return 0


if __name__ == "__main__":
    sys.exit(main())
