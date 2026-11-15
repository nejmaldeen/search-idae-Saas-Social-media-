# Acceptance Criteria — verified status

Verified by execution on 2026-11-15 in the session container. Test results are
from actual runs, not assertions about code.

| ID | Criterion | Status | Evidence |
|---|---|---|---|
| AC-01 | Create and persist a research project | ✅ **met** | `test_ac01_project_created_and_persisted`; CLI `run.py new` used throughout |
| AC-02 | Enter a market/niche and generate bilingual queries | ✅ **met** | 109 queries generated (49 AR / 60 EN); `test_ac02_bilingual_queries_generated`, `test_expand_is_bilingual_and_balanced` |
| AC-03 | Collect from a real authorized integration, or import real user content | ✅ **met** | **181 real documents** collected live from GitHub Issues REST API; manual import verified for JSONL/JSON/CSV/text |
| AC-04 | Every extracted problem links to reviewable evidence | ✅ **met** | `test_full_pipeline_on_fixture_produces_evidence_backed_output` asserts every cluster has evidence with quote + source + stated limits |
| AC-05 | De-duplication prevents obvious inflation | ✅ **met** | exact + same-author containment + cross-author verbatim; `test_exact_duplicate_signals_are_marked`, `test_different_authors_same_problem_are_not_merged_as_duplicates`, `test_post_count_is_not_author_count` |
| AC-06 | Problem clusters, competitors and opportunities displayed in an organized way | ✅ **met** | 9-tab Streamlit UI renders with 0 exceptions (`test_app_renders_all_tabs_without_exception`); Markdown + JSON reports exported |
| AC-07 | System separates evidence, inferences and assumptions | ✅ **met** | `facts` / `inferences` / `assumptions` are separate JSON columns, asserted disjoint in tests; rendered as three columns in UI and three sections in the report |
| AC-08 | A blocked source records the reason and allows a human task | ✅ **met** | `test_ac08_blocked_source_logs_reason_and_creates_human_task`; `access_attempts` table; task de-duplication verified |
| AC-09 | Close, reopen and continue saved research without losing results | ✅ **met** | Demonstrated across 4 separate OS processes: same `run_id` reused, `skipped: ['plan_queries']`, content count unchanged. `test_ac09_resume_skips_completed_steps_and_keeps_data` |
| AC-10 | Export a report with problems, sources, opportunities and next experiments | ✅ **met** | `exports/report_prj_6a78a2a1eb6b.md` (74 KB) + `.json` (107 KB); `test_ac10_report_contains_problems_sources_opportunities_and_experiments` checks all six sections |
| AC-11 | Automated tests for core functions, with real run results | ✅ **met** | **63 tests: 62 passing offline + 1 passing live-network.** Command and output in README §3 |
| AC-12 | No publishing, messaging or account modification without consent | ✅ **met** | No connector implements any write path; `test_ac12_no_write_actions_exist_on_connectors` fails if one ever appears |

## Additional guarantees verified beyond the criteria

| Guarantee | Evidence |
|---|---|
| Synthetic fixtures never contaminate a real report | `test_synthetic_data_never_appears_in_a_real_report`; SQL `CHECK` on `data_origin`; orchestrator refuses live collection into a synthetic run |
| Platform text treated as untrusted data, not instructions | `test_untrusted_platform_text_is_stored_not_executed` |
| A failing pipeline step does not lose prior results | `test_failing_step_does_not_lose_previous_results` |
| Connectors never fabricate items when unavailable | `test_connectors_without_credentials_report_not_authorized_and_return_no_items` |
| SEO spam / agency copy / bot templates excluded from evidence | 91 of 181 real documents rejected with recorded reasons; 6 quality-gate tests |
| Competitor absence never presented as proof of no competition | `test_competitor_absence_is_never_proof_of_no_competition` |

## Not met / not attempted — stated explicitly

| Item | Status | Reason | What completing it needs |
|---|---|---|---|
| Live Reddit / Hacker News / Stack Exchange collection | ❌ **not verified** | Hosts blocked by this environment's network policy (403 on CONNECT). Connectors are written and unit-tested but never ran against the live APIs | Allow `oauth.reddit.com`, `www.reddit.com`, `hn.algolia.com`, `api.stackexchange.com`; add Reddit client id/secret |
| Live YouTube collection | ❌ **not verified** | `www.googleapis.com` is reachable but no `YOUTUBE_API_KEY` is available | Supply an API key |
| TikTok / Instagram / X collection | ❌ **not available** | Require developer approval and/or paid tiers | Apply for access, or use Manual Import |
| G2 / Capterra collection | ❌ **not available by any authorized means** | No public read API; ToS disallow automated collection | Manual Import only |
| LLM-based extraction | ❌ **not implemented** | Rule-based extractor is the only one exercised; no LLM path was wired up or tested | Implement an `llm:<model>` extractor behind the existing `extractor` field |
| Video/audio transcript understanding | ❌ **not implemented** | Captions require the video owner's OAuth | Human task routes this to manual review by design |
| Embedding-based clustering | ❌ **not implemented** | Clustering is lexical (IDF + token overlap) | Add an embedding backend behind the same interface |
| Allowing the blocked hosts from inside this session | ❌ **failed** | The `update_environment` tool call could not serialize its host-list argument | User can allow the hosts in the environment's network settings |
