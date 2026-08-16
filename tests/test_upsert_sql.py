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
        self.assertIn("CREATE TABLE IF NOT EXISTS batch_logs", src)
        # Must not write columns that do not exist on the live cluster
        self.assertNotIn("egg.detail,", src)
        self.assertNotIn("discussion_count, source_urls", src)
        self.assertNotIn("INSERT INTO reddit_insights (\n"
                         "                            movie_id, discussion_count", src)


if __name__ == "__main__":
    unittest.main()
