import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("TMDB_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db")

from src.schema_compat import normalize_easter_egg, normalize_easter_eggs


class JsonExporterSqlTests(unittest.TestCase):
    def test_exporter_sql_never_selects_missing_egg_columns(self):
        with open("src/json_exporter.py", encoding="utf-8") as fh:
            src = fh.read()
        # Live easter_eggs has title/description, not these columns
        self.assertNotIn("SELECT detail, significance, confidence", src)
        self.assertNotIn("source_url FROM easter_eggs", src)
        self.assertNotIn("confidence, source_url", src)
        self.assertIn("SELECT title, description, significance", src)
        self.assertIn('egg["description"]', src)
        self.assertIn('"detail":', src)

    def test_description_maps_to_detail_for_frontend(self):
        eggs = normalize_easter_eggs(
            [
                {
                    "title": "Mid-credits cameo",
                    "description": "A hero appears after the logo.",
                    "significance": "Sequel tease",
                }
            ]
        )
        self.assertEqual(eggs[0]["detail"], "A hero appears after the logo.")
        self.assertEqual(eggs[0]["significance"], "Sequel tease")

    def test_normalize_prefers_description_over_title(self):
        egg = normalize_easter_egg(
            {"title": "Short", "description": "Full published fact"}
        )
        self.assertEqual(egg["detail"], "Full published fact")
        self.assertIn("significance", egg)
