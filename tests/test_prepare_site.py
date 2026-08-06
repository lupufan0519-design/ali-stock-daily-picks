import json
import tempfile
import unittest
from pathlib import Path

from prepare_site import build_site


class PrepareSiteTests(unittest.TestCase):
    def test_build_site_copies_the_simple_page_and_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            (results / "latest.html").write_text("<h1>今日选股</h1>", encoding="utf-8")
            (results / "live.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
            (results / "history.json").write_text(json.dumps({"dates": []}), encoding="utf-8")

            target = build_site(root, root / "public")

            self.assertEqual((root / "index.html").read_text(encoding="utf-8"), "<h1>今日选股</h1>")
            self.assertEqual((target / "index.html").read_text(encoding="utf-8"), "<h1>今日选股</h1>")
            self.assertTrue((target / "live.json").exists())
            self.assertTrue((target / "history.json").exists())
            self.assertTrue((target / ".nojekyll").exists())

    def test_missing_history_blocks_site_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            (results / "latest.html").write_text("<h1>今日选股</h1>", encoding="utf-8")
            (results / "live.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(FileNotFoundError, "history.json"):
                build_site(root, root / "public")


if __name__ == "__main__":
    unittest.main()
