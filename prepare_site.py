from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from validate_strategy_artifacts import validate_artifacts


ROOT = Path(__file__).resolve().parent


def validate_strategy_artifacts(root: Path = ROOT) -> dict:
    results = root / "results"
    return validate_artifacts(
        results / "strategy_grid_optimization.json",
        results / "trend_case.json",
        results / "strategy_portfolio_validation.json",
        require_portfolio=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="准备 GitHub Pages 静态站点")
    parser.add_argument("--site", type=Path, default=ROOT / "_site")
    args = parser.parse_args()
    validate_strategy_artifacts(ROOT)
    args.site.mkdir(parents=True, exist_ok=True)
    latest_html = ROOT / "results" / "latest.html"
    shutil.copy2(latest_html, ROOT / "index.html")
    shutil.copy2(latest_html, args.site / "index.html")
    shutil.copy2(ROOT / "results" / "live.json", args.site / "live.json")
    for filename in (
        "strategy_grid_optimization.json",
        "strategy_portfolio_validation.json",
        "trend_case.json",
    ):
        result = ROOT / "results" / filename
        if result.exists():
            shutil.copy2(result, args.site / filename)
    assets = ROOT / "assets"
    if assets.exists():
        shutil.copytree(assets, args.site / "assets", dirs_exist_ok=True)
    required_assets = (
        "hero-aigc-v2-poster.webp",
        "hero-aigc-v2-poster-mobile.webp",
        "hero-cloudbreak-aigc-v2.webm",
    )
    missing_assets = [name for name in required_assets if not (args.site / "assets" / name).exists()]
    if missing_assets:
        raise FileNotFoundError(f"站点封面资源缺失：{', '.join(missing_assets)}")
    (args.site / ".nojekyll").write_text("", encoding="utf-8")
    print(f"站点已准备：{args.site}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
