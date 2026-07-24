from __future__ import annotations

import html
from datetime import datetime
from typing import Sequence

from strategy_tracker import POOL_NAME, secondary_strategy_stats, strategy_stats


STYLES = r"""
:root {
  color-scheme: light;
  --bg: #f5f7fb;
  --surface: #ffffff;
  --surface-soft: #f8fafc;
  --surface-blue: #eff6ff;
  --text: #172033;
  --muted: #667085;
  --muted-strong: #475467;
  --line: #dfe5ef;
  --line-strong: #cbd5e1;
  --primary: #1e40af;
  --primary-2: #2563eb;
  --accent: #b45309;
  --accent-soft: #fff7ed;
  --positive: #b42318;
  --positive-soft: #fff1f0;
  --negative: #087443;
  --negative-soft: #ecfdf3;
  --warning: #a15c07;
  --warning-soft: #fffaeb;
  --shadow: 0 16px 40px rgba(31, 42, 68, .08);
  --radius-lg: 22px;
  --radius-md: 15px;
  --radius-sm: 10px;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  min-width: 320px;
  background:
    radial-gradient(circle at 8% -10%, rgba(37, 99, 235, .12), transparent 28rem),
    linear-gradient(180deg, #f8fafc 0, var(--bg) 34rem);
  color: var(--text);
  font: 16px/1.6 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", "Microsoft YaHei", sans-serif;
  text-rendering: optimizeLegibility;
}
a { color: var(--primary); text-decoration: none; }
a:hover { text-decoration: underline; text-underline-offset: 3px; }
a:focus-visible, button:focus-visible, summary:focus-visible {
  outline: 3px solid rgba(37, 99, 235, .38);
  outline-offset: 3px;
  border-radius: 6px;
}
.shell { width: min(1440px, 100%); margin: 0 auto; padding: 0 24px 72px; }
.skip-link {
  position: fixed;
  top: 10px;
  left: 12px;
  z-index: 100;
  min-height: 44px;
  padding: 10px 14px;
  border-radius: 9px;
  background: var(--primary-2);
  color: white;
  transform: translateY(-150%);
}
.skip-link:focus { transform: translateY(0); }
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 64px;
  margin: 0 -24px;
  padding: 0 max(24px, calc((100vw - 1440px) / 2 + 24px));
  border-bottom: 1px solid rgba(203, 213, 225, .72);
  background: rgba(248, 250, 252, .88);
  backdrop-filter: blur(18px);
}
.brand { display: flex; align-items: center; gap: 11px; min-height: 44px; color: var(--text); font-weight: 760; }
.brand:hover { text-decoration: none; }
.brand-mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 11px;
  background: linear-gradient(145deg, var(--primary), var(--primary-2));
  color: white;
  box-shadow: 0 8px 20px rgba(30, 64, 175, .24);
}
.brand-mark svg { width: 21px; height: 21px; }
.nav { display: flex; align-items: center; gap: 6px; }
.nav a {
  display: inline-flex;
  align-items: center;
  min-height: 44px;
  padding: 0 12px;
  border-radius: 10px;
  color: var(--muted-strong);
  font-size: 14px;
  font-weight: 650;
}
.nav a:hover { background: var(--surface); color: var(--primary); text-decoration: none; }
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(280px, .6fr);
  gap: 24px;
  padding: 54px 0 26px;
}
.eyebrow {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0 0 12px;
  color: var(--primary);
  font-size: 13px;
  font-weight: 780;
  letter-spacing: .12em;
  text-transform: uppercase;
}
.eyebrow::before { content: ""; width: 28px; height: 2px; background: currentColor; }
h1, h2, h3 { margin: 0; letter-spacing: -.025em; }
h1 { max-width: 780px; font-size: clamp(34px, 5vw, 62px); line-height: 1.08; }
.hero-copy { max-width: 760px; margin: 18px 0 0; color: var(--muted-strong); font-size: 17px; }
.hero-aside {
  align-self: stretch;
  padding: 22px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: rgba(255, 255, 255, .86);
  box-shadow: var(--shadow);
}
.status-line { display: flex; align-items: flex-start; gap: 12px; }
.status-dot {
  flex: 0 0 auto;
  width: 11px;
  height: 11px;
  margin-top: 7px;
  border-radius: 999px;
  background: var(--negative);
  box-shadow: 0 0 0 5px rgba(8, 116, 67, .12);
}
.status-dot.stale { background: var(--warning); box-shadow: 0 0 0 5px rgba(161, 92, 7, .12); }
.status-dot.error { background: var(--positive); box-shadow: 0 0 0 5px rgba(180, 35, 24, .12); }
.status-title { font-weight: 760; }
.status-detail { margin-top: 2px; color: var(--muted); font-size: 14px; }
.timestamp {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 13px;
}
.timestamp strong {
  display: block;
  color: var(--text);
  font: 650 15px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace;
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin: 14px 0 40px;
}
.kpi {
  min-height: 126px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: 0 8px 24px rgba(31, 42, 68, .045);
}
.kpi-label { color: var(--muted); font-size: 13px; font-weight: 650; }
.kpi-value {
  display: block;
  margin: 6px 0 2px;
  font: 720 clamp(25px, 3vw, 36px)/1.2 ui-monospace, SFMono-Regular, Consolas, monospace;
}
.kpi-note { color: var(--muted); font-size: 12px; }
.section { scroll-margin-top: 88px; margin-top: 46px; }
.section-head {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 16px;
}
.section-kicker { color: var(--primary); font-size: 12px; font-weight: 780; letter-spacing: .12em; text-transform: uppercase; }
h2 { margin-top: 4px; font-size: clamp(25px, 3vw, 34px); }
h3 { font-size: 19px; }
.section-copy { max-width: 780px; margin: 8px 0 0; color: var(--muted); }
.panel {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: 0 10px 30px rgba(31, 42, 68, .045);
}
.panel + .panel { margin-top: 18px; }
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 20px 22px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-soft);
}
.panel-head p { margin: 3px 0 0; color: var(--muted); font-size: 13px; }
.count-badge, .chip, .state {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 30px;
  padding: 4px 10px;
  border-radius: 999px;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 720;
}
.count-badge { background: var(--surface-blue); color: var(--primary); }
.state.good { background: var(--negative-soft); color: var(--negative); }
.state.warn { background: var(--warning-soft); color: var(--warning); }
.state.neutral { background: #eef2f6; color: var(--muted-strong); }
.table-scroll { max-width: 100%; overflow-x: auto; overscroll-behavior-inline: contain; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 14px 16px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle; }
th {
  color: var(--muted);
  background: var(--surface);
  font-size: 12px;
  font-weight: 720;
  letter-spacing: .02em;
  white-space: nowrap;
}
tbody tr { transition: background-color 180ms ease; }
tbody tr:hover { background: #f8fbff; }
tbody tr:last-child td { border-bottom: 0; }
.stock-link { display: inline-flex; align-items: center; min-width: 44px; min-height: 44px; font-weight: 760; }
.stock-code { display: block; color: var(--muted); font: 600 12px/1.3 ui-monospace, SFMono-Regular, Consolas, monospace; }
.numeric { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-variant-numeric: tabular-nums; white-space: nowrap; }
.positive { color: var(--positive); }
.negative { color: var(--negative); }
.muted { color: var(--muted); }
.subline { display: block; margin-top: 3px; color: var(--muted); font-size: 12px; white-space: nowrap; }
.signal { min-width: 90px; }
.signal-mark { font-weight: 820; }
.signal-mark.yes { color: var(--negative); }
.signal-mark.no { color: #98a2b3; }
.chart-cell { min-width: 370px; }
.spark { display: block; width: min(420px, 100%); height: auto; }
.empty { padding: 42px 20px; color: var(--muted); text-align: center; }
.metrics {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 1px;
  border-bottom: 1px solid var(--line);
  background: var(--line);
}
.metric { min-height: 106px; padding: 16px; background: var(--surface); }
.metric-label { color: var(--muted); font-size: 12px; }
.metric-value { display: block; margin-top: 7px; font: 700 20px/1.3 ui-monospace, SFMono-Regular, Consolas, monospace; }
.rules {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.rule {
  padding: 17px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface);
}
.rule-num { color: var(--primary); font: 750 13px/1 ui-monospace, SFMono-Regular, Consolas, monospace; }
.rule strong { display: block; margin: 10px 0 4px; }
.rule p { margin: 0; color: var(--muted); font-size: 13px; }
.events {
  margin-bottom: 18px;
  padding: 16px 18px;
  border: 1px solid #fedf89;
  border-radius: var(--radius-md);
  background: var(--warning-soft);
}
.events strong { color: #7a2e0e; }
.events ul { margin: 8px 0 0; padding-left: 20px; color: #7a2e0e; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 0 0 12px; color: var(--muted); font-size: 12px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend i { width: 9px; height: 9px; border-radius: 999px; }
details { border-top: 1px solid var(--line); }
summary {
  min-height: 52px;
  padding: 14px 20px;
  color: var(--primary);
  cursor: pointer;
  font-weight: 700;
}
.disclaimer {
  margin-top: 48px;
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface);
  color: var(--muted);
  font-size: 13px;
}
footer { margin-top: 24px; color: var(--muted); font-size: 12px; }
@media (max-width: 1100px) {
  .kpi-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .rules { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  .shell { padding-inline: 16px; }
  .topbar { margin-inline: -16px; padding-inline: 16px; }
  .nav { display: none; }
  .hero { grid-template-columns: 1fr; padding-top: 34px; }
  .hero-aside { padding: 18px; }
  .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
  .kpi { min-height: 112px; padding: 14px; }
  .section { margin-top: 38px; }
  .section-head, .panel-head { align-items: flex-start; }
  .section-head { flex-direction: column; gap: 8px; }
  .panel-head { padding: 16px; }
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rules { grid-template-columns: 1fr; }
  th, td { padding: 12px 14px; }
  .chart-cell { min-width: 320px; }
}
@media (max-width: 430px) {
  h1 { font-size: 34px; }
  .kpi-grid { grid-template-columns: 1fr 1fr; }
  .kpi-value { font-size: 24px; }
  .metrics { grid-template-columns: 1fr 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --bg: #0b1220;
    --surface: #111a2b;
    --surface-soft: #151f32;
    --surface-blue: #172554;
    --text: #edf2f7;
    --muted: #9aa8bc;
    --muted-strong: #c0cad8;
    --line: #26344a;
    --line-strong: #3b4b64;
    --primary: #93c5fd;
    --primary-2: #60a5fa;
    --accent: #fbbf24;
    --positive: #ff8a80;
    --positive-soft: #3a2024;
    --negative: #6ee7b7;
    --negative-soft: #12392d;
    --warning: #fcd34d;
    --warning-soft: #352b13;
    --shadow: 0 18px 44px rgba(0, 0, 0, .24);
  }
  body {
    background:
      radial-gradient(circle at 8% -10%, rgba(37, 99, 235, .22), transparent 28rem),
      linear-gradient(180deg, #101827 0, var(--bg) 34rem);
  }
  .topbar { background: rgba(11, 18, 32, .86); }
  .hero-aside { background: rgba(17, 26, 43, .92); }
  tbody tr:hover { background: #152136; }
  .count-badge { color: #bfdbfe; }
  .state.neutral { background: #26344a; }
  .events strong, .events ul { color: #fde68a; }
}
"""


LIVE_SCRIPT = r"""
(() => {
  const status = document.querySelector("#market-status");
  const detail = document.querySelector("#market-detail");
  const quoteTime = document.querySelector("#quote-time");
  const dot = document.querySelector("#status-dot");
  const formatPct = (value) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
  const setTone = (element, value) => {
    element.classList.toggle("positive", value >= 0);
    element.classList.toggle("negative", value < 0);
  };
  async function refreshLive() {
    try {
      const response = await fetch(`live.json?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      status.textContent = data.market_label || "行情已更新";
      detail.textContent = data.note || "盘中行情只更新价格，不改变收盘筛选信号";
      quoteTime.textContent = data.generated_at_display || data.generated_at;
      dot.className = `status-dot ${data.is_stale ? "stale" : ""}`;
      Object.entries(data.quotes || {}).forEach(([code, quote]) => {
        document.querySelectorAll(`[data-live-code="${code}"]`).forEach((row) => {
          const price = row.querySelector("[data-live-price]");
          const change = row.querySelector("[data-live-change]");
          const ret = row.querySelector("[data-live-return]");
          if (price) price.textContent = Number(quote.price).toFixed(2);
          if (change) {
            change.textContent = formatPct(Number(quote.change_pct));
            setTone(change, Number(quote.change_pct));
          }
          if (ret && row.dataset.entryPrice) {
            const value = (Number(quote.price) / Number(row.dataset.entryPrice) - 1) * 100;
            ret.textContent = formatPct(value);
            setTone(ret, value);
          }
        });
      });
    } catch (error) {
      dot.className = "status-dot stale";
      status.textContent = "实时行情暂不可用";
      detail.textContent = "当前仍显示最近一次已验证的收盘数据";
    }
  }
  refreshLive();
  window.setInterval(refreshLive, 60_000);
})();
"""


def _esc(value: object) -> str:
    return html.escape(str(value))


def _link(code: str, market: int) -> str:
    prefix = "sh" if int(market) == 1 else "sz" if int(market) == 0 else "bj"
    return f"https://quote.eastmoney.com/{prefix}{code}.html"


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    css = "positive" if value >= 0 else "negative"
    return f'<span class="numeric {css}">{value:+.2f}%</span>'


def _stock_cell(code: str, name: str, market: int) -> str:
    return (
        f'<a class="stock-link" href="{_link(code, market)}" target="_blank" '
        f'rel="noreferrer">{_esc(name)}</a><span class="stock-code">{_esc(code)}</span>'
    )


def _signal(ok: bool, note: str) -> str:
    mark = "✓" if ok else "—"
    css = "yes" if ok else "no"
    return (
        f'<div class="signal"><span class="signal-mark {css}">{mark}</span>'
        f'<span class="subline">{_esc(note)}</span></div>'
    )


def _position_row(position: dict) -> str:
    status_class = "warn" if int(position.get("missing_streak", 0)) else "good"
    entry = float(position["entry_price"])
    return f"""
    <tr data-live-code="{_esc(position['code'])}" data-entry-price="{entry:.4f}">
      <td>{_stock_cell(position['code'], position['name'], int(position['market']))}</td>
      <td class="numeric">{position['entry_date']}<span class="subline">{entry:.2f} 元</span></td>
      <td><span class="numeric" data-live-price>{float(position['last_close']):.2f}</span>
          <span class="subline">{_esc(position['last_date'])}</span></td>
      <td><span data-live-return>{_pct(float(position['return_pct']))}</span></td>
      <td class="numeric">{int(position['holding_days'])} 日</td>
      <td><span class="state {status_class}">{_esc(position['status'])}</span></td>
    </tr>"""


def _closed_row(position: dict) -> str:
    return f"""
    <tr>
      <td>{_stock_cell(position['code'], position['name'], int(position['market']))}</td>
      <td class="numeric">{_esc(position['entry_date'])}<span class="subline">{float(position['entry_price']):.2f} 元</span></td>
      <td class="numeric">{_esc(position.get('exit_date', ''))}<span class="subline">{float(position.get('exit_price', 0)):.2f} 元</span></td>
      <td>{_pct(float(position.get('exit_return_pct', 0.0)))}</td>
      <td class="numeric">{int(position.get('holding_days', 0))} 日</td>
      <td class="muted">{_esc(position.get('exit_reason', ''))}</td>
    </tr>"""


def _evaluation_row(item, observation: bool = False) -> str:
    entry_price = float(item.close)
    base = f"""
    <tr data-live-code="{_esc(item.code)}" data-entry-price="{entry_price:.4f}">
      <td>{_stock_cell(item.code, item.name, int(item.market))}</td>
      <td><span class="numeric" data-live-price>{entry_price:.2f}</span>
          <span class="subline numeric" data-live-change>{item.change_pct:+.2f}%</span></td>
      <td class="chart-cell">{item.chart}</td>"""
    if observation:
        priority = "龙虎优先" if item.cross_ok else "见底候选" if item.bottom_ok else "普通观察"
        return base + f"""
      <td>{_signal(item.cross_ok, item.cross_date or '未出现')}</td>
      <td>{_signal(item.bottom_ok, item.bottom_date or '未出现')}</td>
      <td>{_signal(item.yellow_ok, f'连续 {item.yellow_count} 根')}</td>
      <td>{_signal(item.limit_up_ok, item.limit_up_date or '未出现')}</td>
      <td><span class="state neutral">{priority}</span></td>
    </tr>"""
    return base + f"""
      <td>{_signal(item.bottom_ok, item.bottom_date or '未命中')}</td>
      <td>{_signal(item.cross_ok, item.cross_date or '未命中')}</td>
      <td>{_signal(item.limit_up_ok, item.limit_up_date or '未命中')}</td>
      <td>{_signal(item.yellow_ok, f'连续 {item.yellow_count} 根')}</td>
    </tr>"""


def _events(events: Sequence[dict]) -> str:
    labels = {
        "added": "加入主选区",
        "signal_lost": "龙虎信号消失，进入待确认",
        "signal_restored": "龙虎信号恢复",
        "removed": "连续第二个交易日未恢复，已移出",
        "ineligible_removed": "股票名称含 ST，已移出",
        "secondary_added": "加入次选区",
        "secondary_removed": "龙虎信号消失，已移出次选区",
        "secondary_promoted": "条件补齐，升级主选区",
    }
    items = []
    for event in events:
        suffix = (
            f"，阶段收益 {float(event['return_pct']):+.2f}%"
            if "return_pct" in event
            else ""
        )
        items.append(
            f"<li>{_esc(event.get('code', ''))} {_esc(event.get('name', ''))}："
            f"{_esc(labels.get(event.get('type'), '状态更新'))}{suffix}</li>"
        )
    return (
        f'<div class="events"><strong>今日状态变动</strong><ul>{"".join(items)}</ul></div>'
        if items
        else ""
    )


def _metric(label: str, value: str) -> str:
    return (
        f'<div class="metric"><span class="metric-label">{label}</span>'
        f'<strong class="metric-value">{value}</strong></div>'
    )


def render_report(
    evaluations: Sequence,
    cfg: dict,
    scanned: int,
    errors: Sequence[str],
    strategy_state: dict,
    events: Sequence[dict],
) -> str:
    selected = [item for item in evaluations if item.selected and item.eligible]
    secondary = [
        item
        for item in evaluations
        if item.eligible
        and not item.selected
        and item.cross_ok
        and item.yellow_ok
        and (item.bottom_ok or item.limit_up_ok)
    ]
    near = sorted(
        [
            item
            for item in evaluations
            if item.eligible
            and not item.selected
            and item.matched_count >= cfg["near_match_minimum"]
        ],
        key=lambda item: (
            item.cross_ok,
            item.bottom_ok,
            item.yellow_ok,
            item.limit_up_ok,
            item.cross_date,
            item.bottom_date,
        ),
        reverse=True,
    )[:30]
    trade_date = max((item.date for item in evaluations), default="无数据")
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    main_stats = strategy_stats(strategy_state)
    secondary_stats = secondary_strategy_stats(strategy_state)
    active_rows = "".join(_position_row(item) for item in strategy_state["active"])
    secondary_active_rows = "".join(
        _position_row(item) for item in strategy_state.get("secondary_active", [])
    )
    selected_rows = "".join(_evaluation_row(item) for item in selected)
    near_rows = "".join(_evaluation_row(item, True) for item in near)
    closed_rows = "".join(_closed_row(item) for item in strategy_state["closed"][:50])
    secondary_closed_rows = "".join(
        _closed_row(item) for item in strategy_state.get("secondary_closed", [])[:50]
    )
    empty6 = '<tr><td class="empty" colspan="6">当前没有符合条件的记录</td></tr>'
    empty7 = '<tr><td class="empty" colspan="7">今日没有股票同时满足四项条件</td></tr>'
    empty8 = '<tr><td class="empty" colspan="8">当前没有满足三项条件的观察标的</td></tr>'
    legend = """<div class="legend" aria-label="图表图例">
        <span><i style="background:#ef5350"></i>上涨 K 线</span>
        <span><i style="background:#26a69a"></i>下跌 K 线</span>
        <span><i style="background:#f4d35e"></i>龙线下方实体</span>
        <span><i style="background:#ff5c70"></i>龙线</span>
        <span><i style="background:#55c6e8"></i>虎线</span>
      </div>"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#f8fafc">
  <meta name="description" content="卢氏龙虎趋势池：沪深 A 股主选、次选与盘中行情跟踪">
  <title>卢氏龙虎趋势池 · {trade_date}</title>
  <style>{STYLES}</style>
</head>
<body>
<a class="skip-link" href="#content">跳到主要内容</a>
<div class="shell">
  <header class="topbar">
    <a class="brand" href="#content" aria-label="返回页面顶部">
      <span class="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none"><path d="M4 17V9m5 8V5m5 12v-6m5 6V3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
      </span>
      <span>卢氏龙虎趋势池</span>
    </a>
    <nav class="nav" aria-label="页面导航">
      <a href="#pool">趋势池</a><a href="#signals">今日信号</a><a href="#watch">观察区</a><a href="#rules">规则</a>
    </nav>
  </header>

  <main id="content">
    <section class="hero">
      <div>
        <p class="eyebrow">A-share signal dashboard</p>
        <h1>有人找机会，有人专挑风险</h1>
        <p class="hero-copy">主选、次选严格按收盘规则更新；盘中仅刷新价格、涨跌幅与跟踪收益，不改变策略信号。</p>
      </div>
      <aside class="hero-aside" aria-live="polite">
        <div class="status-line">
          <span class="status-dot" id="status-dot" aria-hidden="true"></span>
          <div><div class="status-title" id="market-status">收盘数据已验证</div>
          <div class="status-detail" id="market-detail">交易日 {trade_date} · 云端行情自动刷新</div></div>
        </div>
        <div class="timestamp">最新行情时间<strong id="quote-time">{generated}</strong></div>
      </aside>
    </section>

    <section class="kpi-grid" aria-label="核心概览">
      <article class="kpi"><span class="kpi-label">主选跟踪</span><strong class="kpi-value">{main_stats['active_count']}</strong><span class="kpi-note">严格四项同时满足</span></article>
      <article class="kpi"><span class="kpi-label">次选跟踪</span><strong class="kpi-value">{secondary_stats['active_count']}</strong><span class="kpi-note">龙虎 + 黄柱 + 另一项</span></article>
      <article class="kpi"><span class="kpi-label">今日严格命中</span><strong class="kpi-value">{len(selected)}</strong><span class="kpi-note">eligible=true</span></article>
      <article class="kpi"><span class="kpi-label">观察标的</span><strong class="kpi-value">{len(near)}</strong><span class="kpi-note">仅观察，不计入选</span></article>
      <article class="kpi"><span class="kpi-label">市场扫描</span><strong class="kpi-value">{scanned}</strong><span class="kpi-note">失败 {len(errors)} 只 · ST 排除</span></article>
    </section>

    <section class="section" id="pool">
      <div class="section-head"><div><span class="section-kicker">Tracked portfolio</span><h2>{POOL_NAME}</h2>
      <p class="section-copy">加入日收盘价作为基准，盘中收益由最新行情计算；策略状态只在收盘完整扫描后变化。</p></div></div>
{_events(events)}
      <article class="panel">
        <div class="panel-head"><div><h3>主选区</h3><p>四项条件同时满足，龙虎信号连续两日失效后移出</p></div><span class="count-badge">{main_stats['active_count']} 只</span></div>
        <div class="metrics">
          {_metric('当前成功率', _pct(main_stats['current_success_rate']))}
          {_metric('样本平均收益', _pct(main_stats['all_average_return']))}
          {_metric('已完成胜率', _pct(main_stats['closed_success_rate']))}
          {_metric('累计实现收益', _pct(main_stats['realized_compound_return']))}
          {_metric('信号待确认', f"{main_stats['warning_count']} 只")}
          {_metric('累计样本', f"{main_stats['sample_count']} 只")}
        </div>
        <div class="table-scroll"><table><thead><tr><th>股票</th><th>加入日 / 价格</th><th>最新价 / 日期</th><th>跟踪收益</th><th>时长</th><th>状态</th></tr></thead>
        <tbody>{active_rows or empty6}</tbody></table></div>
      </article>

      <article class="panel">
        <div class="panel-head"><div><h3>次选区</h3><p>龙腾跃虎与连续黄柱必选，再满足见底或42日涨停之一</p></div><span class="count-badge">{secondary_stats['active_count']} 只</span></div>
        <div class="metrics">
          {_metric('当前成功率', _pct(secondary_stats['current_success_rate']))}
          {_metric('跟踪平均收益', _pct(secondary_stats['active_average_return']))}
          {_metric('全部平均收益', _pct(secondary_stats['all_average_return']))}
          {_metric('跟踪中', f"{secondary_stats['active_count']} 只")}
          {_metric('已移出', f"{secondary_stats['closed_count']} 只")}
          {_metric('累计样本', f"{secondary_stats['sample_count']} 只")}
        </div>
        <div class="table-scroll"><table><thead><tr><th>股票</th><th>加入日 / 价格</th><th>最新价 / 日期</th><th>跟踪收益</th><th>时长</th><th>状态</th></tr></thead>
        <tbody>{secondary_active_rows or empty6}</tbody></table></div>
      </article>
    </section>

    <section class="section" id="signals">
      <div class="section-head"><div><span class="section-kicker">Daily selection</span><h2>今日严格入选</h2>
      </div><span class="count-badge">{len(selected)} 只</span></div>
{legend}
      <div class="panel table-scroll"><table><thead><tr><th>股票</th><th>收盘 / 涨跌</th><th>近42日 K 线与龙虎线</th><th>可能见底</th><th>龙腾跃虎</th><th>42日涨停</th><th>连续黄柱</th></tr></thead>
      <tbody>{selected_rows or empty7}</tbody></table></div>
    </section>

    <section class="section" id="watch">
      <div class="section-head"><div><span class="section-kicker">Watchlist</span><h2>观察区</h2>
      <p class="section-copy">满足至少三项的接近标的，仅用于观察，不纳入主选或次选收益。</p></div><span class="count-badge">{len(near)} 只</span></div>
{legend}
      <div class="panel table-scroll"><table><thead><tr><th>股票</th><th>价格 / 涨跌</th><th>近42日 K 线与龙虎线</th><th>龙腾跃虎</th><th>可能见底</th><th>连续黄柱</th><th>42日涨停</th><th>优先级</th></tr></thead>
      <tbody>{near_rows or empty8}</tbody></table></div>
    </section>

    <section class="section" id="rules">
      <div class="section-head"><div><span class="section-kicker">Methodology</span><h2>筛选规则</h2></div></div>
      <div class="rules">
        <article class="rule"><span class="rule-num">01</span><strong>可能见底</strong><p>最近 {cfg['bottom_lookback_days']} 个交易日出现信号。</p></article>
        <article class="rule"><span class="rule-num">02</span><strong>龙腾跃虎</strong><p>最近 {cfg['cross_lookback_days']} 日出现交叉，且龙线仍在虎线上方。</p></article>
        <article class="rule"><span class="rule-num">03</span><strong>近期涨停</strong><p>最近 {cfg['limit_up_lookback_days']} 个交易日至少一次收盘涨停。</p></article>
        <article class="rule"><span class="rule-num">04</span><strong>连续黄柱</strong><p>实体在龙线下方的部分呈黄色，连续至少 {cfg['yellow_consecutive_days']} 日。</p></article>
      </div>
    </section>

    <section class="section">
      <div class="panel">
        <details><summary>查看主选区历史移出记录</summary>
          <div class="table-scroll"><table><thead><tr><th>股票</th><th>加入</th><th>移出</th><th>收益</th><th>时长</th><th>原因</th></tr></thead><tbody>{closed_rows or empty6}</tbody></table></div>
        </details>
        <details><summary>查看次选区历史移出记录</summary>
          <div class="table-scroll"><table><thead><tr><th>股票</th><th>加入</th><th>移出</th><th>收益</th><th>时长</th><th>原因</th></tr></thead><tbody>{secondary_closed_rows or empty6}</tbody></table></div>
        </details>
      </div>
    </section>

    <p class="disclaimer">本页面按技术条件机械筛选，不构成投资建议。收益按每只股票等权计算，未计手续费、滑点和实际仓位；免费公开行情仅适合个人研究与小范围分享。</p>
  </main>
  <footer>收盘交易日 {trade_date} · 报告生成 {generated} · 沪深 A 股 {scanned} 只 · 数据失败 {len(errors)} 只</footer>
</div>
<script>{LIVE_SCRIPT}</script>
</body>
</html>"""
