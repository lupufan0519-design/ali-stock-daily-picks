from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run_git(*args: str, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
    )


def remote_branch_exists(branch: str) -> bool:
    result = run_git("ls-remote", "--exit-code", "--heads", "origin", branch, check=False)
    return result.returncode == 0


def clear_worktree(path: Path) -> None:
    for child in path.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def copy_site(site_dir: Path, worktree: Path) -> None:
    clear_worktree(worktree)
    for source in site_dir.iterdir():
        target = worktree / source.name
        if source.is_dir() and not source.is_symlink():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    (worktree / ".nojekyll").touch()


def publish(site_dir: Path, branch: str = "gh-pages") -> bool:
    site_dir = site_dir.resolve()
    if not site_dir.is_dir():
        raise FileNotFoundError(f"Site directory does not exist: {site_dir}")

    exists = remote_branch_exists(branch)
    if exists:
        run_git("fetch", "origin", f"{branch}:refs/remotes/origin/{branch}")

    with tempfile.TemporaryDirectory(prefix="stock-pages-") as temp_dir:
        worktree = Path(temp_dir) / "worktree"
        start_ref = f"refs/remotes/origin/{branch}" if exists else "HEAD"
        run_git("worktree", "add", "--detach", str(worktree), start_ref)
        try:
            if not exists:
                run_git("switch", "--orphan", branch, cwd=worktree)
            copy_site(site_dir, worktree)
            run_git("config", "user.name", "github-actions[bot]", cwd=worktree)
            run_git(
                "config",
                "user.email",
                "41898282+github-actions[bot]@users.noreply.github.com",
                cwd=worktree,
            )
            run_git("add", "-A", cwd=worktree)
            if run_git("diff", "--cached", "--quiet", cwd=worktree, check=False).returncode == 0:
                print("Published site is unchanged; gh-pages already matches.")
                return False
            run_git("commit", "-m", "Publish stock dashboard", cwd=worktree)
            run_git("push", "origin", f"HEAD:refs/heads/{branch}", cwd=worktree)
            print(f"Published {site_dir} to {branch}.")
            return True
        finally:
            run_git("worktree", "remove", "--force", str(worktree), check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish the built site to a dedicated Pages branch")
    parser.add_argument("--site", type=Path, default=ROOT / "_site")
    parser.add_argument("--branch", default="gh-pages")
    args = parser.parse_args()
    publish(args.site, args.branch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
