# Reference corpus provenance

This directory contains writing examples for retrieval-augmented story generation. References
teach structure and completeness; they are never authoritative evidence for a user's product.

## `public_samples.json`

Three short records come from:

> Stefan Schwedt (2025), **Data and results for “From Bugs to Benefits: Improving User
> Stories by Leveraging Crowd Knowledge with CrUISE-AC”**, version 4, `User stories
> e-commerce.xlsx`, DOI
> [10.5281/zenodo.14709846](https://doi.org/10.5281/zenodo.14709846).

The dataset record declares **Creative Commons Attribution 4.0 International (CC BY 4.0)**.
The included records retain creator, dataset, workbook, project, row ID, DOI, license, and
source URL attribution. Text labelled `QUALITY NOTE` is an original Requirements Alchemist
annotation, not part of the source dataset.

Useful larger datasets that are **not bundled**:

- [TAWOS](https://github.com/solar-group/tawos): over 450,000 public Jira issues, dataset
  project published under Apache-2.0; consult its terms of use and upstream-project licenses.
- [User stories dataset for effort estimation](https://data.mendeley.com/datasets/v42jh4nfzh/1):
  CC BY 4.0; verify field quality and source suitability before ingestion.
- [Dalpiaz requirements datasets](https://zenodo.org/records/13880060): the record declares
  CC BY 4.0, but its curator explicitly notes uncertainty about rights in some gathered source
  stories; retain as link-only unless legal review accepts that provenance.

## `quality_patterns.json`

These are original synthetic examples authored for Requirements Alchemist and dedicated under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). They demonstrate details that a
strong story may cover: boundaries, negative behavior, security, accessibility, concurrency,
privacy, observability, measurable NFRs, and unresolved decisions.

They deliberately use generic fictional contexts. Their rules and thresholds must never be
copied into a generated product backlog unless the user's own evidence supports them.

## Human-approved references

The app writes approved examples under `user/`. Those records are organization-supplied
content, marked `user-supplied`, and must be governed by that organization's data,
confidentiality, retention, and intellectual-property policies.
