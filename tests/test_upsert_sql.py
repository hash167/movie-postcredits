import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("TMDB_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db")


class UpsertSqlTests(unittest.TestCase):
    def test_upsert_writes_live_columns_only(self):
        with open("src/database.py", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("INSERT INTO easter_eggs", src)
        self.assertIn("title, description", src)
        self.assertIn("reddit_discussion_count", src)
        self.assertIn("worth_staying_to_db", src)
        self.assertIn("async def ensure_schema", src)
        self.assertIn("BATCH_LOGS_TABLE_SQL", src)
        self.assertIn("ensure_schema", src)
        # Must not write columns that do not exist on the live cluster
        self.assertNotIn("movie_id, detail", src)
        self.assertNotIn("confidence, source_url", src)
        self.assertNotIn("discussion_count, source_urls", src)
        self.assertNotIn(
            "movie_id, discussion_count, source_urls", src
        )
        self.assertIn("Do not wipe existing eggs", src)
        self.assertIn("if new_eggs:", src)
        self.assertIn("significance[:50]", src)

    def test_batch_logs_sql_constant(self):
        from src.schema_compat import BATCH_LOGS_TABLE_SQL
        self.assertIn("CREATE TABLE IF NOT EXISTS batch_logs", BATCH_LOGS_TABLE_SQL)


if __name__ == "__main__":
    unittest.main()
