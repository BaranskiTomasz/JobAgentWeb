# Server-side catalog collection

The application starts an APScheduler background scheduler during FastAPI lifespan
startup, registering two interval jobs against `main.py`'s
`_run_scheduled_catalog_collection`:

- **Daily, full catalog** — every 24 hours from process startup, rotating two
  catalog queries by `date.today().toordinal()`.
- **Every 2 hours, `ashby`/`greenhouse`/`lever` only** (`main.py`'s
  `_FREQUENT_POLL_SOURCES`/`_FREQUENT_POLL_INTERVAL_HOURS`) — these three pull a
  full company board from a public JSON API with no browser scraping, so a new
  posting reaches the catalog within 2h instead of waiting for the next daily
  run. This frequent job passes `scoped_extraction=True`
  (`collectors/catalog_runner.py::run_catalog_collection`), so it only extracts
  facts for *its own* newly-found jobs rather than re-running the full-catalog
  extraction backlog catch-up every 2 hours; `attach_catalog_for_all_users`
  still runs unconditionally after every collection (daily or frequent), since
  it's DB-only and is the step that actually makes an extracted posting visible
  to users.

Both jobs share one `app.state.catalog_collection_running` flag
(`_run_catalog_collection_tracked`) with a check-then-set guard, so if the
daily and 2-hourly runs ever overlap, the second one skips cleanly instead of
racing the first's `known_urls` snapshot. The trusted JobAgent automation
client can also request an immediate (daily-style, full-catalog) run with
`POST /api/catalog/collection/run-now` and check its progress with
`GET /api/catalog/collection/status`. An immediate run shifts the daily
interval job's next automatic occurrence to 24 hours after that run; a request
received while collection is already running leaves the existing schedule
unchanged.

Set `ANTHROPIC_API_KEY` in the server environment. `CLAUDE_CATALOG_EXTRACT_MODEL`
optionally overrides the default catalog extraction model. Run one collection
immediately from the deployed application environment with:

```sh
python scripts/run_catalog_collection.py
```

The task writes source funnel statistics with a null `user_id`, because shared
catalog collection is not owned by an individual account.

After catalog extraction completes, public jobs are attached to every user with
active candidate preferences when the catalog work country matches one of the
user's remote countries. Attachment covers every catalog category and is
idempotent. To backfill existing catalog jobs once, run:

```sh
python scripts/backfill_catalog_attachment.py
```
