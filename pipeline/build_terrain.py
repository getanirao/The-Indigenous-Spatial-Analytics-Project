#!/usr/bin/env python3
"""Render USGS-style terrain (hillshade + contour lines) behind the cession maps.

Elevation comes from the AWS Terrain Tiles "terrarium" set, which encodes SRTM height in
RGB; the tiles are public domain. Each nation gets one equirectangular PNG covering all of its
cessions: shaded relief with contour lines, drawn in the same lon/lat space the viewer uses, so
the viewer can place it with a plain SVG transform. One sheet per nation keeps every map on a
single continuous base at one zoom and one contour interval, instead of a collage of tiles.

    py pipeline\\build_terrain.py --key royce-cherokee        # one nation
    py pipeline\\build_terrain.py --all --limit 25             # a first batch
    py pipeline\\build_terrain.py --all                        # every nation

Tiles are cached under data/raw/terrarium/<z>/<x>/<y>.png.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import time
import urllib.request
import zlib
from array import array
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
TILE_SIZE = 256
MAX_ZOOM = 13
MIN_ZOOM = 5
BAND_COUNT = 24
SHADE_COUNT = 8
CONTOUR_INDEX = BAND_COUNT * SHADE_COUNT
INDEX_CONTOUR_INDEX = CONTOUR_INDEX + 1
VOID_INDEX = INDEX_CONTOUR_INDEX + 1
SHEET_VERSION = 3

WATER_COLOR = (205, 216, 221)
RAMP_COLORS = (
    (206, 222, 196),
    (220, 219, 191),
    (226, 201, 162),
)
CONTOUR_COLOR = (170, 142, 106)
INDEX_CONTOUR_COLOR = (126, 98, 68)
SHADE_LOW = 0.72
SHADE_HIGH = 1.06

MIN_SHEET_SPAN_X = 2.2
MIN_SHEET_SPAN_Y = 1.5
MIN_SHEET_ASPECT = 2.1
SHEET_MARGIN = 0.12


def elevation_ramp() -> tuple[tuple[int, int, int], ...]:
    stops = []
    for band in range(BAND_COUNT):
        position = band / (BAND_COUNT - 1)
        if position <= 0.5:
            first, second, local = RAMP_COLORS[0], RAMP_COLORS[1], position / 0.5
        else:
            first, second, local = RAMP_COLORS[1], RAMP_COLORS[2], (position - 0.5) / 0.5
        stops.append(
            tuple(int(first[i] + (second[i] - first[i]) * local) for i in range(3))
        )
    return tuple(stops)


PALETTE_ELEVATION = elevation_ramp()


def log(message: str) -> None:
    print(f"[terrain] {message}", flush=True)


# ---------------------------------------------------------------- PNG helpers


def png_decode(data: bytes) -> tuple[int, int, int, bytearray]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos = 8
    idat = bytearray()
    width = height = color_type = bit_depth = 0
    while pos < len(data):
        length = int.from_bytes(data[pos : pos + 4], "big")
        ctype = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        if ctype == b"IHDR":
            width = int.from_bytes(chunk[0:4], "big")
            height = int.from_bytes(chunk[4:8], "big")
            bit_depth = chunk[8]
            color_type = chunk[9]
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
        pos += 12 + length
    raw = zlib.decompress(bytes(idat))
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    bpp = channels * bit_depth // 8
    stride = width * bpp
    out = bytearray(height * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos : pos + stride])
        pos += stride
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        out[y * stride : (y + 1) * stride] = line
        prev = line
    return width, height, channels, out


def png_encode_indexed(width: int, height: int, indices: bytearray, palette: list[tuple[int, int, int]]) -> bytes:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += indices[y * width : (y + 1) * width]
    compressed = zlib.compress(bytes(raw), 6)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            len(payload).to_bytes(4, "big")
            + tag
            + payload
            + zlib.crc32(tag + payload).to_bytes(4, "big")
        )

    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes((8, 3, 0, 0, 0))
    plte = bytearray()
    for red, green, blue in palette:
        plte += bytes((red, green, blue))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"PLTE", bytes(plte))
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


# ------------------------------------------------------------ elevation tiles


class Terrain:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.elevation: dict[tuple[int, int, int], array] = {}
        self.downloads = 0
        self.workers = 12

    def prefetch(self, keys: list[tuple[int, int, int]]) -> None:
        """Fetch the missing tiles in parallel; one slow tile should not stall a nation."""
        missing = [key for key in keys if key not in self.elevation and not self.cached(key)]
        if not missing:
            return
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            list(pool.map(lambda key: self.fetch(*key), missing))

    def cached(self, key: tuple[int, int, int]) -> bool:
        zoom, x, y = key
        return (self.cache_dir / str(zoom) / str(x) / f"{y}.png").exists()

    def fetch(self, zoom: int, x: int, y: int) -> None:
        path = self.cache_dir / str(zoom) / str(x) / f"{y}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        url = TILE_URL.format(z=zoom, x=x, y=y)
        request = urllib.request.Request(url, headers={"User-Agent": "isap/1.0"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    path.write_bytes(response.read())
                self.downloads += 1
                return
            except Exception as error:
                if attempt == 3:
                    raise
                time.sleep(1.5 * (attempt + 1))
                log(f"retrying {url}: {error}")

    def tile(self, zoom: int, x: int, y: int) -> array:
        key = (zoom, x, y)
        cached = self.elevation.get(key)
        if cached is not None:
            return cached
        path = self.cache_dir / str(zoom) / str(x) / f"{y}.png"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            url = TILE_URL.format(z=zoom, x=x, y=y)
            request = urllib.request.Request(url, headers={"User-Agent": "isap/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                path.write_bytes(response.read())
            self.downloads += 1
        width, height, channels, pixels = png_decode(path.read_bytes())
        if channels not in (3, 4):
            raise ValueError(f"unexpected tile channels: {channels}")
        values = array("f", bytes(width * height * 4))
        step = channels
        for index in range(width * height):
            base = index * step
            values[index] = (
                pixels[base] * 256 + pixels[base + 1] + pixels[base + 2] / 256
            ) - 32768
        self.elevation[key] = values
        return values


def mercator_pixel(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    scale = TILE_SIZE * (1 << zoom)
    x = (lon + 180.0) / 360.0 * scale
    lat = max(min(lat, 85.05112878), -85.05112878)
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * scale
    return x, y


def build_grid(
    terrain: Terrain,
    zoom: int,
    lon0: float,
    lat0: float,
    lon1: float,
    lat1: float,
    width: int,
    height: int,
) -> array:
    """Sample the DEM on the output grid, in output pixels."""
    scale = TILE_SIZE * (1 << zoom)
    corners = [
        mercator_pixel(lon, lat, zoom)
        for lon, lat in ((lon0, lat0), (lon1, lat0), (lon0, lat1), (lon1, lat1))
    ]
    min_x = math.floor(min(point[0] for point in corners) / TILE_SIZE) - 1
    max_x = math.floor(max(point[0] for point in corners) / TILE_SIZE) + 1
    min_y = math.floor(min(point[1] for point in corners) / TILE_SIZE) - 1
    max_y = math.floor(max(point[1] for point in corners) / TILE_SIZE) + 1

    terrain.prefetch(
        [(zoom, tx, ty) for ty in range(min_y, max_y + 1) for tx in range(min_x, max_x + 1)]
    )
    tiles = {}
    for ty in range(min_y, max_y + 1):
        for tx in range(min_x, max_x + 1):
            tiles[(tx, ty)] = terrain.tile(zoom, tx, ty)

    columns = []
    for col in range(width):
        lon = lon0 + (lon0 + (col + 0.5) * (lon1 - lon0) / width - lon0)
        gx, _ = mercator_pixel(lon, lat1, zoom)
        tx = math.floor(gx / TILE_SIZE)
        columns.append((tx, gx - tx * TILE_SIZE))

    grid = array("f", bytes(width * height * 4))
    for row in range(height):
        lat = lat1 - (row + 0.5) * (lat1 - lat0) / height
        _, gy = mercator_pixel(lon0, lat, zoom)
        ty = math.floor(gy / TILE_SIZE)
        fy = gy - ty * TILE_SIZE
        y0 = int(fy)
        wy = fy - y0
        crosses_row = y0 + 1 >= TILE_SIZE
        base = row * width
        for col in range(width):
            tx, fx = columns[col]
            x0 = int(fx)
            wx = fx - x0
            crosses_column = x0 + 1 >= TILE_SIZE

            top_left_tile = tiles[(tx, ty)]
            top_right_tile = tiles[(tx + 1, ty)] if crosses_column else top_left_tile
            if crosses_row:
                bottom_left_tile = tiles[(tx, ty + 1)]
                bottom_right_tile = tiles[(tx + 1, ty + 1)]
            else:
                bottom_left_tile = top_left_tile
                bottom_right_tile = top_right_tile

            top_left = top_left_tile[y0 * TILE_SIZE + x0]
            top_right = top_right_tile[y0 * TILE_SIZE + (0 if crosses_column else x0 + 1)]
            bottom_left = bottom_left_tile[(0 if crosses_row else y0 + 1) * TILE_SIZE + x0]
            bottom_right = bottom_right_tile[
                (0 if crosses_row else y0 + 1) * TILE_SIZE + (0 if crosses_column else x0 + 1)
            ]

            top = top_left + (top_right - top_left) * wx
            bottom = bottom_left + (bottom_right - bottom_left) * wx
            if crosses_row or crosses_column:
                grid[base + col] = top_left
            else:
                grid[base + col] = top + (bottom - top) * wy
    return grid


def smooth_grid(grid: array, valid: array, width: int, height: int) -> array:
    """Average out DEM noise so contours follow the land, like a generalised topo sheet."""
    smoothed = array("f", bytes(width * height * 4))
    for row in range(height):
        base = row * width
        for col in range(width):
            total = 0.0
            count = 0
            for row_offset in (-1, 0, 1):
                for col_offset in (-1, 0, 1):
                    r = row + row_offset
                    c = col + col_offset
                    if r < 0 or r >= height or c < 0 or c >= width:
                        continue
                    index = r * width + c
                    if not valid[index]:
                        continue
                    total += grid[index]
                    count += 1
            smoothed[base + col] = total / count if count else grid[base + col]
    return smoothed


def build_palette() -> list[tuple[int, int, int]]:
    palette = []
    for band in range(BAND_COUNT):
        red, green, blue = PALETTE_ELEVATION[band]
        for shade in range(SHADE_COUNT):
            factor = SHADE_LOW + (SHADE_HIGH - SHADE_LOW) * (shade / (SHADE_COUNT - 1))
            palette.append(
                (
                    min(255, int(red * factor)),
                    min(255, int(green * factor)),
                    min(255, int(blue * factor)),
                )
            )
    palette.append(CONTOUR_COLOR)
    palette.append(INDEX_CONTOUR_COLOR)
    palette.append(WATER_COLOR)
    return palette


def nice_interval(value: float) -> float:
    if value <= 0:
        return 1.0
    exponent = math.floor(math.log10(value))
    magnitude = 10**exponent
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * magnitude:
            return step * magnitude
    return 10 * magnitude


def contour_segments(
    grid: array, valid: array, width: int, height: int, interval: float
) -> list[tuple[float, float, float, float]]:
    segments = []
    for row in range(height - 1):
        base = row * width
        for col in range(width - 1):
            if not (
                valid[base + col]
                and valid[base + col + 1]
                and valid[base + width + col + 1]
                and valid[base + width + col]
            ):
                continue
            corners = (
                grid[base + col],
                grid[base + col + 1],
                grid[base + width + col + 1],
                grid[base + width + col],
            )
            if (max(corners) - min(corners)) < interval * 0.02:
                continue
            first_level = math.floor(min(corners) / interval) + 1
            last_level = math.floor(max(corners) / interval)
            edges = ((0, 1), (1, 2), (2, 3), (3, 0))
            for step in range(first_level, last_level + 1):
                level = step * interval
                is_index = step % 5 == 0
                crossings = []
                for edge_first, edge_second in edges:
                    a = corners[edge_first]
                    b = corners[edge_second]
                    if (a < level) == (b < level):
                        continue
                    t = (level - a) / (b - a) if b != a else 0.0
                    if edge_first == 0:
                        point = (col + t, row)
                    elif edge_first == 1:
                        point = (col + 1, row + t)
                    elif edge_first == 2:
                        point = (col + 1 - t, row + 1)
                    else:
                        point = (col, row + 1 - t)
                    crossings.append(point)
                if len(crossings) == 2:
                    segments.append(
                        (crossings[0][0], crossings[0][1], crossings[1][0], crossings[1][1], is_index)
                    )
                elif len(crossings) == 4:
                    centre_x = col + 0.5
                    centre_y = row + 0.5
                    ordered = sorted(
                        crossings,
                        key=lambda point: math.atan2(point[1] - centre_y, point[0] - centre_x),
                    )
                    segments.append(
                        (ordered[0][0], ordered[0][1], ordered[1][0], ordered[1][1], is_index)
                    )
                    segments.append(
                        (ordered[2][0], ordered[2][1], ordered[3][0], ordered[3][1], is_index)
                    )
    return segments


def draw_line(indices: bytearray, width: int, height: int, x0: float, y0: float, x1: float, y1: float, value: int) -> None:
    x0i, y0i, x1i, y1i = int(x0), int(y0), int(x1), int(y1)
    dx = abs(x1i - x0i)
    dy = -abs(y1i - y0i)
    sx = 1 if x0i < x1i else -1
    sy = 1 if y0i < y1i else -1
    error = dx + dy
    while True:
        if 0 <= x0i < width and 0 <= y0i < height:
            indices[y0i * width + x0i] = value
        if x0i == x1i and y0i == y1i:
            break
        doubled = 2 * error
        if doubled >= dy:
            error += dy
            x0i += sx
        if doubled <= dx:
            error += dx
            y0i += sy


def load_lakes(path: Path) -> list[tuple[tuple[float, float, float, float], list[list[tuple[float, float]]]]]:
    """Read lake outlines so positive lake surfaces can be masked back to water."""
    if not path.exists():
        log(f"no lake mask at {path}; lakes will read as land")
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    lakes = []
    for feature in payload.get("features", []):
        geometry = feature.get("geometry") or {}
        polygons = (
            [geometry.get("coordinates") or []]
            if geometry.get("type") == "Polygon"
            else geometry.get("coordinates") or []
        )
        for polygon in polygons:
            rings = [
                [(float(point[0]), float(point[1])) for point in ring]
                for ring in polygon
                if len(ring) >= 3
            ]
            if not rings:
                continue
            outer = rings[0]
            bounds = (
                min(point[0] for point in outer),
                min(point[1] for point in outer),
                max(point[0] for point in outer),
                max(point[1] for point in outer),
            )
            lakes.append((bounds, rings))
    return lakes


def mask_lakes(
    valid: array,
    width: int,
    height: int,
    bbox: tuple[float, float, float, float],
    lakes: list[tuple[tuple[float, float, float, float], list[list[tuple[float, float]]]]],
) -> None:
    """Scanline-fill each lake so its surface is water, not shaded land."""
    lon0, lat0, lon1, lat1 = bbox
    if lon1 <= lon0 or lat1 <= lat0:
        return
    scale_x = width / (lon1 - lon0)
    scale_y = height / (lat1 - lat0)
    for (x0, y0, x1, y1), rings in lakes:
        if x1 < lon0 or x0 > lon1 or y1 < lat0 or y0 > lat1:
            continue
        row_start = max(0, int((lat1 - y1) * scale_y))
        row_stop = min(height, int((lat1 - y0) * scale_y) + 1)
        for row in range(row_start, row_stop):
            latitude = lat1 - (row + 0.5) / scale_y
            crossings = []
            for ring in rings:
                previous = ring[-1]
                for point in ring:
                    low, high = (previous, point) if previous[1] <= point[1] else (point, previous)
                    if low[1] <= latitude < high[1]:
                        share = (latitude - low[1]) / (high[1] - low[1])
                        crossings.append(low[0] + share * (high[0] - low[0]))
                    previous = point
            crossings.sort()
            base = row * width
            for index in range(0, len(crossings) - 1, 2):
                start = max(0, int((crossings[index] - lon0) * scale_x))
                stop = min(width - 1, int((crossings[index + 1] - lon0) * scale_x))
                for col in range(start, stop + 1):
                    valid[base + col] = 0


def render(
    terrain: Terrain,
    bbox: tuple[float, float, float, float],
    width: int,
    height: int,
    out_path: Path,
    lakes: list[tuple[tuple[float, float, float, float], list[list[tuple[float, float]]]]] = (),
) -> dict:
    lon0, lat0, lon1, lat1 = bbox
    mid_lat = math.radians((lat0 + lat1) / 2)
    meters_per_deg_lon = 111320.0 * math.cos(mid_lat)
    meters_per_deg_lat = 110574.0
    target = max((lon1 - lon0) * meters_per_deg_lon / width, (lat1 - lat0) * meters_per_deg_lat / height)
    resolution = 156543.03392 * math.cos(mid_lat)
    zoom = int(round(math.log2(resolution / target))) if target > 0 else MAX_ZOOM
    zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))

    grid = build_grid(terrain, zoom, lon0, lat0, lon1, lat1, width, height)

    valid = array("b", bytes(width * height))
    for index, elevation in enumerate(grid):
        if 0.0 < elevation < 9000.0:
            valid[index] = 1
    mask_lakes(valid, width, height, bbox, lakes)
    samples = [elevation for index, elevation in enumerate(grid) if valid[index]]
    if not samples:
        samples = [0.0]
    samples.sort()
    lowest = samples[int(len(samples) * 0.02)]
    highest = samples[int(len(samples) * 0.98)]
    if highest - lowest < 20.0:
        highest = lowest + 20.0

    grid = smooth_grid(grid, valid, width, height)
    grid = smooth_grid(grid, valid, width, height)
    for index, elevation in enumerate(grid):
        if valid[index]:
            grid[index] = elevation

    deltas = []
    for row in range(1, height):
        base = row * width
        previous = base - width
        for col in range(1, width):
            if not (valid[base + col] and valid[previous + col]):
                continue
            deltas.append(abs(grid[base + col] - grid[previous + col]))
    deltas.sort()
    per_pixel = deltas[int(len(deltas) * 0.75)] if deltas else 0.0
    interval = nice_interval(max(per_pixel * 6.0, (highest - lowest) / 10.0, 1.0))

    indices = bytearray(width * height)
    shades = array("f", bytes(width * height * 4))
    band_scale = (BAND_COUNT - 1) / (highest - lowest)
    meters_x = max((lon1 - lon0) * meters_per_deg_lon / width, 1.0)
    meters_y = max((lat1 - lat0) * meters_per_deg_lat / height, 1.0)
    zenith = math.radians(45.0)
    azimuth = math.radians(315.0)
    cos_zenith = math.cos(zenith)
    sin_zenith = math.sin(zenith)

    for row in range(height):
        base = row * width
        for col in range(width):
            if not valid[base + col]:
                indices[base + col] = VOID_INDEX
                continue
            elevation = grid[base + col]
            band = int((elevation - lowest) * band_scale)
            band = 0 if band < 0 else (BAND_COUNT - 1 if band > BAND_COUNT - 1 else band)
            indices[base + col] = band * SHADE_COUNT + SHADE_COUNT // 2
            if row < 2 or row >= height - 2 or col < 2 or col >= width - 2:
                continue
            dzdx = (grid[base + col + 2] - grid[base + col - 2]) / 4.0
            dzdy = (grid[base + 2 * width + col] - grid[base - 2 * width + col]) / 4.0
            angle = math.atan(math.hypot(dzdx / meters_x, dzdy / meters_y) * 2.0)
            aspect = math.atan2(dzdy, -dzdx)
            shades[base + col] = cos_zenith * math.cos(angle) + sin_zenith * math.sin(angle) * math.cos(
                azimuth - aspect
            )

    lit = sorted(shades[index] for index in range(width * height) if valid[index])
    if lit:
        low = lit[int(len(lit) * 0.05)]
        high = lit[int(len(lit) * 0.95)]
    else:
        low, high = 0.0, 1.0
    if high - low < 0.10:
        middle = (low + high) / 2.0
        low, high = middle - 0.05, middle + 0.05
    stretch = (SHADE_COUNT - 1) / (high - low)

    for row in range(2, height - 2):
        base = row * width
        for col in range(2, width - 2):
            index = base + col
            if not valid[index]:
                continue
            level = int((shades[index] - low) * stretch)
            level = 0 if level < 0 else (SHADE_COUNT - 1 if level > SHADE_COUNT - 1 else level)
            indices[index] = (indices[index] // SHADE_COUNT) * SHADE_COUNT + level

    for x0, y0, x1, y1, is_index in contour_segments(grid, valid, width, height, interval):
        value = INDEX_CONTOUR_INDEX if is_index else CONTOUR_INDEX
        draw_line(indices, width, height, x0, y0, x1, y1, value)
        if is_index:
            draw_line(indices, width, height, x0, y0 + 1, x1, y1 + 1, value)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png_encode_indexed(width, height, indices, build_palette()))
    return {
        "file": out_path.name,
        "lon0": lon0,
        "lat0": lat0,
        "lon1": lon1,
        "lat1": lat1,
        "zoom": zoom,
        "interval": interval,
    }


def nation_sheet_bounds(
    boxes: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    """One bbox around every cession of a nation, padded so the sheet fills the map frame."""
    lon0 = min(box[0] for box in boxes)
    lat0 = min(box[1] for box in boxes)
    lon1 = max(box[2] for box in boxes)
    lat1 = max(box[3] for box in boxes)
    mid_lat = math.radians((lat0 + lat1) / 2)
    cos_lat = max(0.15, math.cos(mid_lat))

    x0 = lon0 * cos_lat
    x1 = lon1 * cos_lat
    if x1 - x0 < MIN_SHEET_SPAN_X:
        middle = (x0 + x1) / 2
        x0, x1 = middle - MIN_SHEET_SPAN_X / 2, middle + MIN_SHEET_SPAN_X / 2
    if lat1 - lat0 < MIN_SHEET_SPAN_Y:
        middle = (lat0 + lat1) / 2
        lat0, lat1 = middle - MIN_SHEET_SPAN_Y / 2, middle + MIN_SHEET_SPAN_Y / 2
    if x1 - x0 < MIN_SHEET_ASPECT * (lat1 - lat0):
        middle = (x0 + x1) / 2
        half = MIN_SHEET_ASPECT * (lat1 - lat0) / 2
        x0, x1 = middle - half, middle + half

    margin_x = (x1 - x0) * SHEET_MARGIN
    margin_y = (lat1 - lat0) * SHEET_MARGIN
    return (
        (x0 - margin_x) / cos_lat,
        lat0 - margin_y,
        (x1 + margin_x) / cos_lat,
        lat1 + margin_y,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="site/data")
    parser.add_argument("--out", default="site/data/terrain")
    parser.add_argument("--index", default="site/data/terrain.json")
    parser.add_argument("--cache", default="data/raw/terrarium")
    parser.add_argument("--lakes", default="data/raw/us_lakes.geojson")
    parser.add_argument("--key", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--width", type=int, default=1400)
    parser.add_argument("--force", action="store_true", help="re-render nations that already have sheets")
    args = parser.parse_args(argv)

    data_dir = Path(args.data)
    index_payload = json.loads((data_dir / "polities.json").read_text(encoding="utf-8"))
    polities = index_payload["polities"]
    series = json.loads((data_dir / "series.json").read_text(encoding="utf-8"))
    by_key = {polity["key"]: polity for polity in polities}

    targets = list(args.key)
    if args.all:
        ranked = sorted(
            polities,
            key=lambda polity: polity.get("totalArea") or 0.0,
            reverse=True,
        )
        if args.limit:
            ranked = ranked[: args.limit]
        targets = [polity["key"] for polity in ranked]
    if not targets:
        raise SystemExit("pass --key or --all")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = Path(args.index)
    terrain_index: dict[str, list[dict]] = {}
    if index_path.exists():
        terrain_index = json.loads(index_path.read_text(encoding="utf-8"))

    terrain = Terrain(Path(args.cache))
    lakes = load_lakes(Path(args.lakes))
    shard_cache: dict[str, dict] = {}
    started = time.time()

    for key in targets:
        try:
            render_nation(
                key, by_key, series, data_dir, out_dir, index_path, terrain_index, args,
                terrain, lakes, shard_cache,
            )
        except Exception as error:
            log(f"failed {key}: {error}")
    if args.all and not args.limit:
        keep = {
            Path(entry["file"]).name
            for entries in terrain_index.values()
            for entry in entries
        }
        for stale in sorted(out_dir.glob("*.png")):
            if stale.name not in keep:
                stale.unlink()
                log(f"removed stale {stale.name}")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(terrain_index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    log(
        f"wrote {index_path} ({len(terrain_index)} nations, {terrain.downloads} tiles fetched, "
        f"{time.time() - started:.0f}s)"
    )
    return 0


def render_nation(
    key: str,
    by_key: dict,
    series: dict,
    data_dir: Path,
    out_dir: Path,
    index_path: Path,
    terrain_index: dict,
    args,
    terrain: "Terrain",
    lakes: list[tuple[tuple[float, float, float, float], list[list[tuple[float, float]]]]],
    shard_cache: dict,
) -> None:
    polity = by_key.get(key)
    if polity is None:
        log(f"skip {key}: not in dataset")
        return
    intervals = series.get(key, [])
    if not intervals:
        return
    shard_id = polity["shard"]
    if shard_id not in shard_cache:
        shard_path = data_dir / "geom" / f"{shard_id}.json"
        shard_cache[shard_id] = (
            json.loads(shard_path.read_text(encoding="utf-8")) if shard_path.exists() else {}
        )
    shard = shard_cache[shard_id]

    boxes = []
    for item in intervals:
        geometry = (shard.get(item.get("g"), []) or [None] * (item.get("i", 0) + 1))[item["i"]]
        if not geometry:
            continue
        xs: list[float] = []
        ys: list[float] = []
        polygons = (
            [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        )
        for polygon in polygons:
            for ring in polygon:
                for point in ring:
                    xs.append(point[0])
                    ys.append(point[1])
        if xs:
            boxes.append((min(xs), min(ys), max(xs), max(ys)))
    if not boxes:
        return

    existing = terrain_index.get(key)
    if (
        existing
        and not args.force
        and all(entry.get("v") == SHEET_VERSION for entry in existing)
        and all((out_dir / Path(entry["file"]).name).exists() for entry in existing)
    ):
        return

    bbox = nation_sheet_bounds(boxes)
    lon0, lat0, lon1, lat1 = bbox
    mid_lat = math.radians((lat0 + lat1) / 2)
    span_x = max((lon1 - lon0) * 111320.0 * math.cos(mid_lat), 1.0)
    span_y = (lat1 - lat0) * 110574.0
    width = args.width
    height = int(round(width * span_y / span_x))
    if height > 900:
        height = 900
        width = max(300, int(round(height * span_x / span_y)))
    height = max(300, height)

    name = f"{key}.png"
    entry = render(terrain, bbox, width, height, out_dir / name, lakes)
    entry["file"] = f"terrain/{name}"
    entry["v"] = SHEET_VERSION
    terrain_index[key] = [entry]
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(terrain_index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    log(f"{polity['name']}: {width}x{height} sheet, zoom {entry['zoom']}, {entry['interval']:g} m")


if __name__ == "__main__":
    sys.exit(main())
