# Data directory

## `data/raw/` — not committed

Populated by `pipeline/fetch_tribal_cessions.py` and gitignored because it is large and
re-downloadable.

```powershell
py pipeline\fetch_tribal_cessions.py           # ~6 MB, 717 polygons
py pipeline\fetch_tribal_cessions.py --force   # re-fetch
py pipeline\fetch_tribal_cessions.py --dry-run # print the service, fetch nothing
```

Queried from the US Forest Service ArcGIS service and joined to Royce's 1899 schedule:

- **Layer 1** — 718 cession polygons, one `cessnum` each.
- **Layer 2** — 725 schedule rows: `schdtrb` (tribes), `presdaytrb` (present-day nations),
  `cessdate1..5` (epoch milliseconds), state/county, citation and treaty links.

The join is on `cessnum`. Dates are epoch milliseconds; note that Python's
`datetime.fromtimestamp()` raises `OSError` on Windows for pre-1970 values, so the fetcher does
the arithmetic explicitly. Polygons with no schedule row or no parseable date are dropped and
counted in the log.

The output is a GeoJSON FeatureCollection of cession polygons carrying `year` and `tribes`:

| Property | Notes |
| --- | --- |
| `year` | Year of the cession, from the first parseable schedule date |
| `tribes` | Signatory nations named in the schedule, one feature may name several |
| `cessnum` | Royce schedule number, useful for tracing a polygon back to the report |

There is **no acreage column** in the service, so areas are computed geodesically from the
polygons in the build step. Cession boundaries were not surveyed, and the schedule sometimes
describes a reserved tract rather than a ceded one; do not treat the totals as acreage figures.

## US state outlines (`data/raw/us_states.geojson`)

```powershell
py pipeline\fetch_us_states.py           # ~2 MB, 51 states and districts
```

Pulled from the Natural Earth 50m admin-1 layer (public domain, CC0) and filtered to the 50
states and the District of Columbia. The build simplifies them and uses them two ways: as the
map backdrop, and to work out which states each ceded tract falls in today.

## Lake outlines (`data/raw/us_lakes.geojson`)

```powershell
py pipeline\fetch_us_lakes.py           # ~240 KB, 188 lakes
```

Pulled from the Natural Earth 50m lakes layer (public domain, CC0) and clipped to the North
American window. Lake surfaces sit above sea level in the elevation tiles, so the relief
renderer scanline-fills these polygons back to water; without them the Great Lakes read as
land.

## Terrain tiles (`data/raw/terrarium/`)

```powershell
py pipeline\build_terrain.py --all      # renders site/data/terrain/*.png
```

Elevation comes from the AWS Terrain Tiles "terrarium" set, which encodes SRTM height in the
RGB of ordinary PNG tiles. The fetcher caches them under `data/raw/terrarium/<z>/<x>/<y>.png`
and decodes them in pure Python, so the relief pipeline needs no image libraries.

## Verification

Run the build with `--report` to print record counts and the largest nations by total ceded
area. Use this after any refetch to confirm the input actually changed in the way you expect
before republishing figures.

## Output

`site/data/` is generated and gitignored; the Pages workflow rebuilds it on every push. See the
data model section of `README.md` for the file layout.
