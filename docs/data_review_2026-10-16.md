# JobAgentWeb data-path review — 2026-10-16

## Executive verdict

JobAgentWeb is broadly consistent with the README's shared/per-user architecture, records the advertised retrieval funnel, and has a sound client-visible fingerprint mechanism. The API-key route is correctly pinned to the configured user and stripped of admin access. Two correctness problems deserve priority:

1. **High — incomplete `catalog_gate` facts are still exposed to scoring and ranking endpoints.** The extraction queue correctly treats them as pending, but `/new-with-descriptions`, `/unscored`, and `/for-ranking` do not require a full extraction. The current JobAgent evaluator consumes `/new-with-descriptions`, so a normal pipeline run can score catalog-only facts.
2. **High — a reused source requisition ID can merge unrelated jobs without corroboration.** The source identity is only `provider:source_id`; the automatic match happens before company, title, or location checks. A tenant-local ID reused by two employers on the same ATS can therefore cause a destructive false merge.

The existing pytest suite could not be executed in this checkout because neither a project virtual environment nor pytest is installed. No skip or xfail markers exist. The configured database was not reachable from this sandbox, so production freshness/backlog remains unverifiable.

## Scope and method

This review traced JobAgentWeb storage, queue, authentication, deduplication, and statistics code, plus the read-only sibling JobAgent client at `/home/tbaranski/code/JobAgent` to determine how the HTTP endpoints are actually consumed. No source was changed. The only repository change is this report.

Line references are to the reviewed checkout. References beginning `../JobAgent` identify the sibling client and are contextual only.

## Area verdicts

### 1. Tests — unverifiable at runtime

- `pytest -q` was unavailable (`pytest: command not found`); `python3 -m pytest -q` failed with `No module named pytest`. Per the task constraints, no packages were installed.
- The suite expects a dedicated remote Postgres instance configured in `tests/conftest.py:1-16`. A direct connection attempt did not succeed in the sandbox.
- There are **no** `pytest.mark.skip`, `skipif`, `pytest.skip`, `xfail`, or module-level skip declarations to interpret.
- Relevant regression coverage exists for canonical URL and requisition dedup (`tests/test_jobs_api.py:108-177`), catalog-tier queueing (`tests/test_jobs_extra.py:144-171`), API-key isolation (`tests/test_auth.py:271-342`), and search-stat persistence (`tests/test_search_stats.py:1-72`). These tests could not provide a pass/fail signal here.
- Historical-risk comments worth retaining are the insert-race/user-state omission in `tests/test_jobs_api.py:10-15` and global-known-URL omission in `tests/test_jobs_extra.py:11-15`; neither is a skip marker.

### 2. Shared versus per-user storage — working

- Shared posting text and extraction artifacts are stored in `job_postings`, `job_posting_aliases`, `job_fact_extractions`, normalized fact tables, and `job_embeddings` (`migrations.py:16-159`).
- `user_job_states` owns status, scores, score/ranking fingerprints, and application intent under a `(user_id, job_id)` uniqueness constraint (`migrations.py:137-159`). Criteria, sessions, CVs, preference profiles, search statistics, exclusions, candidate preferences, usage/cost data, and dismissed score items all carry `user_id` (`migrations.py:164-305`).
- Reads join postings to the caller's state (`jobs_repo.py:29-38`), and writes scope state updates by both `user_id` and `job_id` (`jobs_repo.py:329-357`). A second user reuses a shared posting while receiving an independent state, covered by `tests/test_jobs_api.py:217-225` and following.
- Startup does run the idempotent schema and additive migration sequence under an advisory lock (`migrations.py:428-464`). Columns use `ADD COLUMN IF NOT EXISTS` (`migrations.py:443-445`), retired columns use `DROP COLUMN IF EXISTS` (`migrations.py:510-512`), and checks are deliberately dropped/re-added (`migrations.py:524-532`). This matches the README.

### 3. Deduplication — broken at one automatic-merge boundary; otherwise conservative

**What works**

- URLs normalize scheme/host, strip fragments and known tracking parameters, sort remaining query parameters, and normalize path slashes (`jobs_repo.py:45-77`). A tracking variant such as `http://www.example.com/jobs/42/?utm_source=x` and `https://example.com/jobs/42` becomes the same canonical URL and is reused during insert (`jobs_repo.py:178-207`).
- Content fingerprints include normalized title, company, location, and a sufficiently long description (`jobs_repo.py:91-99`). Company/title identity aliases normalize punctuation, corporate suffixes, and common title variants (`source_identity.py:40-69`).
- Cross-source fuzzy matching first requires compatible locations, then matching company/title identity, and finally description Jaccard similarity (`dedup_repo.py:67-108`). Exact content and high-similarity matches are candidates at confidence 0.94, below the 0.95 automatic threshold (`dedup_repo.py:18-19,96-107`). This is intentionally conservative: identical Greenhouse and LinkedIn copies with different URLs remain reviewable rather than being silently merged (`tests/test_jobs_api.py:146-168`).
- A negative scenario behaves correctly: two “Backend Engineer” roles at the same company/location, one describing Python/Postgres payments and the other Go/ClickHouse observability, have low token overlap and remain separate (`jobs_repo.py:110-115`; `tests/test_jobs_api.py:189-202`). Likewise, different locations and distinct same-source requisitions are explicitly protected (`tests/test_jobs_api.py:171-186`).
- Matching reruns after a description or facts update (`jobs_repo.py:663-683`). Candidate decisions are retained (`dedup_repo.py:166-186`), and automatic consolidation is transactional at the request level through the connection lifecycle (`db.py:23-35`; `dedup_repo.py:460-494`).

**Concrete bug D1 — high severity: tenant-local requisition IDs can false-merge unrelated jobs**

- Trigger: Employer A and Employer B both arrive as `source="greenhouse"`, `source_id="12345"` (or both URLs yield the same extracted ID), but have unrelated titles, locations, and descriptions.
- `requisition_identity` constructs only `greenhouse:12345`; neither ATS tenant nor company is in the key (`source_identity.py:95-109`). `_match_score` returns confidence 1.0 immediately when those keys match, before its same-source, location, company/title, and description checks (`dedup_repo.py:58-70`). Confidence 1.0 exceeds the 0.95 auto-merge threshold, so `deduplicate_job` consolidates them (`dedup_repo.py:460-488`).
- Impact: shared posting facts and every user's states can be moved onto the wrong vacancy. This is a destructive data-integrity failure, not merely a missed duplicate.
- Existing coverage only proves distinct IDs do not fuzzy-merge and uses a company-scoped sample ID (`acme:<token>`); it does not test equal unscoped IDs across tenants (`tests/test_jobs_api.py:121-177`).

**Expected false negative / operational tradeoff**

- The same vacancy syndicated from an ATS to LinkedIn under different URLs and provider-specific IDs will not auto-merge, even with identical content: provider is part of the requisition key and content confidence is 0.94. It is recorded for review rather than lost (`dedup_repo.py:58-108,166-186`). This matches the current README's stated safety policy, but candidates need an actual review workflow or the duplicate remains visible indefinitely.

### 4. Extraction tier — broken

**Queue behavior works:** personal `GET /api/jobs/missing-facts` treats `_extraction_tier=catalog_gate` as incomplete, while the shared catalog queue treats a current-schema row as complete (`jobs_repo.py:505-560`). The focused regression test expresses exactly that contract (`tests/test_jobs_extra.py:144-171`). Fact projections and version metadata are replaced together inside one request transaction (`jobs_repo.py:563-667`).

**Concrete bug E1 — high severity: scoring/ranking can consume catalog-only facts**

- Trigger: a user is attached to a posting whose current `job_fact_extractions.facts` has `_extraction_tier="catalog_gate"`, a non-empty description, and state `new`.
- `/api/jobs/unscored` only checks `score IS NULL` and description presence (`jobs_repo.py:705-714`). `/api/jobs/new-with-descriptions` only checks status and description (`jobs_repo.py:717-726`). `/api/jobs/for-ranking` has the same omission (`jobs_repo.py:842-851`). None joins `job_fact_extractions` or requires a non-catalog extraction.
- The real evaluator loads `/new-with-descriptions` (`../JobAgent/evaluator/runner.py:19-35`) and scores the returned `structured_data` (`../JobAgent/evaluator/fingerprints.py:23-36`; scoring call at `../JobAgent/evaluator/runner.py:84-120`). `update_facts` projects even `catalog_gate` facts into `job_postings.structured_data` (`jobs_repo.py:595-598`). Therefore the client does not compensate for the server-side omission.
- Impact: scores, auto-rejections, and rankings can be based on deliberately incomplete facts before the personal extraction queue is processed.

### 5. Score/ranking fingerprint staleness — working end to end, with a service-enforcement limitation

- JobAgentWeb stores and returns both fingerprints (`migrations.py:137-159`; `jobs_repo.py:15-23,329-390`). It does not calculate them, which is appropriate because prompts, model configuration, candidate context, and implementation live in JobAgent.
- Score fingerprints include the scoring model, system prompt, scoring implementation digest, and job title/company/location/description/source/structured data (`../JobAgent/evaluator/fingerprints.py:23-36`). The system prompt is rebuilt from active CV/profile, criteria, questionnaire, learned preferences, examples, and calibration cases (`../JobAgent/evaluator/runner.py:58-84`). Thus CV/preference edits, job-content edits, prompt changes, model changes, and scorer implementation changes alter the fingerprint.
- The evaluator recomputes fingerprints for every new-status job with a description and re-scores when the stored value differs, even if a score exists (`../JobAgent/evaluator/runner.py:19-35,84-88`).
- Ranking fingerprints include all four relevant model settings; candidate profile, questionnaire, preferences; job content, facts and scores; and hashes of listwise, debate, reranker, fusion, profile, and shared utility implementations (`../JobAgent/evaluator/fingerprints.py:39-64`). The cache refuses reuse on any mismatch (`../JobAgent/ranker/rank_cache.py:15-32`; caller at `../JobAgent/scripts/rank_jobs.py:144-154`). This covers the requested ranking-implementation trigger.
- Limitation: JobAgentWeb is a passive store and will return old scores/ranks and their old fingerprints; it does not know the current expected fingerprint and cannot label them stale. Correctness therefore depends on each consumer comparing fingerprints. The main JobAgent scorer/ranker does so, but generic `/ranked` consumers receive rows without server validation (`jobs_repo.py:899-912`). This matches the README's “clients can detect” claim, but should be made explicit in the API contract.

### 6. API-key authentication boundary — working for the stated boundary; one authorization smell

- Both API-key settings must exist, the secret comparison is constant-time, and a successful key always resolves exactly `JOBAGENT_API_KEY_USER_ID` from the database (`deps.py:10-22`). A deleted/missing configured user does not authenticate through the key and falls through to the normal session path (`deps.py:24-36`). It cannot select a user ID from request input.
- Key-authenticated requests are marked `trusted_client`; `require_admin` denies them before checking the database admin flag (`deps.py:39-44`). Thus even a configured admin account cannot use the key on `/admin`. The admin router consistently depends on `require_admin` (`routers/admin.py:12-30`). Tests cover wrong/missing keys, exact user scoping, deleted IDs, admin-account scoping, and genuine admin sessions (`tests/test_auth.py:275-342`).
- A malformed non-integer configured user ID can raise a server error at `int(...)` (`deps.py:17,50`), but it does not grant access.

**Concrete issue A1 — medium severity: browser sessions for the configured user can call automation-only catalog endpoints**

- `require_automation_client` accepts either a request marked as key-authenticated **or any normal session whose user ID equals** `JOBAGENT_API_KEY_USER_ID` (`deps.py:47-52`). Consequently the configured user's browser session can insert shared-only catalog jobs and replace shared facts through endpoints guarded by that dependency (`routers/jobs.py:178-238,294-302`).
- This does not violate the specific “API key cannot reach admin or impersonate another user” promise, but it weakens the apparent “API-key-only shared collection” contract in README.md and increases the blast radius of a stolen session cookie.

### 7. Search statistics funnel — working, with honest fallbacks rather than universal stage visibility

- The Web model, router, repository insert, and summary preserve `upstream_found`, `query_matched`, `date_matched`, `geo_matched`, `cards_found`, and `new_found` without renaming or reordering (`models.py:245-262`; `routers/search_stats.py:11-20`; `search_stats_repo.py:4-22,25-54`).
- In the collector, each source search resets diagnostics, source-specific filtering supplies the upstream/query/date/geo counters, the global title-query filter then determines `cards_found`, insertion outcomes determine `new_found`, and all values are posted together (`../JobAgent/collector/runner.py:303-397`). The source implementations actively set diagnostics; representative staged increments are in `../JobAgent/collector/sources/remotive.py:66-120`.
- This trace makes the meanings concrete: `upstream_found` is the fetched population, source-level query/date/geo stages narrow it, `cards_found` is after the collector's global query matcher, and `new_found` is successful inserts. Additional counters distinguish source returns, known URLs, global matches, duplicates, and inserts.
- When a source cannot expose a stage, runner defaults that stage to `len(raw_jobs)` (`../JobAgent/collector/runner.py:383-394`), and historical NULL rows are similarly coalesced to `cards_found` in summaries (`search_stats_repo.py:35-43`). Therefore the funnel is internally consistent but not proof that every source measured every stage. An explicit “observed/defaulted” mask would prevent false precision.

### 8. Data freshness and extraction backlog — unverifiable

- Runtime configuration defaults to local Postgres and reads credentials from environment (`config.py:5-13`; `db.py:12-19`). No usable database credentials were configured in this worktree environment.
- The only explicit test connection is the dedicated remote test database in `tests/conftest.py:1-16`; it was unreachable from the sandbox. Production credentials were neither present nor sought elsewhere.
- Consequently this review cannot report `MAX(job_postings.created_at)`, `MAX(job_postings.updated_at)`, extraction recency, or the count/age of postings missing current full facts. Code inspection alone cannot establish whether the live extractor is keeping pace.

## Prioritized improvement plan

1. **P0 — Enforce full facts on every personal scoring/ranking feed (small).** Centralize an eligibility predicate requiring a current-schema `job_fact_extractions` row whose tier is not `catalog_gate`, and apply it to `/unscored`, `/new-with-descriptions`, `/for-ranking`, and any force-rescore feed. Add an end-to-end regression showing a gate-only posting is absent until full facts replace it. This prevents immediate bad scores and auto-rejections.
2. **P0 — Make requisition identity tenant-aware and corroborated (medium).** Build ATS identity from provider + tenant/account + requisition ID where available. Before automatic merging, require compatible company/title (and preferably location) even for equal IDs; treat conflicts as candidates. Backfill aliases and audit existing auto-merges for cross-company/title conflicts. This addresses the destructive false-merge path.
3. **P1 — Run and gate on the full suite in a reproducible environment (small).** Provide a checked-in test command/container or documented virtualenv bootstrap and run it in CI against disposable Postgres. Preserve explicit tests for the two findings above. The current checkout cannot independently establish a green baseline.
4. **P1 — Restrict automation endpoints to actual key authentication (small).** Remove the configured-user session shortcut from `require_automation_client`, or split “same user” and “trusted automation” dependencies deliberately. Validate `JOBAGENT_API_KEY_USER_ID` at startup so malformed configuration fails clearly.
5. **P1 — Add freshness/backlog observability (medium).** Publish metrics/dashboard queries for newest posting, newest description/facts, total recent postings, missing facts, gate-only facts, stale schema/content hashes, and oldest pending age. Alert on age and percentage thresholds, not only raw count.
6. **P2 — Make dedup candidate review operational (medium).** Add an authenticated review surface or scheduled workflow, age/SLA metrics, and reasons/evidence display. Without resolution, the deliberately conservative cross-source strategy accumulates user-visible duplicates.
7. **P2 — Make funnel provenance explicit (small).** Record which stage counters were directly observed versus defaulted, enforce nonnegative/monotonic invariants where applicable, and add source-contract tests. This keeps dashboards from presenting fallback equality as measured recall.
8. **P2 — Document fingerprint ownership and consumer rules (small).** State that Web stores opaque fingerprints and may serve stale rows, while every consumer must compute the current expected value before reuse. Consider an API field such as `fingerprint_match` only if the client can supply the expected fingerprint.
9. **P3 — Expand adversarial property tests (medium).** Cover canonicalization collisions, same ATS ID across tenants, missing/ambiguous locations, repeated description templates, merge rollback, overlapping user states, and concurrent inserts/late dedup. These cases carry more value than additional happy-path examples.

## Verification limitations

- No pytest runtime was available, and dependencies were not installed.
- The configured test Postgres endpoint was unreachable; no live or test database freshness/backlog query succeeded.
- No production environment or network service was accessed.
- The sibling JobAgent repository was readable and used only to trace client behavior; it was not modified and its separate test suite was not run.

