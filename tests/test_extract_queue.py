import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("TMDB_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db")

from src.extract_queue import (
    STALE_AFTER,
    enqueue_decision,
    movie_has_eggs_or_credits,
    stale_running_action,
    status_after_error,
)
from src.schema_compat import (
    CLAIM_EXTRACT_JOB_SQL,
    EXTRACT_JOBS_TABLE_SQL,
    FAIL_STALE_RUNNING_SQL,
    MARK_EXTRACT_RUNNING_SQL,
    REQUEUE_STALE_RUNNING_SQL,
)


class EnqueueIdempotencyTests(unittest.TestCase):
    def test_insert_when_missing(self):
        self.assertEqual(enqueue_decision(None, False), "insert")

    def test_noop_when_queued_or_running(self):
        self.assertEqual(
            enqueue_decision({"status": "queued"}, False), "noop"
        )
        self.assertEqual(
            enqueue_decision({"status": "running"}, False), "noop"
        )
        self.assertEqual(
            enqueue_decision({"status": "queued"}, True), "noop"
        )

    def test_refresh_false_leaves_done_alone(self):
        self.assertEqual(
            enqueue_decision({"status": "done"}, False), "noop"
        )
        self.assertEqual(
            enqueue_decision({"status": "done"}, True), "noop"
        )
        self.assertEqual(
            enqueue_decision({"status": "done"}, True, refresh=False), "noop"
        )

    def test_refresh_true_requeues_done_and_failed(self):
        self.assertEqual(
            enqueue_decision({"status": "done"}, True, refresh=True),
            "requeue",
        )
        self.assertEqual(
            enqueue_decision({"status": "done"}, False, refresh=True),
            "requeue",
        )
        self.assertEqual(
            enqueue_decision({"status": "failed"}, False, refresh=True),
            "requeue",
        )

    def test_requeue_failed(self):
        self.assertEqual(
            enqueue_decision({"status": "failed"}, False), "requeue"
        )


class ContentCheckTests(unittest.TestCase):
    def test_empty_movie_has_no_content(self):
        self.assertFalse(movie_has_eggs_or_credits(None))
        self.assertFalse(movie_has_eggs_or_credits({"has_scene": False}))
        self.assertFalse(
            movie_has_eggs_or_credits({"has_scene": False, "easter_eggs": []})
        )

    def test_eggs_or_credits_count(self):
        self.assertTrue(movie_has_eggs_or_credits({"has_scene": True}))
        self.assertTrue(
            movie_has_eggs_or_credits(
                {"has_scene": False, "easter_eggs": [{"detail": "x"}]}
            )
        )


class StaleRequeueTests(unittest.TestCase):
    def test_fresh_running_not_stolen(self):
        now = datetime(2026, 8, 17, 5, 0, 0)
        started = now - timedelta(minutes=9)
        self.assertIsNone(stale_running_action(started, 1, now))

    def test_stale_under_max_attempts_requeues(self):
        now = datetime(2026, 8, 17, 5, 0, 0)
        started = now - timedelta(minutes=11)
        self.assertEqual(stale_running_action(started, 2, now), "queued")

    def test_stale_at_max_attempts_fails(self):
        now = datetime(2026, 8, 17, 5, 0, 0)
        started = now - timedelta(minutes=11)
        self.assertEqual(stale_running_action(started, 3, now), "failed")

    def test_stale_window_longer_than_ollama_420s(self):
        self.assertGreater(STALE_AFTER.total_seconds(), 420)

    def test_error_retries_then_fails(self):
        self.assertEqual(status_after_error(1), "queued")
        self.assertEqual(status_after_error(2), "queued")
        self.assertEqual(status_after_error(3), "failed")


class ClaimSqlTests(unittest.TestCase):
    def test_schema_and_claim_use_skip_locked(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS extract_jobs", EXTRACT_JOBS_TABLE_SQL)
        self.assertIn("movie_id INT UNIQUE NOT NULL", EXTRACT_JOBS_TABLE_SQL)
        self.assertIn("FOR UPDATE SKIP LOCKED", CLAIM_EXTRACT_JOB_SQL)
        self.assertIn("LIMIT 1", CLAIM_EXTRACT_JOB_SQL)
        self.assertIn("status = 'queued'", CLAIM_EXTRACT_JOB_SQL)
        self.assertIn("attempts = attempts + 1", MARK_EXTRACT_RUNNING_SQL)
        self.assertIn("attempts < 3", REQUEUE_STALE_RUNNING_SQL)
        self.assertIn("attempts >= 3", FAIL_STALE_RUNNING_SQL)

    def test_worker_deployment_is_two_replicas(self):
        with open("kubernetes/extract-worker.example.yaml", encoding="utf-8") as fh:
            manifest = fh.read()
        self.assertIn("replicas: 2", manifest)
        self.assertIn("FOR UPDATE SKIP LOCKED", manifest)
        self.assertIn("one Ollama host so CPU will contend", manifest)
        with open("kubernetes/all-in-one.example.yaml", encoding="utf-8") as fh:
            all_in_one = fh.read()
        self.assertIn("name: movie-extract-worker", all_in_one)
        worker = all_in_one.split("name: movie-extract-worker", 1)[1]
        self.assertIn("replicas: 2", worker)

    def test_api_does_not_create_task_extract(self):
        with open("src/api.py", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("enqueue_extract_job", src)
        self.assertNotIn("create_task(process_movie", src)
        self.assertNotIn("create_task(reanalyze", src)
        self.assertNotIn("asyncio.create_task(process_movie_background())", src)


class FakeSkipLockedStore:
    """In-memory stand-in for two connections + FOR UPDATE SKIP LOCKED."""

    def __init__(self, jobs):
        self.jobs = {job["id"]: dict(job) for job in jobs}
        self.locked = set()

    def claim(self, conn_id):
        for job in sorted(self.jobs.values(), key=lambda j: j["created_at"]):
            if job["status"] != "queued":
                continue
            if job["id"] in self.locked:
                continue
            self.locked.add(job["id"])
            job["status"] = "running"
            job["attempts"] += 1
            job["holder"] = conn_id
            return dict(job)
        return None

    def commit(self, job_id):
        self.locked.discard(job_id)


class SkipLockedClaimTests(unittest.TestCase):
    def test_second_connection_skips_locked_row(self):
        now = datetime(2026, 8, 17, 4, 0, 0)
        store = FakeSkipLockedStore(
            [
                {
                    "id": 1,
                    "movie_id": 1212763,
                    "status": "queued",
                    "attempts": 0,
                    "created_at": now,
                }
            ]
        )
        first = store.claim("conn-a")
        second = store.claim("conn-b")
        self.assertIsNotNone(first)
        self.assertEqual(first["movie_id"], 1212763)
        self.assertEqual(first["attempts"], 1)
        self.assertIsNone(second)
        store.commit(first["id"])
        # After commit the row is running, not queued, so still not claimed.
        self.assertIsNone(store.claim("conn-b"))

    def test_two_queued_jobs_go_to_two_connections(self):
        now = datetime(2026, 8, 17, 4, 0, 0)
        store = FakeSkipLockedStore(
            [
                {
                    "id": 1,
                    "movie_id": 1,
                    "status": "queued",
                    "attempts": 0,
                    "created_at": now,
                },
                {
                    "id": 2,
                    "movie_id": 2,
                    "status": "queued",
                    "attempts": 0,
                    "created_at": now + timedelta(seconds=1),
                },
            ]
        )
        a = store.claim("conn-a")
        b = store.claim("conn-b")
        self.assertEqual({a["id"], b["id"]}, {1, 2})
        self.assertNotEqual(a["holder"], b["holder"])


class WorkerClaimUsesSqlTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_one_issues_skip_locked_then_commit(self):
        from src.extract_worker import ExtractWorker

        claimed_row = {
            "id": 9,
            "movie_id": 1212763,
            "title": "Evil Dead Burn",
            "year": 2026,
            "attempts": 1,
        }

        class FakeTxn:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeConn:
            def __init__(self):
                self.sql = []

            def transaction(self):
                return FakeTxn()

            async def fetchrow(self, sql, *args):
                self.sql.append(sql)
                if "FOR UPDATE SKIP LOCKED" in sql:
                    return {
                        "id": 9,
                        "movie_id": 1212763,
                        "title": "Evil Dead Burn",
                        "year": 2026,
                        "attempts": 0,
                    }
                return claimed_row

        class FakeAcquire:
            def __init__(self, conn):
                self.conn = conn

            async def __aenter__(self):
                return self.conn

            async def __aexit__(self, exc_type, exc, tb):
                return False

        conn = FakeConn()
        worker = ExtractWorker()
        worker.db.pool = MagicMock()
        worker.db.pool.acquire.return_value = FakeAcquire(conn)
        job = await worker.claim_one()
        self.assertEqual(job["movie_id"], 1212763)
        self.assertTrue(any("FOR UPDATE SKIP LOCKED" in s for s in conn.sql))
        self.assertTrue(any("attempts = attempts + 1" in s for s in conn.sql))


class WorkerOllamaErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_ollama_extract_error_never_marks_done(self):
        from src.extract_worker import ExtractWorker
        from src.insights import OllamaExtractError

        worker = ExtractWorker()
        worker.requeue_stale = AsyncMock()
        worker.claim_one = AsyncMock(
            return_value={
                "id": 7,
                "movie_id": 505642,
                "title": "Wakanda Forever",
                "attempts": 1,
            }
        )
        worker.run_job = AsyncMock(
            side_effect=OllamaExtractError("timed out")
        )
        worker.mark_done = AsyncMock()
        worker.mark_error = AsyncMock()
        worked = await worker.loop_once()
        self.assertTrue(worked)
        worker.mark_done.assert_not_called()
        worker.mark_error.assert_awaited_once()
        args = worker.mark_error.await_args.args
        self.assertEqual(args[0], 7)
        self.assertEqual(args[1], 1)
        self.assertEqual(status_after_error(1), "queued")
        self.assertEqual(status_after_error(3), "failed")

    async def test_fill_insights_error_does_not_upsert_or_done(self):
        from src.extract_worker import ExtractWorker
        from src.insights import OllamaExtractError

        worker = ExtractWorker()
        worker.tmdb.get_movie_details = AsyncMock(
            return_value={"id": 505642, "title": "Wakanda Forever"}
        )
        worker.tmdb.format_movie = MagicMock(
            return_value={
                "id": 505642,
                "title": "Wakanda Forever",
                "year": 2022,
                "release_date": "2022-11-11",
                "runtime_minutes": 161,
                "poster_path": None,
                "overview": "",
                "vote_average": 0.0,
                "popularity": 0.0,
                "tier": "on-demand",
                "imdb_id": None,
            }
        )
        worker.insights.fill_insights = AsyncMock(
            side_effect=OllamaExtractError("HTTP 500")
        )
        worker.db.upsert_movie = AsyncMock()
        with self.assertRaises(OllamaExtractError):
            await worker.run_job(
                {
                    "id": 7,
                    "movie_id": 505642,
                    "title": "Wakanda Forever",
                    "attempts": 1,
                }
            )
        worker.db.upsert_movie.assert_not_called()


class EnqueueExtractRefreshTests(unittest.IsolatedAsyncioTestCase):
    def _db_with_existing(self, existing, executed):
        from src.database import DatabaseManager

        class Conn:
            async def fetchrow(self, sql, *args):
                return existing

            async def execute(self, sql, *args):
                executed.append(sql)
                return "UPDATE 1"

        class Acquire:
            async def __aenter__(self):
                return Conn()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        db = DatabaseManager()
        db.pool = MagicMock()
        db.pool.acquire.return_value = Acquire()
        return db

    async def test_refresh_true_requeues_done_row(self):
        executed = []
        db = self._db_with_existing(
            {"id": 1, "status": "done"}, executed
        )
        result = await db.enqueue_extract(
            505642, "Wakanda Forever", 2022, refresh=True
        )
        self.assertEqual(result, "requeue")
        self.assertTrue(any("status = 'queued'" in sql for sql in executed))

    async def test_refresh_false_leaves_done_alone(self):
        executed = []
        db = self._db_with_existing(
            {"id": 1, "status": "done"}, executed
        )
        result = await db.enqueue_extract(
            505642, "Wakanda Forever", 2022, refresh=False
        )
        self.assertEqual(result, "noop")
        self.assertEqual(executed, [])

    def test_refresh_endpoint_passes_refresh_true(self):
        with open("src/api.py", encoding="utf-8") as fh:
            src = fh.read()
        block = src.split("async def refresh_movie_analysis", 1)[1]
        block = block.split("async def trigger_sync", 1)[0]
        self.assertIn("refresh=True", block)
        self.assertIn("enqueue_extract", block)
