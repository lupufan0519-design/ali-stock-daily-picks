from __future__ import annotations

import re
from pathlib import Path

from report_ui import (
    LIVE_SCRIPT,
    STYLES,
    _read_result_json,
    _validation_cohorts,
    _validation_section,
)


ROOT = Path(__file__).resolve().parent
LATEST_HTML = ROOT / "results" / "latest.html"
START = "<!-- validation-section:start -->"
END = "<!-- validation-section:end -->"


def _section_bounds(source: str, section_id: str) -> tuple[int, int]:
    opening = re.search(
        rf"<section\b[^>]*\bid=[\"']{re.escape(section_id)}[\"'][^>]*>",
        source,
        flags=re.IGNORECASE,
    )
    if not opening:
        raise RuntimeError(f"页面中找不到 {section_id} 区")
    token_pattern = re.compile(r"</?section\b[^>]*>", flags=re.IGNORECASE)
    depth = 0
    for token in token_pattern.finditer(source, opening.start()):
        if token.group(0).startswith("</"):
            depth -= 1
            if depth == 0:
                return opening.start(), token.end()
        else:
            depth += 1
    raise RuntimeError(f"页面中的 {section_id} 区没有闭合")


def refresh(path: Path = LATEST_HTML) -> None:
    if not _validation_cohorts(_read_result_json("strategy_grid_optimization.json")):
        raise RuntimeError(
            "联合滚动验证结果缺少 schema_version=3、批次元数据或主选/次选/合计 cohorts"
        )
    source = path.read_text(encoding="utf-8")
    updated, style_count = re.subn(
        r"<style>.*?</style>",
        lambda _match: f"<style>{STYLES}</style>",
        source,
        count=1,
        flags=re.DOTALL,
    )
    if style_count != 1:
        raise RuntimeError("页面中没有唯一的主样式区")

    validation = _validation_section().lstrip()
    if not validation:
        raise RuntimeError("联合滚动验证结果不存在或无法读取")
    block = f"{START}\n    {validation}\n    {END}"
    if START in updated and END in updated:
        start = updated.index(START)
        end = updated.index(END, start) + len(END)
        updated = updated[:start] + block + updated[end:]
    else:
        start, end = _section_bounds(updated, "validation")
        updated = updated[:start] + block + updated[end:]

    updated, script_count = re.subn(
        r"<script>\s*\(\(\) => \{.*?</script>\s*</body>",
        lambda _match: f"<script>{LIVE_SCRIPT}</script>\n</body>",
        updated,
        count=1,
        flags=re.DOTALL,
    )
    if script_count != 1:
        raise RuntimeError("页面中没有唯一的主交互脚本")

    updated = "\n".join(line.rstrip() for line in updated.splitlines())
    path.write_text(updated, encoding="utf-8")
    print(f"完整历史验证区已刷新：{path}")


if __name__ == "__main__":
    refresh()
