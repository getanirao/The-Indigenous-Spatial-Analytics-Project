# Data directory

## `data/raw/` — not committed

Populated by `pipeline/fetch_cliopatria.py`. Contains the upstream release archive and the
extracted `cliopatria.geojson`. Large and re-downloadable, so it is gitignored.

```
py pipeline\fetch_cliopatria.py            # download + extract
py pipeline\fetch_cliopatria.py --dry-run  # print the resolved download URL and exit
py pipeline\fetch_cliopatria.py --force    # re-download even if the file exists
py pipeline\fetch_cliopatria.py --record 14714684   # pin a different Zenodo record
```

The default record is Cliopatria v0.2.0. The script resolves files through the Zenodo API
(`https://zenodo.org/api/records/<id>`) rather than guessing archive filenames, so it keeps
working across releases.

## Upstream record

Cliopatria is distributed as a single `cliopatria.geojson` of roughly 15,000 features. Relevant
properties:

| Property | Notes |
| --- | --- |
| `Name` | Polity name |
| `FromYear` / `ToYear` | Negative values are BCE |
| `Area` | Recorded polygon area in km² — the metric this project plots |
| `Type` | `POLITY` or `RELATION` (composite, e.g. vassalage or personal union) |
| `Wikipedia`, `Wikidata`, `SeshatID`, `MemberOf` | Identifiers, when known |

Because `Area` is supplied upstream, the build step needs no geometric area computation and no
GIS stack. A spherical-excess fallback exists in `build_site_data.py` for records with a
missing or zero `Area`.

## US cessions (`data/raw/tribal_cessions.geojson`)

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

There is **no acreage column** in the service, so areas are computed geodesically from the
polygons in the build step. Cession boundaries were not surveyed, and the schedule sometimes
describes a reserved tract rather than a ceded one; do not treat the totals as acreage figures.

## Verification

Run the build with `--report` to print record counts, entities with missing area, and the
smallest/largest extents. Use this after any version bump to confirm the input actually changed
in the way you expect before republishing figures.

## The 1492 window

Post-contact scope is a build-time filter, not a data edit: `--min-year` (default `1492`)
clamps any record overlapping the window and excludes the rest. The same `cliopatria.geojson`
can therefore drive a deep-time build (`--min-year -4000`) and a post-contact build without
re-downloading. Cliopatria's post-1492 density varies a lot by region — check the `--report`
counts to see what the window actually leaves you.
