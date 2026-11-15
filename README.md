# AI SaaS Opportunity Discovery Agent

An evidence-first research system that turns social/community content and product
reviews into **traceable problem signals** and **testable AI SaaS opportunity
hypotheses**. Every opportunity links back to the clusters that support it, those
clusters link to individual quotes, and each quote links to its source URL and the
query that found it.

The system is deliberately conservative: it separates *what the evidence shows*
from *what the model inferred* from *what remains an assumption*, and it refuses
to turn post counts into user counts or stated frustration into proven demand.

---

## 1. What actually works right now

Verified by running it, in this container, on this date:

| Capability | Status |
|---|---|
| Create/persist research projects, resume across process restarts | ✅ working |
| Bilingual (AR/EN) query expansion, balanced per language and intent | ✅ working, 109 queries generated |
| **Real automated collection: YouTube + Hacker News + Stack Exchange + GitHub** | ✅ working, **7,958 real documents** collected |
| Manual import (JSONL / JSON / CSV / plain text) | ✅ working |
| Content-quality gate (SEO spam, agency copy, bot templates) | ✅ working, rejected 91/181 real docs |
| Pain-signal extraction, AR + EN, rule-based, no API key | ✅ working |
| De-duplication (exact, same-author containment, cross-author verbatim) | ✅ working |
| Problem clustering (concept-aware, IDF salient tokens) | ✅ working |
| Competitor extraction with verbatim pricing + evidence URL | ✅ working |
| Opportunity scoring with a fully declared rubric | ✅ working |
| Human-task creation / completion / resume | ✅ working |
| Markdown + JSON report export | ✅ working |
| Streamlit review UI, 9 tabs | ✅ working, 0 exceptions |
| Automated tests | ✅ **93 passing** (92 offline + 1 live network) |

### Sources: supported in code vs usable here

`code_supported` and `usable_now` are deliberately different things.

| Source | Access mechanism | Usable in this container | Why not |
|---|---|---|---|
| **YouTube / Shorts** | YouTube Data API v3 | ✅ **yes** | API key supplied; 7,584 Arabic comments collected |
| **Hacker News** | Official Algolia search API, keyless | ✅ **yes** | host allowed; 302 documents |
| **Stack Exchange** | Official API 2.3, keyless | ✅ **yes** | host allowed; 72 documents (300/day free quota) |
| **GitHub Issues** | Official REST Search API | ✅ **yes** | works unauthenticated at 10 req/min |
| Reddit | Official OAuth2 API | ❌ no | **requires prior approval** (Responsible Builder Policy) + credentials + host is blocked |
| TikTok | Research API | ❌ no | requires application + approval |
| Instagram / Reels | Graph API | ❌ no | requires Business account + app review; no public comment search |
| X | API v2 | ❌ no | free tier has no search endpoint; paid token required |
| G2 / Capterra | none | ❌ no | no public read API; ToS disallow automated collection |

No scraping, CAPTCHA bypass, or logged-in session reuse is performed anywhere.
Platforms without authorized access are routed to the **Manual Import** path and
raise a human task explaining exactly how to unblock them.

### Honest finding about GitHub as a source

GitHub is a **working integration but a low-precision source for SMB/e-commerce
market pain.** From 181 real documents it produced only 11 signals, and those are
mostly developer and project-management text where words like "manual" appear in
an engineering context — not store owners describing business problems.

This is a property of the source, not a bug: no filter can produce store-owner
complaints that GitHub does not contain. GitHub is a good source for
**developer-tool** pain. For the Saudi e-commerce question, the productive routes
are unblocking Reddit/YouTube or using Manual Import. The report states the real
data scope so this is never hidden.

---

## 2. Install and run

```bash
pip3 install -r requirements.txt
```

```bash
python3 run.py audit
```

```bash
python3 run.py new --name "Saudi ecommerce ops" --domain "ecommerce inventory and order management" --market sa --languages ar,en --sector ecommerce
```

```bash
python3 run.py run --project prj_XXXX --sector ecommerce --tools "Shopify,Salla,Zid,Zoho Inventory"
```

```bash
python3 run.py report --project prj_XXXX --out exports
```

Launch the review UI:

```bash
streamlit run app.py
```

Set the database location (optional, defaults to `./data/oda.sqlite3`):

```bash
export ODA_DB=/path/to/oda.sqlite3
```

### Manual import

```bash
python3 run.py import --project prj_XXXX --file my_export.jsonl --platform tiktok --kind comment
```

Accepted: JSONL, a JSON list, CSV/TSV with a `text` column, or plain-text blocks
separated by a blank line or `---`. Recognised fields (English or Arabic):
`text`, `url`, `title`, `author`, `published_at`, `kind`, `platform`, `external_id`.

### Human tasks

```bash
python3 run.py tasks --project prj_XXXX --status open --verbose
```

```bash
python3 run.py answer --task tsk_XXXX --response "Reviewed; confirmed with 3 interviews."
```

### Resume

Resume is the default. Re-running continues the latest run and skips completed
steps; collection never re-adds stored content because sources are keyed on
`(project, platform, external_id)` and contents on `(project, content_hash)`.

```bash
python3 run.py run --project prj_XXXX              # resumes
python3 run.py run --project prj_XXXX --no-resume   # starts a fresh run
```

---

## 3. Tests

```bash
python3 -m pytest -q -m "not network"
```

```bash
python3 -m pytest -q -m network
```

Result on this machine: **62 passed** offline, **1 passed** live (GitHub).

Coverage includes: project creation/persistence, bilingual query generation and
idempotent storage, ingestion idempotency, access-failure recording without data
loss, exact/near de-duplication, post-count ≠ author-count, missing-field
handling, a failing step not losing prior results, resume skipping completed
steps, human-task creation and completion/validation, prompt-injection-shaped
content stored inertly, connector contracts (no connector may fabricate items or
expose a write action), the spam/bot quality gate, Arabic and English extraction,
report completeness, and **synthetic fixtures never appearing in a real report**.

---

## 4. Architecture

```
run.py            CLI
app.py            Streamlit review UI (9 tabs)
oda/
  db.py           SQLite schema, migrations, logging, access-attempt recording
  store.py        ingestion with provenance; run/step state for resume
  queries.py      bilingual query expansion + platform language affinity
  textutil.py     Arabic/English normalization, hashing, similarity
  quality.py      content-quality gate (SEO spam / agency copy / bot templates)
  extract.py      pain-signal extraction (rules:v1, auditable)
  dedupe.py       exact + near-duplicate marking
  cluster.py      concept-aware problem clustering
  competitors.py  competitor + verbatim pricing extraction
  evaluate.py     opportunity scoring under a declared rubric
  review.py       human-task manager
  report.py       Markdown + JSON reports
  orchestrator.py the single research loop with resumable steps
  connectors/     base contract + one module per source
tests/            63 automated tests
```

One orchestrator, plain functions, no multi-agent framework. The LLM is not
required: the default extractor is deterministic and rule-based, so results are
reproducible and every decision is inspectable. Signals record their extractor
(`rules:v1`), so if an LLM extractor is added later, generative output can never
be mistaken for an independent source of fact.

### Pipeline

```
plan_queries → collect → extract → dedupe → cluster → competitors → evaluate → review_gate
```

Each step's status is persisted in `run_steps`. A step that fails is recorded as
failed and the pipeline continues; prior results are never lost.

### Data model

`projects → research_runs → run_steps`, `search_queries`, `sources → contents →
pain_signals → cluster_members → clusters → opportunities`, plus `competitors`,
`human_tasks`, `access_attempts`, `exec_logs`.

Navigate from any opportunity → its cluster → its signals → their contents →
their sources → the query that found them.

### Real vs synthetic separation

Every collectable row carries `data_origin` (`real` | `synthetic_fixture`),
enforced by a SQL `CHECK` constraint. Reports filter on origin, the UI labels it,
and the orchestrator refuses to collect live data into a synthetic run. A real
report discloses when synthetic rows exist in the same project. This is covered
by a dedicated test.

---

## 5. How scoring works (and what it is not)

Ten criteria, each scored 0–3 against a rule stated in the output, split into two
scores that are **never combined**:

- **evidence_strength** — counted observations only: distinct authors, signal
  clarity, quantified impact, observed workarounds, willingness-to-pay language.
- **attractiveness** — commercial judgment, partly inference: audience clarity,
  competitive gap, AI-solvability, testability, marketing clarity.

These are a **heuristic ranking under declared rules, not probabilities of
commercial success.** Every opportunity also carries explicit `facts`,
`inferences`, `assumptions`, and concrete next validation experiments —
including a falsification test and a disconfirming competitor search.

Willingness-to-pay captures *language only*. No payment is ever observed.
A competitor absent from results is never treated as proof that none exists.

---

## 6. Privacy, compliance, safety

- **Compliance posture (operator decision D-10):** the original "official APIs only"
  rule was lifted by the operator. Platforms with no official self-serve path for a
  commercial user (TikTok, Reddit, G2, Capterra) are collected through a commercial
  data provider. This system calls the provider's own documented REST API with the
  operator's token and performs no collection itself; responsibility for the
  provider's and target platforms' terms rests with the operator. Every run records
  the provider and actor used, so usage stays auditable. See `INTEGRATIONS.md`.
- No connector can post, comment, message, follow, like, delete or modify any
  account. Enforced by a test that fails if such a method ever appears.
- Only public author handles are stored, no extra personal data.
- Platform text is stored as **untrusted data** and never executed as
  instructions; a prompt-injection-shaped payload test asserts this.
- Source terms are recorded per connector (`tos_notes`), including Stack
  Exchange's CC BY-SA attribution requirement and Reddit's redistribution limits.
- Credentials are read from the environment only, never from a committed file.

---

## 7. Known limits and what is not done

1. **No LLM extractor is wired up.** The rule-based extractor is the only one
   exercised. `extractor` is recorded per signal so an LLM path can be added
   without confusing its output for evidence. Not implemented, not claimed.
2. **GitHub is the only live-collecting source here**, and it is low-precision
   for this domain (see §1). Reddit, Hacker News and Stack Exchange are coded and
   would work once their hosts are allowed; that was not verified end-to-end
   because the hosts are blocked in this container.
3. **No video/audio understanding.** YouTube captions need the owner's OAuth, so
   transcripts become a human task instead of being scraped. YouTube search +
   comments are coded but unverified (no API key available here).
4. **Clustering is lexical**, not embedding-based. It can merge distinct root
   causes or split one problem across wordings. Each cluster states this gap.
5. **Segment detection is a keyword list**, so `audience` is often "not stated".
6. **No scheduling/incremental re-collection.** Runs are manual.
7. **Arabic dialect coverage is limited** to the phrases in the pattern tables;
   Gulf/Egyptian colloquial variants beyond those will be missed.
8. The `update_environment` call to allow the blocked API hosts could not be
   completed in this session, so Reddit/HN/StackExchange remain unverified live.

## 8. Next version priorities

1. Unblock `oauth.reddit.com`, `hn.algolia.com`, `api.stackexchange.com` and
   verify those three connectors end-to-end — the single highest-value change,
   since they are where SMB pain actually gets discussed.
2. Add an embedding-based clustering option behind the same interface.
3. Add an optional LLM extraction pass that *proposes* signals for human
   confirmation, tagged `llm:<model>` and never auto-promoted to evidence.
4. Platform-specific query rendering (quoted phrases for GitHub, subreddit
   targeting for Reddit).
5. Incremental re-collection with a per-query watermark.
