from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def build_site(root: Path = ROOT, site: Path | None = None) -> Path:
    target = site or root / "_site"
    target.mkdir(parents=True, exist_ok=True)
    latest_html = root / "results" / "latest.html"
    live_json = root / "results" / "live.json"
    history_json = root / "results" / "history.json"
    required = (latest_html, live_json, history_json)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("站点文件缺失：" + "、".join(missing))

    shutil.copy2(latest_html, root / "index.html")
    shutil.copy2(latest_html, target / "index.html")
    shutil.copy2(live_json, target / "live.json")
    shutil.copy2(history_json, target / "history.json")
    (target / ".nojekyll").write_text("", encoding="utf-8")
    print(f"站点已准备：{target}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="准备极简 GitHub Pages 站点")
    parser.add_argument("--site", type=Path, default=ROOT / "_site")
    args = parser.parse_args()
    build_site(ROOT, args.site)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
