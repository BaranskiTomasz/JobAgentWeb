# Server-side catalog collection

The application starts an APScheduler background scheduler during FastAPI lifespan
startup. It runs `collectors.catalog_runner.run_catalog_collection` every 24 hours
from process startup, rotating two catalog queries by `date.today().toordinal()`.

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
