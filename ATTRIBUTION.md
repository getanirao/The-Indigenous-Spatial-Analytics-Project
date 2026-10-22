# Attribution

Every visualization, derived dataset, and SVG exported from this repository is a *derived
work* of the source below. Attribution is a license condition, not a courtesy: include the
block below (or its equivalent) anywhere our output is republished, including Wikimedia
Commons file pages.

## Required credit

> **Data:** Royce, C. C. (1899). *Indian Land Cessions in the United States.* Eighteenth
> Annual Report of the Bureau of American Ethnology, Smithsonian Institution. Digitised and
> georeferenced by the U.S. Forest Service with Claudio Saunt — public domain (U.S. Government
> work).
>
> **Figure:** *The Indigenous Spatial Analytics Project*,
> https://github.com/getanirao/The-Indigenous-Spatial-Analytics-Project — licensed CC BY-SA 4.0.

## Sources

| Source | Version / date | License | Used for |
| --- | --- | --- | --- |
| [Tribal Ceded Lands](https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_TribalCessionLands_01/MapServer) (US Forest Service) | 2018 revision | Public domain (US Government work) | Cession polygons, dates, signatory nations |
| Royce, *Indian Land Cessions in the United States* (1899) | [LOC 13023487](https://www.loc.gov/item/13023487/) | Public domain | Underlying schedule and maps |
| Claudio Saunt, "Indian Land Cessions" digital companion | 2018 | Public domain (US Government work) | Georeferencing and schedule join |

## License compatibility

Both the Forest Service digitisation and Royce's 1899 report are U.S. Government works and are
public domain in the United States, so they impose no upstream restriction. They are still
credited explicitly: the digitisation is someone's labour, and the 1899 schedule carries its
own interpretive choices.

This repository releases its figures and derived data under CC BY-SA 4.0. That choice is ours,
not an upstream obligation. Do not relicense our output as public domain or CC BY 4.0 "to
simplify" reuse; keep the share-alike term and the credit block intact.

This project does **not** use any NonCommercial (NC) or NoDerivatives (ND) dataset; those are
not accepted on Wikimedia Commons, and several Indigenous mapping projects are NC-licensed.
Check before adding a source.

## When a source changes

Record the version in `site/data/polities.json` (`meta.source`) so any published SVG can be
traced back to the exact release it came from. If the Forest Service republishes the cession
layer, figures generated from the old one should be re-generated rather than silently edited.
