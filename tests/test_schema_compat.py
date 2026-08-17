import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("TMDB_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db")

from src.schema_compat import (
    MOVIES_COMPLETE_VIEW_SQL,
    egg_to_live_columns,
    normalize_easter_egg,
    worth_staying_to_bool,
    worth_staying_to_db,
)


class SchemaCompatTests(unittest.TestCase):
    def test_egg_detail_maps_to_title_and_description(self):
        mapped = egg_to_live_columns(
            "A mid-credits cameo teases the sequel.",
            "Sets up the next film",
        )
        self.assertEqual(
            mapped["title"], "A mid-credits cameo teases the sequel."
        )
        self.assertEqual(
            mapped["description"], "A mid-credits cameo teases the sequel."
        )
        self.assertIsNone(mapped["timestamp_minutes"])
        self.assertEqual(mapped["significance"], "Sets up the next film")

    def test_egg_title_truncated_to_500(self):
        long_detail = "x" * 600
        mapped = egg_to_live_columns(long_detail, "y" * 80)
        self.assertEqual(len(mapped["title"]), 500)
        self.assertEqual(mapped["description"], long_detail)
        self.assertEqual(len(mapped["significance"]), 50)

    def test_significance_truncated_to_50_before_insert(self):
        """Live easter_eggs.significance is VARCHAR(50)."""
        mapped = egg_to_live_columns(
            "A mid-credits cameo.",
            "This significance string is far longer than fifty characters and would fail INSERT",
        )
        self.assertEqual(len(mapped["significance"]), 50)
        self.assertTrue(
            mapped["significance"].startswith("This significance string")
        )

    def test_worth_staying_db_values(self):
        self.assertEqual(worth_staying_to_db(True), "yes")
        self.assertEqual(worth_staying_to_db(False), "no")
        self.assertIsNone(worth_staying_to_db(None))
        self.assertEqual(worth_staying_to_db("yes"), "yes")

    def test_worth_staying_bool_values(self):
        self.assertTrue(worth_staying_to_bool("yes"))
        self.assertFalse(worth_staying_to_bool("no"))
        self.assertTrue(worth_staying_to_bool(True))
        self.assertIsNone(worth_staying_to_bool(None))

    def test_normalize_egg_exposes_detail_alias(self):
        egg = normalize_easter_egg(
            {"title": "Cameo", "description": "Stan Lee appears"}
        )
        self.assertEqual(egg["detail"], "Stan Lee appears")
        self.assertEqual(egg["title"], "Cameo")

    def test_view_sql_uses_live_columns_only(self):
        sql = MOVIES_COMPLETE_VIEW_SQL
        self.assertIn("ri.reddit_discussion_count", sql)
        self.assertIn("ee.title", sql)
        self.assertIn("ee.description", sql)
        self.assertNotIn("ri.discussion_count", sql)
        self.assertNotIn("ee.detail", sql)
        self.assertNotIn("source_urls", sql)
        self.assertNotIn("ee.confidence", sql)
        self.assertNotIn("ee.source_url", sql)


class SetupSqlTests(unittest.TestCase):
    def test_setup_db_sql_matches_live_schema(self):
        with open("scripts/setup_db.sql", encoding="utf-8") as fh:
            sql = fh.read()
        self.assertIn("reddit_discussion_count", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS batch_logs", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS extract_jobs", sql)
        self.assertIn("CREATE OR REPLACE VIEW movies_complete", sql)
        self.assertIn("worth_staying VARCHAR", sql)
        self.assertNotIn("ee.detail", sql)
        self.assertNotIn("ri.discussion_count", sql)
        self.assertNotIn("ri.source_urls", sql)
        self.assertNotIn("source_urls TEXT", sql)
        # Table definitions must use live easter_egg columns
        self.assertIn("title VARCHAR(500)", sql)
        self.assertIn("description TEXT", sql)
        self.assertNotIn("detail TEXT NOT NULL", sql)
        self.assertNotIn("    discussion_count INTEGER", sql)


if __name__ == "__main__":
    unittest.main()
