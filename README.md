# Movie Post-Credits & Easter Eggs

**Live app:** [https://movies.thewalawalas.com](https://movies.thewalawalas.com)

Search a movie, see whether it has a mid- or post-credits scene, and read easter eggs grounded in source articles. The site is a small same-origin frontend. The API, extract worker, and theater batch job live in this repo.

What is deployed can lag this branch. A production parity check is still in progress and is not a claim that the public site is running this commit.

## What it does

- Search with `GET /search?q=` or `GET /search?query=`, and open `GET /movie/{id}`.
- Mark post-credits and mid-credits from TMDB keywords.
- Fetch public articles, extract eggs with Ollama, then drop eggs that fail cast, source, or overview checks.
- Queue extracts in Postgres (`FOR UPDATE SKIP LOCKED`) and poll `GET /movie/{id}` until the job finishes.
- Export theater, popular, recent, and on-demand lists for the frontend. `POST /movie/{id}/refresh` re-runs one title.

Reddit scraping and OpenAI are not on this path. `openai` remains a dependency, but extraction uses `OLLAMA_HOST` and `OLLAMA_MODEL`.

## Stack

- API: FastAPI, served by uvicorn (`src.api:app`, port 8000).
- Worker: `python -m src.extract_worker`.
- Batch: `python -m src.run_batch --mode theaters --export --upload`.
- Data: Postgres (`asyncpg`). Object storage: S3-compatible (MinIO or S3) via boto3.
- Frontend: static HTML and JavaScript. `frontend/config.js` uses the page origin. `frontend/nginx.conf` proxies API and object-storage paths.
- Telemetry: OpenTelemetry to Honeycomb when `HONEYCOMB_API_KEY` is set. Traces and logs mask credential-shaped values before they leave the process.

## Configure

Copy `.env.example` to `.env` and set values there or in the process environment. Do not commit `.env`.

Required for the API process:

- `TMDB_API_KEY` (or `TMDB_READ_ACCESS_TOKEN` for TMDB v4 reads)
- `DATABASE_URL`

Required for extract and batch, when you run those:

- `OLLAMA_HOST` and `OLLAMA_MODEL` (default model in source is `llama3.1:8b`)
- `S3_ENDPOINT`, `S3_BUCKET` (default `movies`), `S3_ACCESS_KEY`, `S3_SECRET_KEY`

Optional:

- `CORS_ORIGINS` for browsers that are not same-origin
- `HONEYCOMB_API_KEY`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`
- `EXPORT_DIR` (default `./exports`)

Empty defaults do not point at a private host. If `OLLAMA_HOST` or `S3_ENDPOINT` is missing, extract and upload fail instead of using a built-in address.

## Run

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn src.api:app --host 0.0.0.0 --port 8000
```

Health check: `GET /health`.

In other terminals, with the same environment:

```bash
python -m src.extract_worker
python -m src.run_batch --mode theaters --export --upload
```

Tests use a local Postgres only when `TEST_DATABASE_URL` points at `127.0.0.1` or `localhost`. They do not call TMDB, Ollama, or a real object store.

```bash
pip install pytest
python3 -m pytest tests -q
```

## Container images

[`.github/workflows/image.yml`](.github/workflows/image.yml) publishes this image on every push to `main` and on `workflow_dispatch`:

`ghcr.io/hash167/movie-postcredits-api:<git sha>`

The tag is the full commit SHA. The build context is the repository root, the platform is `linux/amd64`, and the `GIT_SHA` build-arg is that same SHA. The root `Dockerfile` stores it as `org.opencontainers.image.revision`. The API process, the extract worker (`python -m src.extract_worker`), and the `theaters-daily` CronJob (`python -m src.run_batch --mode theaters --export --upload`) all run this image. Pull requests run the same build with `push: false`.

The live frontend is the static app in `frontend/`, served by nginx. `frontend/nginx.conf` and the HTML are mounted from the `movie-frontend` and `movie-frontend-html` ConfigMaps. This repository has no Dockerfile for that nginx image, so the workflow publishes the API image only.

GitHub creates the package as private. To let the cluster pull it with no registry credential, open the package settings and set the visibility to public. To keep it private, create an image pull secret in the cluster from a token with `read:packages`, and name that secret on the pod. Keep the token out of this repository.

Pointing the k3s Deployment and CronJob at `ghcr.io/hash167/movie-postcredits-api:<sha>` is a separate step. This workflow does not deploy and does not contact the cluster.

## Images

The screenshots in `images/` are from an earlier UI. The current page is the static app under `frontend/`.
