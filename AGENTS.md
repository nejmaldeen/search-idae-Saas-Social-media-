# AGENTS.md

Operating instructions for any AI agent picking up this repository.

## What this repository is

An evidence-first research system that collects real user complaints from
Saudi/Arabic social platforms and turns them into traceable AI SaaS opportunity
hypotheses. Read `SKILL.md` first — it is the short operating guide.

## Before you touch anything

```bash
pip install -r requirements.txt
python3 -m pytest -q -m "not network"
```

102 tests must pass in a couple of seconds. If they take minutes, credentials
are leaking into the offline suite — that is a bug, not normal.

## Ground rules for working in this codebase

**Never claim something works without running it.** This project's whole value
is that its claims are checked. Six real defects were found only by running the
code against live data; four of those looked correct in review.

**Never fabricate data.** Connectors return `access_status` plus a reason when
they cannot collect. They never return invented items. Keep it that way.

**Silent success is the worst failure mode.** One provider returns
`{"noResults": true}` marker rows; mapping those away quietly reported "ok, 0
items" and would have been read as "the market is empty". See
`is_sentinel_row()` in `oda/connectors/provider.py`. When you add a connector,
ask what its "nothing found" response looks like.

**Keep real and synthetic data apart.** Every collectable row carries
`data_origin` (`real` | `synthetic_fixture`), enforced by a SQL CHECK. Reports
filter on it. There is a test that fails if synthetic rows reach a real report.

**Edits must be verified.** A `str.replace()` that does not match fails
silently and leaves the code untouched while printing success. Assert the match
or use an editing tool that errors on a miss. This bit us once already.

## Architecture in one paragraph

One orchestrator (`oda/orchestrator.py`) runs a fixed pipeline —
`plan_queries → collect → extract → dedupe → cluster → competitors → evaluate →
review_gate` — where each step's status is persisted in `run_steps`, so a run
can stop, fail, or block on a human and resume without re-collecting. There is
no multi-agent framework and no LLM is required: extraction is deterministic
and rule-based (`rules:v1`), so every decision is inspectable and reproducible.

## Where things live

| Path | Responsibility |
|---|---|
| `oda/connectors/` | one module per source; `base.py` defines the contract |
| `oda/connectors/provider.py` | commercial provider (TikTok/Instagram/Snapchat/X/Reddit) |
| `oda/quality.py` | rejects SEO spam, agency copy, bot templates |
| `oda/extract.py` | Arabic + English pain-signal patterns |
| `oda/dedupe.py` | exact, same-author containment, cross-author verbatim |
| `oda/cluster.py` | concept-aware clustering (IDF salient tokens) |
| `oda/evaluate.py` | declared-rubric scoring; facts/inferences/assumptions |
| `oda/verify.py` | the 11-criteria integration verification harness |

## Adding a platform connector

1. Subclass `Connector`; fill `Capability` honestly — `limits` and `tos_notes`
   are read by humans making decisions.
2. **Fetch the provider's real input schema** rather than guessing field names.
   For Apify: `GET /v2/acts/<actor>/builds/default`. Guessing cost us four
   rejected runs.
3. Map engagement through `extract_engagement()`; a missing metric must stay
   absent, never become `0`.
4. Return a non-ok `access_status` with a reason on every failure path, and
   make the message actionable (name the env var that fixes it).
5. Add tests using the actor's **real response shape**, including its error and
   empty responses.

## Cost discipline

Collection costs real money (~$0.68 per 1,000 items, measured). Before widening
a run: filter posts that have zero comments, cap `comments_per_post`, and
prefer re-deriving over re-collecting — stored content is reused automatically
because sources key on `(project, platform, external_id)` and contents on
`(project, content_hash)`.

## What NOT to do

- Do not add a scheduler, queue, or multi-agent layer. The pipeline is
  deliberately simple and resumable.
- Do not treat views or likes as evidence of willingness to pay.
- Do not widen collection to fix thin evidence when the real problem is
  targeting. Searching tutorials returns beginners; searching criticism returns
  paying customers.
- Do not commit `.env`, a database, or exports.
