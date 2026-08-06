import tempfile
import unittest
from pathlib import Path

from publish_pages_branch import clear_worktree, copy_site


class PublishPagesBranchTests(unittest.TestCase):
    def test_copy_site_replaces_old_files_and_adds_nojekyll(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            site = root / "site"
            worktree = root / "worktree"
            site.mkdir()
            worktree.mkdir()
            (site / "index.html").write_text("new", encoding="utf-8")
            (worktree / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
            (worktree / "old.html").write_text("old", encoding="utf-8")

            copy_site(site, worktree)

            self.assertEqual((worktree / "index.html").read_text(encoding="utf-8"), "new")
            self.assertFalse((worktree / "old.html").exists())
            self.assertTrue((worktree / ".git").exists())
            self.assertTrue((worktree / ".nojekyll").exists())

    def test_clear_worktree_preserves_git_pointer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            worktree = Path(temp_dir)
            (worktree / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
            (worktree / "nested").mkdir()
            (worktree / "nested" / "file.txt").write_text("x", encoding="utf-8")

            clear_worktree(worktree)

            self.assertTrue((worktree / ".git").exists())
            self.assertFalse((worktree / "nested").exists())


if __name__ == "__main__":
    unittest.main()
