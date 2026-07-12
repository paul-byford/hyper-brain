---
type: Reference
title: Knowledge bundles and concepts
domain: commons
tags:
- open-knowledge-format
- reference
source: raw-commons
source_url: raw/commons/knowledge-bundles-and-concepts.md
fetched_at: '2026-07-12T09:00:00+00:00'
checksum: b0nd1eb0nd1eb0nd1eb0nd1eb0nd1eb0nd1eb0nd1eb0nd1eb0nd1eb0nd1eb0nd
ingest_run: seed-commons
---

# Knowledge bundles and concepts

The [[Open Knowledge Format]] is built from two simple ideas: bundles and concepts.

## Concepts

A **concept** is a single unit of knowledge: one markdown file. It can describe
something concrete (a document, a dataset, an API) or something abstract (a metric, a
process, a decision). Its **concept id** is just its path without the `.md`, so a file
at `commons/welcome-to-hyper-brain.md` has the id `commons/welcome-to-hyper-brain`.
The frontmatter carries structured fields an agent can query: `type` (the one required
field), `title`, `description`, `resource` (a canonical link), `tags`, and
`timestamp`.

## Bundles

A **bundle** is a directory tree of concepts, shipped as one unit. In Hyper Brain a
domain, like the commons, is a bundle, and the whole corpus is a bundle too.
Directories give an implicit hierarchy, and a reserved `index.md` lists what a
directory holds.

## Relationships

Concepts link to each other with ordinary markdown links, which OKF treats as a
directed graph of the connections between ideas. Hyper Brain authors links as
`[[wikilinks]]` for convenience and rewrites them to standard links on export, so the
graph travels with the bundle. See [[Sharing and collaboration]] for how those links
stay scoped to what you are allowed to see.
