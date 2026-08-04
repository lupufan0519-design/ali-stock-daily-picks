from __future__ import annotations

import re
from pathlib import Path

from report_ui import STYLES, _strategy_grid_panel


ROOT = Path(__file__).resolve().parent
LATEST_HTML = ROOT / "results" / "latest.html"
START = "<!-- strategy-grid:start -->"
END = "<!-- strategy-grid:end -->"


def refresh(path: Path = LATEST_HTML) -> None:
    source = path.read_text(encoding="utf-8")
    updated, style_count = re.subn(
        r"<style>.*?</style>",
        f"<style>{STYLES}</style>",
        source,
        count=1,
        flags=re.DOTALL,
    )
    if style_count != 1:
        raise RuntimeError("页面中没有唯一的主样式区")

    panel = _strategy_grid_panel().lstrip()
    if not panel:
        raise RuntimeError("扩展买卖点结果不存在或无法读取")
    block = f"{START}\n      {panel}\n      {END}"
    if START in updated and END in updated:
        start = updated.index(START)
        end = updated.index(END, start) + len(END)
        updated = updated[:start] + block + updated[end:]
    else:
        repaint = updated.find('class="repaint-panel"')
        if repaint < 0:
            raise RuntimeError("页面中找不到信号重绘对照区")
        anchor = updated.find('\n      <article class="panel">', repaint)
        if anchor < 0:
            raise RuntimeError("页面中找不到历史验证规则表")
        updated = updated[:anchor] + f"\n      {block}" + updated[anchor:]

    path.write_text(updated, encoding="utf-8")
    print(f"历史研究栏目已刷新：{path}")


if __name__ == "__main__":
    refresh()
