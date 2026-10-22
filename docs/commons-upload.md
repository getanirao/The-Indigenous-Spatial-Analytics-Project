# Uploading to Wikimedia Commons

Commons has hard rules that decide whether a file can stay up. Getting these wrong gets the
upload deleted, so work through this checklist per file rather than in bulk.

## 1. License eligibility

Commons only accepts licenses that permit **commercial use and derivative works**. Two
consequences for this project:

- **CC BY-SA 4.0 is fine** for our figures. It is the license declared in [LICENSE](../LICENSE).
- **CC BY-NC anything is not.** Several Indigenous mapping projects are NonCommercial; their
  output **cannot** go on Commons, no matter how open it looks. Check `ATTRIBUTION.md` and the
  upstream record before you render.

Cession figures are built on U.S. Government works (Royce 1899; the Forest Service digitisation
with Claudio Saunt), which are public domain in the United States. They are freely uploadable,
but credit them anyway — the digitisation is someone's labour, and the 1899 schedule carries its
own interpretive choices. The CC BY-SA 4.0 label on our figures is our choice as a project, not
an upstream obligation.

## 2. Attribution is a condition, not a courtesy

Use the credit block from [ATTRIBUTION.md](../ATTRIBUTION.md). Both parts are required: the
upstream source *and* the adaptation (this project). A figure missing either is a license
problem, not a style issue.

## 3. File naming

```
<Nation> cumulative land ceded.svg
<Nation> ceded by <year>.svg
```

Prefer ASCII and the nation's common English name. Avoid "final", "v2", "corrected" — upload a
new revision instead so the history stays intact.

## 4. Information template

```
{{Information
|description={{en|1=Land ceded by the [[:en:Cherokee|Cherokee]] up to 1866, accumulated from
the Royce schedule of Indian land cessions (1899), digitised by the U.S. Forest Service.
Cessions are recorded at uneven intervals and the line is therefore a step function. Areas are
computed from the digitised polygons, not from surveyed acreage, and a cession shared by
several nations is credited in full to each.}}
|date=2026-10-22
|source={{own}}, derived from Royce, C. C., Indian Land Cessions in the United States (1899),
digitised by the U.S. Forest Service and Claudio Saunt (public domain)
|author=The Indigenous Spatial Analytics Project
|other_versions=
}}
```

Then add the license tag and the upstream attribution:

```
== {{int:license-header}} ==
{{self|cc-by-sa-4.0}}
{{PD-USGov-USDA-FS}}
{{Attribution-Royce-Cessions}}
```

`{{Attribution-Royce-Cessions}}` will not exist yet — either create that template with the
credit block, or paste the plain-text attribution into the file page. Prefer a template: it
keeps every figure consistent when the source is revised.

## 5. Categories

Verify exact names on Commons before saving; category names drift.

- `[[Category:Maps of the Indian land cessions]]`
- `[[Category:Land cessions by the United States]]`
- `[[Category:Area charts]]`
- A nation category, e.g. `[[Category:Cherokee]]`

## 6. Technical requirements

- **Text must be real text, not outlines.** Our exporter emits `<text>` elements, so
  [SVG Translate](https://commons.wikimedia.org/wiki/Commons:SVG_Translate) can localise labels.
  Never convert to paths.
- **No scripts, no external references.** Our SVGs are self-contained; do not add JavaScript to
  animate them on Commons.
- **Embedded `<metadata>` is permitted** and already carries source, version and license.
- **State the limitations in the description.** Royce's cession boundaries were never surveyed,
  and the schedule sometimes describes a *reserved* tract rather than a ceded one. Say so: a
  chart that reads like a survey is misleading. Also note that areas are computed from digitised
  polygons and that a cession shared by several nations is credited in full to each.
- **Watch file size.** Keep under ~10 MB. Keep `--cession-tolerance` small, or small cessions
  collapse to nothing.

## 7. Not suitable for Commons

- Interactive or JavaScript-driven pages — those belong on the GitHub Pages site, which Commons
  can link to from the file page (`|other_versions=` or the description).
- Anything aggregating overlapping nations into a single "national total" without a stated
  overlap policy.
- Anything built on NC-licensed Indigenous datasets. Publish those on the site with the
  upstream terms instead.
