#!/usr/bin/env python3
"""Render standalone, Commons-ready SVGs from the built dataset in site/data/.

Output has no scripts and no external references; the relief sheet is embedded as a PNG data
URI, and `<title>`, `<desc>` and a metadata block carry source, version and license. Standard
library only.

Examples
--------
    py pipeline/export_svg.py --key royce-cherokee --year 1866
    py pipeline/export_svg.py --top 12
    py pipeline/export_svg.py --key royce-comanche --out dist/svg
    py pipeline/export_svg.py --list 50
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

CHART_WIDTH = 1200
CHART_HEIGHT = 1000
MAP_WIDTH = 1200
INK = "#1c1b18"
MUTED = "#6b655b"
CESSION = "#007c78"
GRID = "#e6e1d6"
AXIS = "#cbc5b8"
STATE_LINE = "#737a78"

def log(message: str) -> None:
    print(f"[export] {message}", flush=True)


def format_year(year: int) -> str:
    return f"{abs(year)} BCE" if year < 0 else f"{year} CE"


def format_area(area: float | None) -> str:
    return "unknown" if area is None else f"{area:,.0f} km²"


def cession_color(index: int, count: int) -> str:
    stops = ((246, 213, 92), (237, 139, 35), (198, 40, 40))
    progress = 0.0 if count <= 1 else index / (count - 1)
    segment = min(1, int(progress * 2))
    within_segment = progress * 2 - segment
    channels = tuple(
        round(start + (end - start) * within_segment)
        for start, end in zip(stops[segment], stops[segment + 1])
    )
    return "#" + "".join(f"{channel:02x}" for channel in channels)


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


def wrapped_text(value: str, limit: int) -> list[str]:
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + len(word) + 1 > limit:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def svg_document(
    meta: dict,
    source: dict,
    title: str,
    description: str,
    width: int,
    height: int,
    body: list[str],
) -> str:
    attribution_lines = wrapped_text(source["attribution"], 185)
    attribution_lines = attribution_lines[:4]
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
            f'<line x1="32" x2="{width - 32}" y1="{height - 72}" y2="{height - 72}" stroke="{GRID}"/>',
            *[
                f'<text x="32" y="{height - 56 + index * 13}" font-family="sans-serif" font-size="9" fill="{MUTED}">'
                f"{escape(line)}</text>"
                for index, line in enumerate(attribution_lines)
            ],
            f'<text x="32" y="{height - 12}" font-family="sans-serif" font-size="9" fill="{MUTED}">'
            f"Figure license: {escape(meta['license'])} · Generated {escape(meta['generated'])}</text>",
            "</svg>",
        ]
    )
    return "\n".join(lines) + "\n"


def render_chart(meta: dict, polity: dict, intervals: list[dict]) -> str:
    known = [item for item in intervals if item["area"] is not None]
    year_areas: dict[int, float] = {}
    for item in known:
        year_areas[item["to"]] = year_areas.get(item["to"], 0.0) + item["area"]
    event_years = sorted(year_areas)
    event_rows = max(1, math.ceil(len(event_years) / 4))
    extra_height = max(0, event_rows - 1) * 22
    chart_height = CHART_HEIGHT + extra_height
    margin = {"top": 162, "right": 58, "bottom": chart_height - 662, "left": 142}
    plot_w = CHART_WIDTH - margin["left"] - margin["right"]
    plot_h = chart_height - margin["top"] - margin["bottom"]
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
        f"Cumulative recorded area · {len(intervals)} cession records · "
        f"{format_year(x_min)} to {format_year(x_max)}"
    )
    total_area = format_area(polity.get("totalArea"))
    body = [
        f'<text x="72" y="42" font-family="sans-serif" font-size="12" font-weight="700" '
        f'letter-spacing="2" fill="{CESSION}">NATIVE LAND CESSIONS - CUMULATIVE RECORD</text>',
        f'<text x="72" y="82" font-family="sans-serif" font-size="32" font-weight="600" fill="{INK}">{escape(title.replace("—", "-"))}</text>',
        f'<text x="72" y="111" font-family="sans-serif" font-size="16" fill="{MUTED}">'
        f"{escape(subtitle)}</text>",
        f'<rect x="850" y="40" width="278" height="82" rx="4" fill="#f2f6f5"/>',
        f'<text x="872" y="68" font-family="sans-serif" font-size="11" font-weight="700" '
        f'letter-spacing="1.2" fill="{MUTED}">RECORDED TOTAL</text>',
        f'<text x="872" y="101" font-family="sans-serif" font-size="26" font-weight="600" fill="{CESSION}">{escape(total_area)}</text>',
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

    baseline = margin["top"] + plot_h
    body.append(
        f'<line x1="{margin["left"]}" x2="{margin["left"] + plot_w}" y1="{baseline}" '
        f'y2="{baseline}" stroke="{AXIS}" stroke-width="1.2"/>'
    )

    points = [f"M{sx(x_min):.1f},{sy(0):.1f}"]
    events = []
    cumulative = 0.0
    year_colors = {
        event_year: cession_color(index, len(event_years))
        for index, event_year in enumerate(event_years)
    }
    for event_year in event_years:
        cumulative += year_areas[event_year]
        x = sx(event_year)
        y = sy(cumulative)
        points.append(f"H{x:.1f}V{y:.1f}")
        events.append((x, y, event_year, cumulative))
    points.append(f"H{sx(x_max):.1f}")
    line = "".join(points)
    body.append(f'<path d="{line}L{sx(x_max):.1f},{sy(0):.1f}Z" fill="{CESSION}" fill-opacity="0.12"/>')
    body.append(f'<path d="{line}" stroke="{CESSION}" stroke-width="4" fill="none" stroke-linejoin="round"/>')
    for x, y, event_year, cumulative_area in events:
        color = year_colors[event_year]
        body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{baseline}" y2="{baseline + 8}" stroke="{color}" stroke-width="2"/>')
        body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}" stroke="#ffffff" stroke-width="2"><title>{escape(format_year(event_year))}: {cumulative_area:,.0f} km² cumulative</title></circle>')

    event_top = baseline + 133
    body.append(
        f'<text x="72" y="{event_top}" font-family="sans-serif" font-size="12" font-weight="700" '
        f'letter-spacing="1.2" fill="{INK}">RECORDED AREA BY CESSION YEAR · KM²</text>'
    )
    event_column_width = (CHART_WIDTH - 144) / 4
    for index, event_year in enumerate(event_years):
        column = index // event_rows
        row = index % event_rows
        x = 72 + column * event_column_width
        y = event_top + 29 + row * 22
        color = year_colors[event_year]
        body.append(f'<circle cx="{x + 5}" cy="{y - 4}" r="4" fill="{color}"/>')
        body.append(
            f'<text x="{x + 16}" y="{y}" font-family="sans-serif" font-size="12" fill="{INK}">'
            f"{escape(format_year(event_year))} · {year_areas[event_year]:,.0f}</text>"
        )

    notes_top = event_top + 29 + event_rows * 22 + 8
    chart_height = max(CHART_HEIGHT, notes_top + 65 + 35 + 96)
    body.extend([
        f'<defs><linearGradient id="cession-time" x1="0" x2="1" y1="0" y2="0">'
        f'<stop offset="0%" stop-color="#f6d55c"/><stop offset="52%" stop-color="#ed8b23"/>'
        f'<stop offset="100%" stop-color="#c62828"/></linearGradient></defs>',
        f'<text x="72" y="{notes_top}" font-family="sans-serif" font-size="12" fill="{MUTED}">'
        f"Gaps indicate no cession record in the schedule—not absence of Native presence or land use.</text>",
        f'<rect x="72" y="{notes_top + 30}" width="220" height="10" rx="2" fill="url(#cession-time)"/>',
        f'<text x="72" y="{notes_top + 57}" font-family="sans-serif" font-size="11" fill="{INK}">Earlier recorded cessions</text>',
        f'<text x="292" y="{notes_top + 57}" text-anchor="end" font-family="sans-serif" font-size="11" fill="{INK}">Later recorded cessions</text>',
        f'<text x="72" y="{notes_top + 19}" font-family="sans-serif" font-size="12" fill="{MUTED}">'
        f"Areas are computed from digitised polygons; shared cessions are credited in full to each signatory nation.</text>",
    ])
    source = source_for(meta)
    return svg_document(meta, source, title, description, CHART_WIDTH, chart_height, body)


def render_map(
    meta: dict,
    polity: dict,
    intervals: list[dict],
    geometries: list,
    year: int,
    states: list[dict],
    relief: list[dict],
) -> str:
    header = 116
    pad = 30
    content_h = 570
    title = f"Land still unceded by {polity['name']} after {format_year(year)}"
    active = [item for item in intervals if item["to"] >= year]
    touched: set[str] = set()
    for item in active:
        touched.update(item.get("s") or [])
    states_touched = sorted(touched)
    description = (
        f"Recorded cessions by {polity['name']} still ahead of {format_year(year)}, "
        f"equirectangular projection framed to the recorded polygons, with modern state "
        f"boundaries for context. The ceded land now lies in: "
        f"{', '.join(states_touched) if states_touched else 'no mapped state'}. "
        f"Source: Royce, C. C., Indian Land Cessions in the United States (1899), digitised "
        f"by the U.S. Forest Service and Claudio Saunt (public domain). State and lake outlines: "
        f"Natural Earth (public domain). Figure licensed {meta['license']}. "
        f"Cession boundaries are one interpretation of the 1899 schedule, not surveyed borders."
    )

    all_years = sorted({item["to"] for item in intervals})
    year_colors = {
        event_year: cession_color(index, len(all_years))
        for index, event_year in enumerate(all_years)
    }
    active_years = [event_year for event_year in all_years if event_year >= year]
    active_year_colors = {event_year: year_colors[event_year] for event_year in active_years}
    layers: list[tuple[dict, str, int]] = []
    state_layers: list[tuple[dict, str]] = []
    state_label_bounds: dict[str, list[float]] = {}
    min_lon = min_lat = math.inf
    max_lon = max_lat = -math.inf
    active_ids = {id(item) for item in active}
    for item in intervals:
        index = item["i"]
        if index is None or index >= len(geometries) or geometries[index] is None:
            continue
        if id(item) not in active_ids:
            continue
        geometry = geometries[index]
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        fill = active_year_colors[item["to"]]
        for polygon in polygons:
            for ring in polygon:
                for lon, lat in ring:
                    min_lon = min(min_lon, lon)
                    max_lon = max(max_lon, lon)
                    min_lat = min(min_lat, lat)
                    max_lat = max(max_lat, lat)
        layers.append((geometry, fill, item["to"]))

    for entry in states:
        if entry.get("name") not in touched:
            continue
        geometry = entry["geometry"]
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        bounds = [math.inf, math.inf, -math.inf, -math.inf]
        for polygon in polygons:
            for ring in polygon:
                for lon, lat in ring:
                    bounds[0] = min(bounds[0], lon)
                    bounds[1] = min(bounds[1], lat)
                    bounds[2] = max(bounds[2], lon)
                    bounds[3] = max(bounds[3], lat)
        state_layers.append((geometry, STATE_LINE))
        state_label_bounds[entry["name"]] = bounds

    if not math.isfinite(min_lon):
        if relief:
            min_lon, max_lon = relief[0]["lon0"], relief[0]["lon1"]
            min_lat, max_lat = relief[0]["lat0"], relief[0]["lat1"]
        else:
            min_lon, max_lon, min_lat, max_lat = -170.0, -20.0, 15.0, 72.0

    mid_lat = (min_lat + max_lat) / 2
    lon_scale = max(0.15, math.cos(math.radians(mid_lat)))
    span_x = max(1.2, (max_lon - min_lon) * lon_scale)
    span_y = max(0.9, max_lat - min_lat)
    scale = min((MAP_WIDTH - 2 * pad) / span_x, (content_h - 2 * pad) / span_y)
    center_lon = (min_lon + max_lon) / 2
    center_lat = (min_lat + max_lat) / 2

    def project(lon: float, lat: float) -> tuple[float, float]:
        return (
            MAP_WIDTH / 2 + (lon - center_lon) * lon_scale * scale,
            header + content_h / 2 - (lat - center_lat) * scale,
        )

    relief_images = []
    for entry in relief:
        path = Path(entry.get("path", ""))
        if not path.exists():
            continue
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        relief_images.append(
            f'<image x="{entry["lon0"]:.4f}" y="{entry["lat0"]:.4f}" '
            f'width="{entry["lon1"] - entry["lon0"]:.4f}" height="{entry["lat1"] - entry["lat0"]:.4f}" '
            f'preserveAspectRatio="none" '
            f'transform="matrix({lon_scale * scale:.6f} 0 0 {-scale:.6f} '
            f'{MAP_WIDTH / 2 - lon_scale * scale * center_lon:.4f} '
            f'{header + content_h / 2 + scale * center_lat:.4f})" '
            f'href="data:image/png;base64,{encoded}"/>'
        )

    body = [
        f'<text x="40" y="36" font-family="sans-serif" font-size="12" font-weight="700" '
        f'letter-spacing="2" fill="{CESSION}">NATIVE LAND CESSIONS · REMAINING AFTER {escape(format_year(year))}</text>',
        f'<text x="40" y="74" font-family="sans-serif" font-size="30" font-weight="600" fill="{INK}">{escape(title)}</text>',
        f'<text x="40" y="101" font-family="sans-serif" font-size="14" fill="{MUTED}">'
        f"{len(active)} cession records from {format_year(year)} onward · {format_area(sum(item.get('area') or 0 for item in active))} recorded area</text>",
        f'<defs><clipPath id="map-clip"><rect x="0" y="{header}" width="{MAP_WIDTH}" '
        f'height="{content_h}"/></clipPath><linearGradient id="cession-time" x1="0" x2="1" y1="0" y2="0">'
        f'<stop offset="0%" stop-color="#f6d55c"/><stop offset="52%" stop-color="#ed8b23"/>'
        f'<stop offset="100%" stop-color="#c62828"/></linearGradient></defs>',
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

    body.extend(relief_images)

    for geometry, color, event_year in layers:
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        paths = []
        for polygon in polygons:
            for ring in polygon:
                points = [project(lon, lat) for lon, lat in ring]
                paths.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in points) + "Z")
        body.append(
            f'<path d="{"".join(paths)}" fill="{color}" fill-opacity="0.9" fill-rule="evenodd" '
            f'stroke="#171717" stroke-width="1.15" stroke-linejoin="round">'
            f'<title>{escape(format_year(event_year))} cession</title></path>'
        )

    for geometry, color in state_layers:
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        paths = []
        for polygon in polygons:
            for ring in polygon:
                points = [project(lon, lat) for lon, lat in ring]
                paths.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in points) + "Z")
        body.append(
            f'<path d="{"".join(paths)}" fill="none" stroke="{color}" stroke-width="1.1"/>'
        )

    for name, bounds in state_label_bounds.items():
        lon = (bounds[0] + bounds[2]) / 2
        lat = (bounds[1] + bounds[3]) / 2
        x, y = project(lon, lat)
        body.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" dominant-baseline="middle" '
            f'font-family="sans-serif" font-size="12" font-weight="700" letter-spacing="1" '
            f'fill="{INK}" paint-order="stroke" stroke="#f7f5ef" stroke-width="3.5" stroke-linejoin="round">'
            f"{escape(name.upper())}</text>"
        )

    body.append("</g>")
    body.append(
        f'<rect x="0.5" y="{header + 0.5}" width="{MAP_WIDTH - 1}" height="{content_h - 1}" '
        f'fill="none" stroke="{AXIS}"/>'
    )

    legend_top = header + content_h + 30
    legend_height = 72
    first_recorded_year = all_years[0] if all_years else None
    last_recorded_year = all_years[-1] if all_years else None
    context_lines = wrapped_text(
        "Modern state boundaries shown for context; labels identify states overlapping recorded ceded areas.",
        145,
    )
    touched_lines = wrapped_text(
        "Ceded land now lies in: " + (", ".join(states_touched) if states_touched else "no mapped state"),
        145,
    )
    caveat_lines = wrapped_text(
        "Cession boundaries follow Royce's historical schedule and are not surveyed borders. "
        "Areas use digitised polygons; shared cessions are credited in full to each nation.",
        145,
    )
    caption_top = legend_top + legend_height + 24
    context_lines.extend(touched_lines)
    for index, line in enumerate(context_lines):
        body.append(
            f'<text x="40" y="{caption_top + index * 19}" font-family="sans-serif" font-size="13" fill="{MUTED}">'
            f"{escape(line)}</text>"
        )
    caveat_top = caption_top + len(context_lines) * 19
    for index, line in enumerate(caveat_lines):
        body.append(
            f'<text x="40" y="{caveat_top + index * 19}" font-family="sans-serif" font-size="13" fill="{MUTED}">'
            f"{escape(line)}</text>"
        )
    source_top = caveat_top + len(caveat_lines) * 19
    source_lines = wrapped_text(
        "Sources: Royce (1899), digitised by the U.S. Forest Service with Claudio Saunt; "
        "state boundaries: Natural Earth (CC0); relief: NASA SRTM (public domain).",
        145,
    )
    for index, line in enumerate(source_lines):
        body.append(
            f'<text x="40" y="{source_top + index * 17}" font-family="sans-serif" font-size="12" fill="{MUTED}">'
            f"{escape(line)}</text>"
        )

    height = source_top + len(source_lines) * 17 + legend_height + 58
    body.extend([
        f'<text x="40" y="{legend_top}" font-family="sans-serif" font-size="12" font-weight="700" '
        f'letter-spacing="1.4" fill="{INK}">CESSION CHRONOLOGY · ALL RECORDED EVENTS</text>',
        f'<line x1="426" x2="460" y1="{legend_top - 4}" y2="{legend_top - 4}" stroke="{STATE_LINE}" stroke-width="2"/>',
        f'<text x="468" y="{legend_top}" font-family="sans-serif" font-size="12" fill="{MUTED}">Modern state boundary</text>',
        f'<rect x="40" y="{legend_top + 12}" width="300" height="12" rx="2" fill="url(#cession-time)"/>',
        f'<text x="40" y="{legend_top + 42}" font-family="sans-serif" font-size="12" fill="{INK}">'
        f'Earlier · {escape(format_year(first_recorded_year)) if first_recorded_year is not None else "no records"}</text>',
        f'<text x="340" y="{legend_top + 42}" text-anchor="end" font-family="sans-serif" font-size="12" fill="{INK}">'
        f'Later · {escape(format_year(last_recorded_year)) if last_recorded_year is not None else "no records"}</text>',
        f'<text x="40" y="{legend_top + 60}" font-family="sans-serif" font-size="11" fill="{MUTED}">'
        f'Yellow to red follows recorded cession order; it does not show original territory or current holdings.</text>',
    ])

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

    terrain_path = data_dir / "terrain.json"
    terrain_index = (
        json.loads(terrain_path.read_text(encoding="utf-8")) if terrain_path.exists() else {}
    )
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
            relief = []
            for entry in terrain_index.get(key, []):
                path = data_dir / "terrain" / Path(entry["file"]).name
                if path.exists():
                    relief.append({**entry, "path": str(path)})
            map_path = out_dir / f"{base}-remaining-after-{year}.svg"
            map_path.write_text(
                render_map(meta, polity, intervals, geometries, year, states, relief),
                encoding="utf-8",
            )
            log(f"wrote {map_path}")
            written += 1

    log(f"done: {written} file(s) in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
