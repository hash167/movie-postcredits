# Easter egg validation strategy

Ollama extracts eggs from fetched articles. Before upsert/serve, each egg runs
through the checks below (**first failure drops the egg**).

## Check order

1. **Non-empty detail** — blank eggs are dropped.
2. **Overview / foreign-franchise filter** (`insight_filters.egg_fits_overview`) —
   drops off-title franchise markers (Superman, MCU, etc.) that contradict the
   TMDB overview/title. Unchanged from prior behavior; still required.
3. **Cast grounding** (`egg_validation.check_cast_grounding`) — when an egg
   asserts `Actor's character, Name` / `Actor as Name`, the pairing must match
   TMDB `/movie/{id}/credits`. Actor↔character swaps (The Wrecking Crew) are
   **dropped**, never rewritten (role bios in the same sentence are often swapped too).
4. **Source grounding** (`egg_validation.check_source_grounding`) — distinctive
   tokens in the detail must appear in fetched article text. Unsupported
   franchise fluff in `significance` (Aquaman / Guardians-style nods) is stripped;
   invented details absent from articles are dropped. Best-matching article URL
   is attached as `source_url`.
5. **Prefer real eggs** (`looks_like_plot_bio`) — bare character/plot bios without
   egg markers (cameo, hidden, mid-credits, reference, …) are dropped.

## Fail behavior

- Drop + log reason (`drop egg [reason]: …`).
- Surviving eggs keep cleaned `significance` and `source_url`.
- Movie-level `source_urls` (article list) are persisted on `movie_insights`.

## Where it runs

`MovieInsights.scrape_movie_insights` → after Ollama + overview filter →
`validate_eggs(...)` → `DatabaseManager.upsert_movie`.

Used by `jobs.fill_insights`, `extract_worker`, `run_one_movie`, and the API
enqueue path.

## Re-analyze a movie after deploy

```bash
# In the API / extract-worker environment (PYTHONPATH=/app):
python -m src.run_one_movie <TMDB_ID> on-demand
```

For The Wrecking Crew: `python -m src.run_one_movie 1168190 on-demand`

Or enqueue via the existing extract job queue and wait for `extract_worker`.

## Tests

```bash
PYTHONPATH=. python tests/test_egg_validation.py
PYTHONPATH=. python tests/test_insight_filters.py
```
