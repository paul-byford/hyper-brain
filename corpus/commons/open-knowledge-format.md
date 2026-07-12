---
type: Guide
title: Open Knowledge Format
domain: commons
tags:
- open-knowledge-format
- interoperability
- getting-started
source: raw-commons
source_url: raw/commons/open-knowledge-format.md
fetched_at: '2026-07-12T09:00:00+00:00'
checksum: 0kf10kf10kf10kf10kf10kf10kf10kf10kf10kf10kf10kf10kf10kf10kf10kf1
ingest_run: seed-commons
---

# Open Knowledge Format

Hyper Brain stores everything it knows in the **Open Knowledge Format** (OKF),
Google's open, vendor-neutral standard for portable, agent-readable knowledge. If you
can read a markdown file, you can read our corpus; if you can `git clone` a repo, you
can take your knowledge with you.

## What OKF is

OKF is deliberately minimal: a knowledge base is a directory tree of markdown files,
and each file is one **concept** with a little YAML frontmatter on top. The only
required field is `type` (this page is a `Guide`); everything else, such as the title,
tags, and where a fact came from, is recommended but optional. See
[[Knowledge bundles and concepts]] for the building blocks.

## Why it matters for a team

Most context tools lock knowledge inside a proprietary system. OKF is a format, not a
service, so your curated context is never trapped: it is plain files you own, readable
by any editor, any search tool, any agent, and the wider OKF ecosystem, including
Google's Knowledge Catalog. That portability is what makes shared curation worth
investing in, which is the whole point of [[Writing good notes]].

## How Hyper Brain uses it

Every note you create, however it arrives, is written as a conformant OKF concept: a
`type`, a title, tags, its provenance, and `[[wikilinks]]` to related concepts that
form the knowledge graph. You can export any space as an OKF bundle to hand to another
tool, and import a bundle from elsewhere through the studio. Nothing about your
knowledge is one-way or one-vendor. New joiners should start at
[[Welcome to Hyper Brain]].
