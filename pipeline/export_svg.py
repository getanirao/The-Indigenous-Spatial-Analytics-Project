#!/usr/bin/env python3
"""Render standalone, Commons-ready SVGs from the built dataset in site/data/.

Output has no scripts, no external references, and no embedded raster, with `<title>`,
`<desc>` and a metadata block carrying source, version and license. Standard library only.

Examples
--------
    py pipeline/export_svg.py --key roman-empire --year 117
    py pipeline/export_svg.py --top 12
    py pipeline/export_svg.py --key mongol-empire --out dist/svg
    py pipeline/export_svg.py --list 50
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

CHART_WIDTH = 960
CHART_HEIGHT = 520
MAP_WIDTH = 960
INK = "#1c1b18"
MUTED = "#6b655b"
CESSION = "#8a3324"
GRID = "#e6e1d6"
AXIS = "#cbc5b8"
STATE_LINE = "#b9b2a3"


def log(message: str) -> None:
    print(f"[export] {message}", flush=True)


def format_year(year: int) -> str:
    return f"{abs(year)} BCE" if year < 0 else f"{year} CE"


def format_area(area: float | None) -> str:
    return "unknown" if area is None else f"{area:,.0f} km²"


def nice_ticks(minimum: float, maximum: float, count: int) -> list[float]:
    if not maximum > minimum:
        return [minimum]
    raw = (maximum - minimum) / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = magnitude * 10
    for multiple in (1, 2, 2.5, 5, 10):
        candidate = multiple * magnitude
        if (maximum - minimum) / candidate <= count:
            step = candidate
            break
    ticks = []
    value = math.floor(minimum / step) * step
    while value <= maximum + step * 1e-6:
        if value >= minimum - step * 1e-6:
            ticks.append(value)
        value += step
    return ticks or [minimum, maximum]


def short_number(value: float) -> str:
    if value >= 1e6:
        return f"{value / 1e6:.1f}M"
    if value >= 1e3:
        return f"{value / 1e3:.0f}k"
    return f"{value:.0f}"


def source_for(meta: dict) -> dict:
    return {
        "name": meta["source"]["name"],
        "version": "Royce 1899 digitisation",
        "doi": "",
        "license": meta["source"]["license"],
        "attribution": meta["attribution"],
    }


def svg_document(
    meta: dict,
    source: dict,
    title: str,
    description: str,
    width: int,
    height: int,
    body: list[str],
) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f"<title>{escape(title)}</title>",
        f"<desc>{escape(description)}</desc>",
        "<metadata>",
        f"  <source>{escape(source['name'])}</source>",
        f"  <sourceVersion>{escape(source['version'])}</sourceVersion>",
    ]
    if source.get("doi"):
        lines.append(f"  <sourceDoi>https://doi.org/{escape(source['doi'])}</sourceDoi>")
    lines.extend(
        [
            f"  <sourceLicense>{escape(source['license'])}</sourceLicense>",
            f"  <figureLicense>{escape(meta['license'])}</figureLicense>",
            f"  <generated>{escape(meta['generated'])}</generated>",
            f"  <attribution>{escape(source['attribution'])}</attribution>",
            "</metadata>",
            f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
            *body,
            f'<text x="{width - 16}" y="{height - 12}" text-anchor="end" font-family="sans-serif" '
            f'font-size="12" fill="{MUTED}">Data: {escape(source["name"])} '
            f'({escape(source["license"])}) · Figure: {escape(meta["license"])} · '
            f"The Indigenous Spatial Analytics Project</text>",
            "</svg>",
        ]
    )
    return "\n".join(lines) + "\n"


def render_chart(meta: dict, polity: dict, intervals: list[dict]) -> str:
    margin = {"top": 74, "right": 32, "bottom": 74, "left": 116}
    plot_w = CHART_WIDTH - margin["left"] - margin["right"]
    plot_h = CHART_HEIGHT - margin["top"] - margin["bottom"]
    known = [item for item in intervals if item["area"]]
    if not known:
        known = []
    areas = [item["area"] for item in known] or [1.0]
    y_max = max(1.0, sum(areas))
    rough = nice_ticks(0.0, y_max, 4)
    step_y = rough[1] - rough[0] if len(rough) > 1 else y_max
    y_max = max(step_y, math.ceil(y_max / step_y) * step_y)
    x_min, x_max = polity["from"], polity["to"]

    def sx(year: float) -> float:
        return margin["left"] + (year - x_min) / max(1, x_max - x_min) * plot_w

    def sy(area: float) -> float:
        return margin["top"] + plot_h - (area / y_max) * plot_h

    title = f"{polity['name']} — cumulative land ceded"
    description = (
        f"Cumulative land area ceded by {polity['name']} from {format_year(x_min)} to "
        f"{format_year(x_max)}; {len(intervals)} cession record(s) totalling "
        f"{format_area(polity.get('totalArea'))}. Source: Royce, C. C., Indian Land Cessions "
        f"in the United States (1899), digitised by the U.S. Forest Service and Claudio Saunt "
        f"(public domain). Figure licensed {meta['license']}. Areas are computed from the "
        f"digitised polygons, not from surveyed acreage, and a cession shared by several "
        f"nations is credited in full to each."
    )

    subtitle = (
        f"Cumulative land ceded, {format_year(x_min)} – {format_year(x_max)} · "
        f"{len(intervals)} cession record{'s' if len(intervals) != 1 else ''}"
    )
    body = [
        f'<text x="{margin["left"]}" y="40" font-family="sans-serif" font-size="26" fill="{INK}">{escape(title)}</text>',
        f'<text x="{margin["left"]}" y="62" font-family="sans-serif" font-size="15" fill="{MUTED}">'
        f"{escape(subtitle)}</text>",
    ]

    for tick in nice_ticks(0, y_max, 4):
        y = sy(tick)
        body.append(
            f'<line x1="{margin["left"]}" x2="{margin["left"] + plot_w}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>'
        )
        body.append(
            f'<text x="{margin["left"] - 12}" y="{y + 5:.1f}" text-anchor="end" font-family="sans-serif" '
            f'font-size="13" fill="{MUTED}">{short_number(tick)} km²</text>'
        )

    for tick in nice_ticks(x_min, x_max, 6):
        x = sx(tick)
        body.append(
            f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{margin["top"]}" y2="{margin["top"] + plot_h}" stroke="{GRID}"/>'
        )
        body.append(
            f'<text x="{x:.1f}" y="{margin["top"] + plot_h + 26}" text-anchor="middle" font-family="sans-serif" '
            f'font-size="13" fill="{MUTED}">{escape(format_year(int(tick)))}</text>'
        )

    body.append(
        f'<line x1="{margin["left"]}" x2="{margin["left"] + plot_w}" y1="{margin["top"] + plot_h}" '
        f'y2="{margin["top"] + plot_h}" stroke="{AXIS}"/>'
    )

    points = [f"M{sx(x_min):.1f},{sy(0):.1f}"]
    running = 0.0
    for item in sorted(known, key=lambda entry: entry["to"]):
        running += item["area"]
        points.append(f"H{sx(item['to']):.1f}V{sy(running):.1f}")
    points.append(f"H{sx(x_max):.1f}")
    line = "".join(points)
    body.append(f'<path d="{line}L{sx(x_max):.1f},{sy(0):.1f}Z" fill="{CESSION}" fill-opacity="0.1"/>')
    body.append(f'<path d="{line}" stroke="{CESSION}" stroke-width="4" fill="none" stroke-linejoin="round"/>')

    body.append(
        f'<text x="{margin["left"]}" y="{CHART_HEIGHT - 26}" font-family="sans-serif" font-size="12" fill="{MUTED}">'
        f"Step height is the recorded polygon area; gaps mean no record, not absence of people.</text>"
    )
    source = source_for(meta)
    return svg_document(meta, source, title, description, CHART_WIDTH, CHART_HEIGHT, body)


def render_map(
    meta: dict,
    polity: dict,
    intervals: list[dict],
    geometries: list,
    year: int,
    states: list[dict],
) -> str:
    header = 56
    footer = 64
    pad = 26
    content_h = 500
    height = header + content_h + footer
    title = f"Land ceded by {polity['name']} by {format_year(year)}"
    active = [item for item in intervals if item["to"] <= year]
    touched: set[str] = set()
    for item in active:
        touched.update(item.get("s") or [])
    states_touched = sorted(touched)
    description = (
        f"All land recorded as ceded by {polity['name']} up to {format_year(year)}, "
        f"equirectangular projection framed to the recorded polygons, with modern state "
        f"boundaries for context. The ceded land now lies in: "
        f"{', '.join(states_touched) if states_touched else 'no mapped state'}. "
        f"Source: Royce, C. C., Indian Land Cessions in the United States (1899), digitised "
        f"by the U.S. Forest Service and Claudio Saunt (public domain). State outlines: "
        f"Natural Earth (public domain). Figure licensed {meta['license']}. "
        f"Cession boundaries are one interpretation of the 1899 schedule, not surveyed borders."
    )

    layers: list[tuple[list, str]] = []
    state_layers: list[tuple[list, str]] = []
    min_lon = min_lat = math.inf
    max_lon = max_lat = -math.inf
    for item in intervals:
        index = item["i"]
        if index is None or index >= len(geometries) or geometries[index] is None:
            continue
        if not any(entry is item for entry in active):
            continue
        geometry = geometries[index]
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        fill = CESSION
        for polygon in polygons:
            for ring in polygon:
                for lon, lat in ring:
                    min_lon = min(min_lon, lon)
                    max_lon = max(max_lon, lon)
                    min_lat = min(min_lat, lat)
                    max_lat = max(max_lat, lat)
                layers.append((ring, fill))

    for entry in states:
        if entry.get("name") not in touched:
            continue
        geometry = entry["geometry"]
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        for polygon in polygons:
            for ring in polygon:
                for lon, lat in ring:
                    min_lon = min(min_lon, lon)
                    max_lon = max(max_lon, lon)
                    min_lat = min(min_lat, lat)
                    max_lat = max(max_lat, lat)
                state_layers.append((ring, STATE_LINE))

    if not math.isfinite(min_lon):
        min_lon, max_lon, min_lat, max_lat = -170.0, -20.0, 15.0, 72.0

    mid_lat = (min_lat + max_lat) / 2
    lon_scale = max(0.15, math.cos(math.radians(mid_lat)))
    span_x = max(0.05, (max_lon - min_lon) * lon_scale)
    span_y = max(0.05, max_lat - min_lat)
    scale = min((MAP_WIDTH - 2 * pad) / span_x, (content_h - 2 * pad) / span_y)
    center_lon = (min_lon + max_lon) / 2
    center_lat = (min_lat + max_lat) / 2

    def project(lon: float, lat: float) -> tuple[float, float]:
        return (
            MAP_WIDTH / 2 + (lon - center_lon) * lon_scale * scale,
            header + content_h / 2 - (lat - center_lat) * scale,
        )

    body = [
        f'<text x="16" y="34" font-family="sans-serif" font-size="26" fill="{INK}">{escape(title)}</text>',
        f'<defs><clipPath id="map-clip"><rect x="0" y="{header}" width="{MAP_WIDTH}" '
        f'height="{content_h}"/></clipPath></defs>',
        f'<rect x="0" y="{header}" width="{MAP_WIDTH}" height="{content_h}" fill="#f7f5ef"/>',
        '<g clip-path="url(#map-clip)">',
    ]

    if span_y > 60:
        step = 20
    elif span_y > 25:
        step = 10
    elif span_y > 8:
        step = 5
    elif span_y > 2:
        step = 1
    else:
        step = 0.25

    latitude = math.ceil(min_lat / step) * step
    while latitude <= max_lat:
        _, y = project(center_lon, latitude)
        body.append(
            f'<line x1="0" x2="{MAP_WIDTH}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>'
        )
        latitude += step
    longitude = math.ceil(min_lon / step) * step
    while longitude <= max_lon:
        x, _ = project(longitude, center_lat)
        body.append(
            f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{header}" y2="{header + content_h}" stroke="{GRID}"/>'
        )
        longitude += step

    for ring, color in state_layers:
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in (project(lon, lat) for lon, lat in ring))
        body.append(
            f'<polygon points="{points}" fill="none" stroke="{color}" stroke-width="0.7"/>'
        )

    for ring, fill in layers:
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in (project(lon, lat) for lon, lat in ring))
        body.append(
            f'<polygon points="{points}" fill="#fbfaf6" fill-opacity="0.9" stroke="{INK}" '
            f'stroke-width="1.1"/>'
        )

    body.append("</g>")
    body.append(
        f'<rect x="0.5" y="{header + 0.5}" width="{MAP_WIDTH - 1}" height="{content_h - 1}" '
        f'fill="none" stroke="{AXIS}"/>'
    )

    if states_touched:
        names = ", ".join(states_touched)
        body.append(
            f'<text x="16" y="{height - 38}" font-family="sans-serif" font-size="13" fill="{MUTED}">'
            f"Ceded land now lies in: {escape(names)}</text>"
        )

    if not active:
        body.append(
            f'<text x="{MAP_WIDTH / 2:.0f}" y="{header + content_h / 2:.0f}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="20" fill="{MUTED}">No polygon recorded for '
            f"{escape(format_year(year))}</text>"
        )

    return svg_document(meta, source_for(meta), title, description, MAP_WIDTH, height, body)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def load_shard(data_dir: Path, shard: str) -> dict:
    path = data_dir / "geom" / f"{shard}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def rank_by_size(polities: list[dict]) -> list[dict]:
    """Order by total land ceded."""
    return sorted(
        polities,
        key=lambda polity: polity.get("totalArea") or 0.0,
        reverse=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", default="site/data")
    parser.add_argument("--out", default="dist/svg")
    parser.add_argument("--key", action="append", default=[], help="polity key (repeatable)")
    parser.add_argument("--top", type=int, default=0, help="export the N largest polities")
    parser.add_argument("--list", type=int, default=0, help="list the N largest polities and exit")
    parser.add_argument("--year", type=int, default=None, help="year for the map export")
    parser.add_argument("--no-map", action="store_true", help="skip map rendering")
    args = parser.parse_args(argv)

    data_dir = Path(args.data)
    if not (data_dir / "polities.json").exists():
        raise SystemExit(f"{data_dir}/polities.json not found — run pipeline/build_site_data.py first")

    index_payload = json.loads((data_dir / "polities.json").read_text(encoding="utf-8"))
    meta = index_payload["meta"]
    polities = index_payload["polities"]
    series = json.loads((data_dir / "series.json").read_text(encoding="utf-8"))

    if args.list:
        for polity in rank_by_size(polities)[: args.list]:
            log(f"{polity['key']:<42} {polity['name']} ({polity['from']}..{polity['to']})")
        return 0

    targets = list(args.key)
    if args.top:
        targets.extend(polity["key"] for polity in rank_by_size(polities)[: args.top])
    if not targets:
        parser.error("pass --key or --top (or use --list)")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    by_key = {polity["key"]: polity for polity in polities}
    shard_cache: dict[str, dict] = {}
    written = 0

    for key in targets:
        polity = by_key.get(key)
        if polity is None:
            log(f"skip {key}: not in dataset")
            continue
        intervals = series.get(key, [])
        shard = polity["shard"]
        if shard not in shard_cache:
            shard_cache[shard] = load_shard(data_dir, shard)

        base = slug(polity["name"])
        chart_path = out_dir / f"{base}-cumulative-land-ceded.svg"
        chart_path.write_text(render_chart(meta, polity, intervals), encoding="utf-8")
        log(f"wrote {chart_path}")
        written += 1

        peak = next((i for i in intervals if i["area"]), None)
        if not args.no_map and peak is not None:
            year = args.year if args.year is not None else polity["to"]
            geometries = shard_cache[shard].get(intervals[0].get("g", key) if intervals else key) or []
            states = shard_cache[shard].get("us-states") or []
            map_path = out_dir / f"{base}-ceded-by-{year}.svg"
            map_path.write_text(
                render_map(meta, polity, intervals, geometries, year, states), encoding="utf-8"
            )
            log(f"wrote {map_path}")
            written += 1

    log(f"done: {written} file(s) in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
