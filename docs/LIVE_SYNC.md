# Live sync source map

Archive `movies-live-sync-sanitized-20261107.tar.gz`
SHA-256 `2304fd0830551b4112453adba940a53d897bc57001579beb4e79ee9fe11bf779`.
Image `randomnumber20/movie-api:20260929-eggval`
digest `sha256:34fe7abe11e78666ab27d5bbddb619c8dffc27a230decb27fac0a54232e68541`.

Every Python name was byte-identical across the four API/worker pods.
ConfigMap `movie-api-patches` matched those pods for every key it contained.
`run_batch.py`, `storage_uploader.py`, and `sync_job.py` are image files
(not ConfigMap keys) and were identical on all four pods. Frontend HTML/JS
matched ConfigMap `movie-frontend-html`. nginx `default.conf` matched
ConfigMap `movie-frontend` after sanitization.

Not imported by the captured tree, and not reconstructed:
`web_search.py`, `extract_queue.py`, `schema_compat.py`, `get_search.py`
(directory mounts; image underlay not captured). `reddit_scraper.py` is
absent because the live `api.py` and `batch_processor.py` contain no
import, string, or importlib reference to it. The previous `main` API did
import it; that call path is not in the running source. `scrape_movie_insights`
on the live tree is `MovieInsights`, not Reddit.

Verified live proxy targets, not guesses: API
`movie-api.movie-api.svc.cluster.local:8000` (Service port 8000, 2 ready
endpoints) and MinIO `minio.movie-api.svc.cluster.local:9000` (1 ready
endpoint). Catalog objects are `theaters-movies.json`, `popular-movies.json`,
`recent-movies.json`, and `on-demand-movies.json` in bucket `movies`.
`/movies/` proxies that bucket. The four catalog keys stay in
`movie-frontend-html`; the saved rollback copy omits them, so a frontend
ConfigMap replace must keep those keys until a complete rollback exists.
This repo does not publish the runtime JSON.

`CORS_ORIGINS`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, and
`OLLAMA_HOST` are nonempty at runtime via `movie-api-config` and
`movie-api-secrets`. Source defaults are empty so those literals are not
credentials. `S3_*` key presence inside the Secret was not inspected.
`/otel` is an emptyDir filled by an init pip install (API/worker
1.27.0 and instrumentation 0.48b0; batch installs a smaller set), not a
source patch. 1207 installed-file hashes matched; no sitecustomize.

Catalog JSON, env values, Kubernetes Secrets, and the redacted workload
inventory are not in this commit. `/otel` was mounted and not inspected.
OpenTelemetry packages pinned in `requirements.txt` are the versions the
image had installed, so a rebuild can import them without that mount.
Confirm the import in the built image before removing the mount.

Startup `DatabaseManager.ensure_schema` already recreates the
`movies_complete` view and widens `easter_eggs.significance`. This commit
does not add a migration and does not run one.
