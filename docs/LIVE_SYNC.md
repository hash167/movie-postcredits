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
(directory mounts; image underlay not captured). `reddit_scraper.py` was
not in the capture and is not imported.

Catalog JSON, env values, Kubernetes Secrets, and the redacted workload
inventory are not in this commit. `/otel` was mounted and not inspected.
OpenTelemetry packages pinned in `requirements.txt` are the versions the
image had installed, so a rebuild can import them without that mount.
Confirm the import in the built image before removing the mount.

Startup `DatabaseManager.ensure_schema` already recreates the
`movies_complete` view and widens `easter_eggs.significance`. This commit
does not add a migration and does not run one.
