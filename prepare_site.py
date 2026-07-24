from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="准备 GitHub Pages 静态站点")
    parser.add_argument("--site", type=Path, default=ROOT / "_site")
    args = parser.parse_args()
    args.site.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "results" / "latest.html", args.site / "index.html")
    shutil.copy2(ROOT / "results" / "live.json", args.site / "live.json")
    assets = ROOT / "assets"
    if assets.exists():
        shutil.copytree(assets, args.site / "assets", dirs_exist_ok=True)
    (args.site / ".nojekyll").write_text("", encoding="utf-8")
    print(f"站点已准备：{args.site}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
