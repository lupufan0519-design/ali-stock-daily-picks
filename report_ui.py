from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Sequence

from observation import visible_observations
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
.state.ended { background: rgba(208, 48, 48, .12); color: #b42318; }
.state.neutral { background: #eef2f6; color: var(--muted-strong); }
.status-operation { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.operation-ticket {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: 6px 10px;
  border: 1px solid currentColor;
  border-radius: 9px;
  font-size: 12px;
  font-weight: 820;
  line-height: 1.2;
  letter-spacing: .01em;
  white-space: nowrap;
}
.operation-ticket.wait { color: #475467; background: #f2f4f7; border-color: #d0d5dd; }
.operation-ticket.buy { color: #c4322b; background: #fff1f0; border-color: #f3aaa5; }
.operation-ticket.hold { color: #175cd3; background: #eff6ff; border-color: #a9c7f7; }
.operation-ticket.caution { color: #9a6700; background: #fff8e7; border-color: #e8c56a; }
.operation-ticket.sell { color: #08745b; background: #ecfdf3; border-color: #83d5bd; }
.operation-ticket.confirm { color: #9f3a17; background: #fff4ed; border-color: #f2aa83; }
.status-detail-line { max-width: 360px; margin-top: 6px; white-space: normal; line-height: 1.45; }
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
.settlement-note {
  margin: 0;
  padding: 12px 18px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-blue);
  color: var(--primary);
  font-size: 13px;
  font-weight: 650;
}
.pool-composition {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 9px;
  color: var(--muted);
  font-size: 12px;
}
.pool-composition span {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 3px 9px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface);
}
.pool-group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 13px 18px 9px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.pool-group-head strong { font-size: 14px; }
.pool-group-head span { color: var(--muted); font-size: 12px; }
.pool-group-head.settled {
  border-top: 1px solid var(--line);
  background: var(--surface-soft);
}
.live-exit-list {
  display: grid;
  gap: 8px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--line);
  background: #fff8f5;
}
.live-exit-list[hidden] { display: none; }
.live-exit-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 10px 12px;
  border: 1px solid rgba(208, 48, 48, .18);
  border-radius: 12px;
  background: var(--surface);
}
.live-exit-stock { min-width: 0; }
.live-exit-stock strong { display: block; }
.live-exit-stock small { display: block; margin-top: 2px; color: var(--muted); }
.live-exit-result { flex: 0 0 auto; text-align: right; }
.live-exit-result .subline { margin-top: 4px; }
.date-strip {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-top: 12px;
}
.date-chip {
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 10px;
  background: rgba(4,20,35,.32);
  color: rgba(236,248,255,.7);
  font-size: 10px;
}
.date-chip strong {
  display: block;
  overflow: hidden;
  margin-top: 1px;
  color: #fff;
  font: 690 12px/1.3 ui-monospace, SFMono-Regular, Consolas, monospace;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.live-pool-status { min-width: 150px; }
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
.validation-lead {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(260px, .85fr);
  gap: 14px;
  margin-bottom: 14px;
}
.validation-verdict {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 22px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: linear-gradient(145deg, var(--surface), var(--surface-blue));
}
.validation-verdict strong { display: block; margin-bottom: 7px; font-size: 19px; }
.validation-verdict p { margin: 0; color: var(--muted-strong); }
.trend-case {
  --case-up: #e43b36;
  --case-down: #139b68;
  --case-start: #2457d6;
  --case-end: #d4512f;
  --case-peak: #b7790b;
  --case-grid: color-mix(in srgb, var(--line) 76%, transparent);
  margin-top: 20px;
  min-width: 0;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--line-strong) 72%, transparent);
  border-radius: 18px;
  background: color-mix(in srgb, var(--surface) 91%, transparent);
  box-shadow: 0 14px 34px rgba(30, 64, 175, .08);
}
.trend-case-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 15px 17px 10px;
}
.trend-case-head strong { margin: 0; font-size: 15px; }
.trend-case-head span { color: var(--muted); font-size: 11px; }
.trend-case-legend {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 9px;
  border: 1px solid color-mix(in srgb, var(--case-start) 22%, var(--line));
  border-radius: 999px;
  background: color-mix(in srgb, var(--case-start) 7%, var(--surface));
  font-weight: 750;
}
.trend-case-legend span { display: inline-flex; align-items: center; gap: 5px; color: var(--muted-strong); }
.trend-case-legend i { display: block; width: 17px; height: 2px; border-radius: 999px; }
.trend-case-legend .dragon { background: #ff5c70; box-shadow: 0 0 0 1px rgba(255,92,112,.08); }
.trend-case-legend .tiger { background: #55c6e8; box-shadow: 0 0 0 1px rgba(85,198,232,.08); }
.trend-case-legend .yellow-formula,
.trend-case-legend .yellow-qualified { width: 10px; height: 10px; border-radius: 2px; }
.trend-case-legend .yellow-formula { background: color-mix(in srgb, #f4d35e 48%, transparent); }
.trend-case-legend .yellow-qualified { border: 1.5px solid #b7790b; background: #f4d35e; }
.trend-case-wave-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 12px 5px;
  color: var(--muted);
  font-size: 10px;
}
.trend-case-wave-head strong { margin: 0; color: var(--text); font-size: 12px; }
.trend-case-wave-head span { text-align: right; }
.trend-case-canvas {
  position: relative;
  height: clamp(300px, 37vw, 390px);
  margin: 0 10px;
  overflow: hidden;
  border-radius: 14px;
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--surface-blue) 34%, transparent), transparent 48%),
    var(--surface-soft);
}
.trend-case-svg { display: block; width: 100%; height: 100%; }
.trend-case-svg line, .trend-case-svg path, .trend-case-svg rect, .trend-case-svg circle { vector-effect: non-scaling-stroke; }
.case-grid { stroke: var(--case-grid); stroke-width: 1; stroke-dasharray: 3 5; }
.case-axis-label { fill: var(--muted); font: 600 10px/1 ui-monospace, SFMono-Regular, Consolas, monospace; }
.case-wick { stroke-width: 1.25; }
.case-candle.up .case-wick { stroke: var(--case-up); }
.case-candle.up .case-body { fill: var(--case-up); }
.case-candle.down .case-wick { stroke: var(--case-down); }
.case-candle.down .case-body { fill: var(--case-down); }
.case-yellow-body { fill: #f4d35e; stroke: #d8ad12; stroke-width: .45; }
.case-yellow-body.contextual { opacity: .48; stroke-width: .25; }
.case-yellow-body.qualified { opacity: 1; stroke: #9a5a00; stroke-width: 1.5; filter: drop-shadow(0 0 3px rgba(183,121,11,.48)); }
.case-yellow-label { fill: #8d5a00; font: 800 9px/1 "Microsoft YaHei", sans-serif; }
.case-candle:hover .case-body { filter: drop-shadow(0 0 5px currentColor); }
.case-dragon-line, .case-tiger-line { fill: none; stroke-width: 2.45; stroke-linecap: round; stroke-linejoin: round; }
.case-dragon-line { stroke: #ff4f68; filter: drop-shadow(0 0 2px rgba(255,79,104,.28)); }
.case-tiger-line { stroke: #25b9df; filter: drop-shadow(0 0 2px rgba(37,185,223,.25)); }
.case-line-label { font: 850 10px/1 "Microsoft YaHei", sans-serif; paint-order: stroke; stroke: var(--surface-soft); stroke-width: 3px; stroke-linejoin: round; }
.case-line-label.dragon { fill: #e83d58; }
.case-line-label.tiger { fill: #129fc4; }
.case-cross-guide { stroke: var(--case-start); stroke-width: 1; stroke-dasharray: 3 4; opacity: .62; }
.case-cross-ring { fill: var(--surface); stroke: var(--case-start); stroke-width: 2.2; }
.case-cross-label { fill: var(--case-start); font: 800 11px/1 "Microsoft YaHei", sans-serif; }
.case-stop-line { stroke: var(--case-end); stroke-width: 1.25; stroke-dasharray: 5 4; }
.case-stop-label { fill: var(--case-end); font: 750 10px/1 ui-monospace, SFMono-Regular, Consolas, monospace; }
.case-arrow-start, .case-arrow-end { fill: none; stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; }
.case-arrow-start { stroke: var(--case-start); marker-end: url(#case-arrow-blue); }
.case-arrow-end { stroke: var(--case-end); marker-end: url(#case-arrow-red); }
.case-exit-target { fill: color-mix(in srgb, var(--surface) 82%, transparent); stroke: var(--case-end); stroke-width: 2.4; filter: drop-shadow(0 0 3px rgba(212,81,47,.32)); }
.case-peak-ring { fill: var(--surface); stroke: var(--case-peak); stroke-width: 2.5; }
.case-peak-guide { stroke: var(--case-peak); stroke-width: 1; stroke-dasharray: 3 4; }
.case-pin {
  position: absolute;
  z-index: 2;
  display: grid;
  gap: 1px;
  min-width: 96px;
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface) 92%, transparent);
  box-shadow: 0 8px 22px rgba(23,32,51,.12);
  backdrop-filter: blur(8px);
  pointer-events: none;
}
.case-pin b { font-size: 12px; line-height: 1.15; }
.case-pin small { color: var(--muted); font: 650 10px/1.25 ui-monospace, SFMono-Regular, Consolas, monospace; }
.case-pin.start { top: 9px; left: 7%; border-color: color-mix(in srgb, var(--case-start) 34%, var(--line)); }
.case-pin.start b { color: var(--case-start); }
.case-pin.peak { top: 9px; left: 58%; border-color: color-mix(in srgb, var(--case-peak) 38%, var(--line)); }
.case-pin.peak b { color: var(--case-peak); }
.case-pin.end { right: 2%; top: 9px; border-color: color-mix(in srgb, var(--case-end) 38%, var(--line)); }
.case-pin.end b { color: var(--case-end); }
.trend-case-notes {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-top: 1px solid var(--line);
}
.trend-case-note { padding: 11px 13px 13px; }
.trend-case-note + .trend-case-note { border-left: 1px solid var(--line); }
.trend-case-note span { display: block; color: var(--muted); font-size: 10px; }
.trend-case-note strong { min-width: 0; margin: 3px 0 0; overflow-wrap: anywhere; font-size: 13px; }
.trend-case-note.start strong { color: var(--case-start); }
.trend-case-note.peak strong { color: var(--case-peak); }
.trend-case-note.end strong { color: var(--case-end); }
.trend-case-foot { padding: 0 15px 14px; color: var(--muted); font-size: 10px; }
.reveal.is-visible .case-candle { animation: case-candle-in 420ms both; animation-delay: calc(var(--i) * 12ms); }
.reveal.is-visible .case-arrow-start, .reveal.is-visible .case-arrow-end { stroke-dasharray: 280; animation: case-arrow-draw 900ms 520ms both; }
@keyframes case-candle-in { from { opacity: 0; transform: translateY(8px); } }
@keyframes case-arrow-draw { from { stroke-dashoffset: 280; } to { stroke-dashoffset: 0; } }
.validation-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.validation-fact {
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface);
}
.validation-fact span { display: block; color: var(--muted); font-size: 12px; }
.validation-fact strong { display: block; margin-top: 5px; font-size: 20px; }
.repaint-panel {
  --repaint-live: #2457d6;
  --repaint-lost: #d4512f;
  --repaint-kept: #11845b;
  position: relative;
  isolation: isolate;
  margin-bottom: 14px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--primary) 24%, var(--line));
  border-radius: var(--radius-lg);
  background:
    radial-gradient(circle at 9% 6%, color-mix(in srgb, var(--repaint-live) 11%, transparent), transparent 31%),
    radial-gradient(circle at 94% 91%, color-mix(in srgb, var(--repaint-lost) 9%, transparent), transparent 28%),
    var(--surface);
  box-shadow: 0 18px 45px rgba(30, 64, 175, .08);
}
.repaint-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 22px 22px 15px;
}
.repaint-head h3 { margin: 3px 0 5px; font-size: 22px; }
.repaint-head p { max-width: 760px; margin: 0; color: var(--muted-strong); }
.repaint-badge {
  flex: 0 0 auto;
  padding: 7px 10px;
  border: 1px solid color-mix(in srgb, var(--repaint-live) 25%, var(--line));
  border-radius: 999px;
  background: color-mix(in srgb, var(--repaint-live) 6%, var(--surface));
  color: var(--repaint-live);
  font-size: 11px;
  font-weight: 800;
}
.repaint-lineage {
  display: grid;
  grid-template-columns: minmax(180px, .75fr) 42px minmax(0, 1.25fr);
  align-items: stretch;
  gap: 12px;
  padding: 0 22px 18px;
}
.lineage-origin,
.lineage-branch {
  min-width: 0;
  padding: 17px;
  border: 1px solid var(--line);
  border-radius: 15px;
  background: color-mix(in srgb, var(--surface) 92%, transparent);
}
.lineage-origin { display: flex; flex-direction: column; justify-content: center; }
.lineage-origin span,
.lineage-branch span { color: var(--muted); font-size: 11px; }
.lineage-origin strong { margin: 4px 0 2px; color: var(--repaint-live); font-size: clamp(30px, 4vw, 48px); line-height: 1; }
.lineage-origin small,
.lineage-branch small { color: var(--muted); }
.lineage-fork { position: relative; min-height: 142px; }
.lineage-fork::before,
.lineage-fork::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  border: solid color-mix(in srgb, var(--repaint-live) 42%, var(--line));
}
.lineage-fork::before { top: 50%; border-width: 1px 0 0; }
.lineage-fork::after { top: 25%; bottom: 25%; border-width: 1px 1px 1px 0; border-radius: 0 12px 12px 0; }
.lineage-branches { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.lineage-branch strong { display: block; margin: 4px 0; font-size: 25px; }
.lineage-branch.lost { border-color: color-mix(in srgb, var(--repaint-lost) 27%, var(--line)); }
.lineage-branch.lost strong { color: var(--repaint-lost); }
.lineage-branch.kept { border-color: color-mix(in srgb, var(--repaint-kept) 27%, var(--line)); }
.lineage-branch.kept strong { color: var(--repaint-kept); }
.repaint-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border-top: 1px solid var(--line); }
.repaint-cohort { min-width: 0; padding: 20px 22px; }
.repaint-cohort + .repaint-cohort { border-left: 1px solid var(--line); }
.repaint-cohort h4 { margin: 0 0 4px; font-size: 17px; }
.repaint-cohort > p { min-height: 42px; margin: 0 0 15px; color: var(--muted); font-size: 12px; }
.repaint-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.repaint-stat { padding: 11px; border-radius: 11px; background: var(--surface-soft); }
.repaint-stat span { display: block; min-height: 28px; color: var(--muted); font-size: 10px; }
.repaint-stat strong { display: block; margin-top: 3px; font-size: 17px; }
.repaint-cohort.hindsight {
  background: repeating-linear-gradient(-45deg, transparent, transparent 16px, color-mix(in srgb, var(--warning-soft) 42%, transparent) 16px, color-mix(in srgb, var(--warning-soft) 42%, transparent) 32px);
}
.repaint-warning {
  margin: 0 22px 18px;
  padding: 12px 14px;
  border-left: 3px solid var(--repaint-lost);
  border-radius: 0 10px 10px 0;
  background: color-mix(in srgb, var(--repaint-lost) 7%, var(--surface));
  color: var(--muted-strong);
  font-size: 12px;
}
.repaint-strategy { display: grid; grid-template-columns: 1.05fr .95fr; gap: 12px; padding: 0 22px 20px; }
.repaint-strategy-card { padding: 16px; border: 1px solid var(--line); border-radius: 14px; background: var(--surface); }
.repaint-strategy-card strong { display: block; margin-bottom: 7px; }
.repaint-strategy-card p { margin: 0; color: var(--muted-strong); font-size: 12px; }
.repaint-strategy-card em { color: var(--repaint-live); font-style: normal; font-weight: 800; }
.repaint-failures { margin: 0 22px 20px; border: 1px solid var(--line); border-radius: 13px; }
.repaint-failures summary { min-height: 0; padding: 12px 14px; }
.repaint-failure-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; padding: 0 14px 14px; }
.repaint-failure { padding: 10px; border-radius: 10px; background: var(--surface-soft); font-size: 11px; }
.repaint-failure a { color: var(--text); font-weight: 800; text-decoration: none; }
.repaint-failure span { display: block; margin-top: 3px; color: var(--muted); }
.strategy-lab {
  --lab-success: #11845b;
  --lab-balanced: #2457d6;
  --lab-return: #b7790b;
  margin-bottom: 14px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.strategy-lab-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 22px;
  border-bottom: 1px solid var(--line);
  background:
    linear-gradient(90deg, color-mix(in srgb, var(--lab-success) 8%, transparent), transparent 29%),
    linear-gradient(270deg, color-mix(in srgb, var(--lab-return) 9%, transparent), transparent 29%);
}
.strategy-lab-head h3 { margin: 3px 0 5px; font-size: 22px; }
.strategy-lab-head p { max-width: 760px; margin: 0; color: var(--muted-strong); }
.strategy-lab-stamp {
  flex: 0 0 auto;
  display: grid;
  gap: 2px;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: color-mix(in srgb, var(--surface) 88%, transparent);
  text-align: right;
}
.strategy-lab-stamp strong { font: 800 17px/1 ui-monospace, SFMono-Regular, Consolas, monospace; }
.strategy-lab-stamp small { color: var(--muted); font-size: 9px; }
.strategy-tickets {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  padding: 18px 22px;
}
.strategy-ticket {
  --ticket-tone: var(--lab-balanced);
  position: relative;
  min-width: 0;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--ticket-tone) 28%, var(--line));
  border-radius: 16px;
  background: color-mix(in srgb, var(--ticket-tone) 4%, var(--surface));
}
.strategy-ticket::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--ticket-tone);
}
.strategy-ticket.success { --ticket-tone: var(--lab-success); }
.strategy-ticket.return { --ticket-tone: var(--lab-return); }
.strategy-ticket.recommended { box-shadow: 0 15px 34px color-mix(in srgb, var(--ticket-tone) 14%, transparent); transform: translateY(-3px); }
.strategy-ticket-head { padding: 16px 16px 12px 18px; border-bottom: 1px dashed color-mix(in srgb, var(--ticket-tone) 22%, var(--line)); }
.strategy-ticket-kicker { color: var(--ticket-tone); font-size: 10px; font-weight: 850; letter-spacing: .1em; text-transform: uppercase; }
.strategy-ticket h4 { margin: 5px 0 2px; font-size: 18px; }
.strategy-ticket-head small { color: var(--muted); }
.strategy-orders { display: grid; gap: 8px; padding: 13px 16px 2px 18px; }
.strategy-order { display: grid; grid-template-columns: 36px 1fr; gap: 8px; align-items: start; }
.strategy-order b { padding-top: 2px; color: var(--ticket-tone); font: 850 9px/1.4 ui-monospace, SFMono-Regular, Consolas, monospace; }
.strategy-order span { color: var(--muted-strong); font-size: 11px; }
.strategy-numbers { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; padding: 13px 16px 13px 18px; }
.strategy-number { padding: 9px; border-radius: 10px; background: var(--surface-soft); }
.strategy-number span { display: block; min-height: 26px; color: var(--muted); font-size: 9px; }
.strategy-number strong { display: block; margin-top: 2px; font-size: 16px; }
.strategy-phases { display: grid; gap: 7px; padding: 0 16px 16px 18px; }
.strategy-phase { display: grid; grid-template-columns: 68px 1fr 46px; gap: 7px; align-items: center; font-size: 9px; }
.strategy-phase span { color: var(--muted); }
.strategy-phase b { color: var(--muted-strong); text-align: right; }
.strategy-phase-track { height: 5px; overflow: hidden; border-radius: 999px; background: var(--line); }
.strategy-phase-track i { display: block; width: min(100%, var(--phase)); height: 100%; border-radius: inherit; background: var(--ticket-tone); }
.strategy-lab-baseline {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  margin: 0 22px 18px;
  padding: 13px 15px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface-soft);
}
.strategy-lab-baseline p { margin: 0; color: var(--muted-strong); font-size: 11px; }
.strategy-lab-baseline strong { color: var(--text); }
.strategy-baseline-numbers { display: flex; gap: 14px; color: var(--muted); font-size: 10px; white-space: nowrap; }
.strategy-baseline-numbers b { color: var(--text); font-size: 13px; }
.strategy-lab-note { margin: 0 22px 20px; color: var(--muted); font-size: 11px; }
.validation-method {
  margin: 12px 0 0;
  color: var(--muted);
  font-size: 13px;
}
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
  .validation-lead { grid-template-columns: 1fr; }
  .validation-verdict { padding: 17px; }
  .trend-case { margin-top: 17px; }
  .trend-case-head { display: grid; gap: 8px; padding: 13px 13px 9px; }
  .trend-case-legend { justify-self: start; flex-wrap: wrap; border-radius: 12px; }
  .trend-case-wave-head { display: grid; gap: 3px; }
  .trend-case-wave-head span { text-align: left; }
  .trend-case-canvas { height: 285px; margin-inline: 6px; }
  .case-axis-label, .case-stop-label { display: none; }
  .case-pin { min-width: 82px; padding: 6px 7px; }
  .case-pin b { font-size: 10px; }
  .case-pin small { font-size: 8.5px; }
  .case-pin.start { left: 1%; }
  .case-pin.peak { left: 44%; }
  .case-pin.end { right: 1%; top: 9px; }
  .trend-case-notes { grid-template-columns: 1fr; }
  .trend-case-note { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 9px 12px; }
  .trend-case-note + .trend-case-note { border-top: 1px solid var(--line); border-left: 0; }
  .trend-case-note strong { max-width: 68%; text-align: right; }
  .repaint-head { display: grid; padding: 18px 16px 13px; }
  .repaint-badge { justify-self: start; }
  .repaint-lineage { grid-template-columns: 1fr; padding: 0 16px 16px; }
  .lineage-fork { display: none; }
  .lineage-branches { grid-template-columns: 1fr 1fr; }
  .repaint-columns, .repaint-strategy { grid-template-columns: 1fr; }
  .repaint-cohort { padding: 17px 16px; }
  .repaint-cohort + .repaint-cohort { border-top: 1px solid var(--line); border-left: 0; }
  .repaint-warning { margin: 0 16px 16px; }
  .repaint-strategy { padding: 0 16px 16px; }
  .repaint-failures { margin: 0 16px 16px; }
  .repaint-failure-list { grid-template-columns: 1fr 1fr; }
  .strategy-lab-head { display: grid; padding: 18px 16px; }
  .strategy-lab-stamp { justify-self: start; text-align: left; }
  .strategy-tickets { grid-template-columns: 1fr; padding: 16px; }
  .strategy-ticket.recommended { transform: none; }
  .strategy-lab-baseline { grid-template-columns: 1fr; margin: 0 16px 16px; }
  .strategy-baseline-numbers { flex-wrap: wrap; }
  .strategy-lab-note { margin: 0 16px 18px; }
  th, td { padding: 12px 14px; }
  .chart-cell { min-width: 320px; }
  .pool-group-head { padding-inline: 14px; }
  .pool-table-shell { overflow: visible; }
  .pool-table, .pool-table tbody { display: block; }
  .pool-table thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .pool-table tbody {
    display: grid;
    gap: 10px;
    padding: 12px;
  }
  .pool-table tr {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px 10px;
    padding: 14px;
    border: 1px solid var(--line);
    border-radius: 15px;
    background: var(--surface);
    box-shadow: 0 8px 22px rgba(31,42,68,.045);
  }
  .pool-table td {
    display: flex;
    min-width: 0;
    padding: 0;
    border: 0;
    flex-direction: column;
    align-items: flex-start;
  }
  .pool-table td::before {
    content: attr(data-label);
    margin-bottom: 4px;
    color: var(--muted);
    font-size: 10px;
    font-weight: 720;
    letter-spacing: .04em;
  }
  .pool-table td:first-child,
  .pool-table td:last-child { grid-column: 1 / -1; }
  .pool-table td.empty {
    display: block;
    grid-column: 1 / -1;
    padding: 20px 4px;
  }
  .pool-table td.empty::before { display: none; }
  .pool-table .stock-link { min-height: 30px; }
  .pool-table .signal { min-width: 0; }
  .pool-table .live-pool-status { min-width: 0; }
  .pool-table .status-operation { width: 100%; }
  .pool-table .operation-ticket { min-height: 38px; white-space: normal; }
  .pool-table .status-detail-line { max-width: none; }
  .live-exit-list { padding: 10px 12px; }
  .live-exit-item { align-items: flex-start; }
}
@media (prefers-reduced-motion: reduce) {
  .reveal.is-visible .case-candle, .reveal.is-visible .case-arrow-start, .reveal.is-visible .case-arrow-end { animation: none; }
}
@media (max-width: 430px) {
  h1 { font-size: 34px; }
  .kpi-grid { grid-template-columns: 1fr 1fr; }
  .kpi-value { font-size: 24px; }
  .metrics { grid-template-columns: 1fr 1fr; }
  .lineage-branches, .repaint-stats, .repaint-failure-list { grid-template-columns: 1fr; }
  .repaint-stat span { min-height: 0; }
  .strategy-numbers { grid-template-columns: 1fr 1fr; }
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
  .operation-ticket.wait { color: #d0d5dd; background: #202b3d; border-color: #526176; }
  .operation-ticket.buy { color: #ffb4ad; background: #3a2024; border-color: #7f3b41; }
  .operation-ticket.hold { color: #bfdbfe; background: #172d4f; border-color: #335f95; }
  .operation-ticket.caution { color: #fde68a; background: #352b13; border-color: #735f22; }
  .operation-ticket.sell { color: #9ce7cf; background: #12392d; border-color: #2a745e; }
  .operation-ticket.confirm { color: #fdba8c; background: #3d2519; border-color: #815038; }
  .events strong, .events ul { color: #fde68a; }
}

/* Risk radar workstation — one signature motion, everything else stays quiet. */
:root {
  --petrol: #0b3440;
  --petrol-deep: #061f28;
  --gold: #d6ae63;
  --gold-soft: #f4e6c7;
}
button { font: inherit; }
.top-actions { display: flex; align-items: center; gap: 8px; }
.theme-toggle {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 50%;
  background: var(--surface);
  color: var(--muted-strong);
  cursor: pointer;
  touch-action: manipulation;
  transition: transform 180ms ease, border-color 180ms ease, color 180ms ease;
}
.theme-toggle:hover { transform: translateY(-1px); border-color: var(--gold); color: var(--accent); }
.theme-toggle svg { width: 19px; height: 19px; }
.hero { align-items: stretch; grid-template-columns: minmax(0, 1.25fr) minmax(330px, .75fr); padding-top: 58px; }
.hero-copy-block { display: flex; flex-direction: column; justify-content: center; padding: 18px 0; }
h1 {
  font-family: "Bahnschrift SemiCondensed", "Arial Narrow", "Microsoft YaHei", sans-serif;
  font-stretch: condensed;
  font-weight: 760;
  letter-spacing: -.045em;
}
.opportunity-word { color: var(--primary); }
.risk-word {
  position: relative;
  display: inline-block;
  color: var(--positive);
}
.risk-word::after {
  content: "";
  position: absolute;
  right: 0;
  bottom: .04em;
  left: 0;
  height: .09em;
  border-radius: 99px;
  background: currentColor;
  opacity: .24;
}
.risk-stage {
  --coverage-angle: 0deg;
  position: relative;
  isolation: isolate;
  overflow: hidden;
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  align-items: center;
  gap: 22px;
  min-height: 264px;
  padding: 28px;
  border: 1px solid rgba(214, 174, 99, .3);
  border-radius: 30px;
  background:
    linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px),
    radial-gradient(circle at 24% 42%, rgba(214, 174, 99, .14), transparent 32%),
    linear-gradient(145deg, var(--petrol), var(--petrol-deep));
  background-size: 22px 22px, 22px 22px, auto, auto;
  color: #f7fbfc;
  box-shadow: 0 30px 70px rgba(6, 31, 40, .2);
}
.risk-stage::after {
  content: "";
  position: absolute;
  z-index: -1;
  right: -55px;
  bottom: -85px;
  width: 220px;
  height: 220px;
  border: 1px solid rgba(214, 174, 99, .15);
  border-radius: 50%;
}
.risk-orbit {
  position: relative;
  display: grid;
  place-items: center;
  width: 150px;
  aspect-ratio: 1;
  border-radius: 50%;
}
.risk-orbit::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: conic-gradient(from -42deg, var(--gold) 0 var(--coverage-angle), rgba(255,255,255,.12) var(--coverage-angle) 360deg);
  -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 8px), #000 0);
  mask: radial-gradient(farthest-side, transparent calc(100% - 8px), #000 0);
}
.risk-orbit::after {
  content: "";
  position: absolute;
  inset: 12px;
  border: 1px solid rgba(255,255,255,.12);
  border-top-color: rgba(214, 174, 99, .9);
  border-radius: inherit;
  animation: radar-sweep 8s linear infinite;
}
@keyframes radar-sweep { to { transform: rotate(360deg); } }
.risk-lens {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 108px;
  aspect-ratio: 1;
  border: 1px solid rgba(255,255,255,.13);
  border-radius: 50%;
  background: rgba(5, 26, 34, .72);
  box-shadow: inset 0 0 30px rgba(214,174,99,.08);
  text-align: center;
}
.risk-lens span { color: #b8ccd1; font-size: 11px; letter-spacing: .12em; }
.risk-lens strong { display: block; margin-top: 2px; color: var(--gold-soft); font: 730 18px/1.2 ui-monospace, Consolas, monospace; }
.risk-meta { min-width: 0; }
.risk-stage .status-title { color: #fff; font-size: 16px; }
.risk-stage .status-detail { color: #b8ccd1; }
.risk-stage .timestamp { border-color: rgba(255,255,255,.12); color: #8faab1; }
.risk-stage .timestamp strong { color: #eef7f8; }
.risk-stage .status-dot { background: #58d2a3; box-shadow: 0 0 0 5px rgba(88,210,163,.12); }
.risk-stage .status-dot.stale { background: #f2c572; box-shadow: 0 0 0 5px rgba(242,197,114,.12); }
.risk-stage .status-dot.error { background: #ff8a80; box-shadow: 0 0 0 5px rgba(255,138,128,.12); }
.live-rail {
  display: grid;
  grid-template-columns: 160px minmax(0, 1fr);
  align-items: center;
  gap: 16px;
  margin: 6px 0 32px;
  padding: 13px 14px 13px 18px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: color-mix(in srgb, var(--surface) 88%, transparent);
  box-shadow: 0 10px 28px rgba(31,42,68,.04);
}
.live-rail-label { display: flex; align-items: center; gap: 9px; color: var(--muted-strong); font-size: 13px; font-weight: 720; }
.live-rail-label::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--positive); box-shadow: 0 0 0 4px var(--positive-soft); }
.ticker-track {
  display: flex;
  gap: 8px;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: thin;
  scroll-snap-type: x proximity;
  overscroll-behavior-inline: contain;
  -webkit-overflow-scrolling: touch;
}
.ticker-item {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: auto auto;
  gap: 0 12px;
  min-width: 152px;
  min-height: 48px;
  padding: 7px 11px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--surface-soft);
  color: var(--text);
  scroll-snap-align: start;
}
.ticker-item:hover { border-color: var(--line-strong); text-decoration: none; }
.ticker-name { max-width: 7em; overflow: hidden; font-size: 12px; font-weight: 720; text-overflow: ellipsis; white-space: nowrap; }
.ticker-price { grid-row: span 2; align-self: center; font: 720 15px/1.2 ui-monospace, Consolas, monospace; }
.ticker-change { font: 650 11px/1.2 ui-monospace, Consolas, monospace; }
.ticker-empty { color: var(--muted); font-size: 12px; }
.kpi, .panel, .rule {
  transition: transform 200ms ease, border-color 200ms ease, box-shadow 200ms ease;
}
.kpi:hover, .rule:hover { transform: translateY(-2px); border-color: var(--line-strong); box-shadow: 0 14px 34px rgba(31,42,68,.08); }
.pool-switcher {
  display: inline-flex;
  gap: 5px;
  margin: 2px 0 16px;
  padding: 5px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--surface-soft);
}
.pool-tab {
  min-height: 44px;
  padding: 0 18px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--muted-strong);
  cursor: pointer;
  font-weight: 720;
  touch-action: manipulation;
}
.pool-tab[aria-selected="true"] {
  background: var(--surface);
  color: var(--text);
  box-shadow: 0 5px 18px rgba(31,42,68,.08);
}
[hidden] { display: none !important; }
html.js .reveal { opacity: 0; transform: translateY(14px); }
html.js .reveal.is-visible { opacity: 1; transform: translateY(0); transition: opacity 520ms ease, transform 520ms cubic-bezier(.2,.8,.2,1); }
.quote-updated { animation: quote-flash 700ms ease; }
@keyframes quote-flash { 50% { background: color-mix(in srgb, var(--gold) 20%, transparent); } }
.mobile-dock { display: none; }
html[data-theme="light"] {
  color-scheme: light;
  --bg: #f5f7fb; --surface: #ffffff; --surface-soft: #f8fafc; --surface-blue: #eff6ff;
  --text: #172033; --muted: #667085; --muted-strong: #475467; --line: #dfe5ef; --line-strong: #cbd5e1;
  --primary: #1e40af; --primary-2: #2563eb; --accent: #b45309; --positive: #b42318; --positive-soft: #fff1f0;
  --negative: #087443; --negative-soft: #ecfdf3; --warning: #a15c07; --warning-soft: #fffaeb;
}
html[data-theme="light"] body {
  background: radial-gradient(circle at 8% -10%, rgba(37,99,235,.12), transparent 28rem), linear-gradient(180deg, #f8fafc 0, var(--bg) 34rem);
}
html[data-theme="light"] .topbar { background: rgba(248,250,252,.88); }
html[data-theme="dark"] {
  color-scheme: dark;
  --bg: #0b1220; --surface: #111a2b; --surface-soft: #151f32; --surface-blue: #172554;
  --text: #edf2f7; --muted: #9aa8bc; --muted-strong: #c0cad8; --line: #26344a; --line-strong: #3b4b64;
  --primary: #93c5fd; --primary-2: #60a5fa; --accent: #fbbf24; --positive: #ff8a80; --positive-soft: #3a2024;
  --negative: #6ee7b7; --negative-soft: #12392d; --warning: #fcd34d; --warning-soft: #352b13;
}
html[data-theme="dark"] body {
  background: radial-gradient(circle at 8% -10%, rgba(37,99,235,.22), transparent 28rem), linear-gradient(180deg, #101827 0, var(--bg) 34rem);
}
html[data-theme="dark"] .topbar { background: rgba(11,18,32,.86); }
html[data-theme="dark"] tbody tr:hover { background: #152136; }
@media (max-width: 760px) {
  .shell { padding-bottom: calc(104px + env(safe-area-inset-bottom)); }
  .brand span:last-child { font-size: 14px; }
  .hero { grid-template-columns: 1fr; padding-top: 30px; }
  .hero-copy-block { padding: 0; }
  .hero-copy { font-size: 15px; }
  .risk-stage { grid-template-columns: 112px minmax(0, 1fr); min-height: 204px; padding: 21px; border-radius: 24px; }
  .risk-orbit { width: 112px; }
  .risk-lens { width: 80px; }
  .risk-lens strong { font-size: 14px; }
  .risk-lens span { font-size: 9px; }
  .live-rail { grid-template-columns: 1fr; gap: 8px; margin-top: 0; padding: 12px; }
  .pool-switcher { display: flex; width: 100%; }
  .pool-tab { flex: 1 1 0; padding-inline: 10px; }
  .mobile-dock {
    position: fixed;
    z-index: 30;
    right: 12px;
    bottom: max(10px, env(safe-area-inset-bottom));
    left: 12px;
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    min-height: 66px;
    padding: 7px;
    border: 1px solid color-mix(in srgb, var(--line) 80%, transparent);
    border-radius: 19px;
    background: color-mix(in srgb, var(--surface) 90%, transparent);
    box-shadow: 0 20px 48px rgba(6,31,40,.18);
    backdrop-filter: blur(18px);
  }
  .mobile-dock a {
    display: grid;
    place-items: center;
    align-content: center;
    gap: 3px;
    min-width: 44px;
    min-height: 50px;
    border-radius: 13px;
    color: var(--muted);
    font-size: 10px;
    font-weight: 700;
    touch-action: manipulation;
  }
  .mobile-dock a:hover, .mobile-dock a:focus-visible { background: var(--surface-soft); color: var(--primary); text-decoration: none; }
  .mobile-dock svg { width: 19px; height: 19px; }
}
@media (max-width: 430px) {
  h1 { font-size: clamp(35px, 11vw, 44px); line-height: 1.05; }
  .risk-stage { grid-template-columns: 94px minmax(0, 1fr); gap: 16px; padding: 18px 16px; }
  .risk-orbit { width: 94px; }
  .risk-lens { width: 66px; }
  .risk-lens span { letter-spacing: .04em; }
  .status-detail { font-size: 12px; }
  .timestamp { margin-top: 12px; padding-top: 10px; }
  .timestamp strong { font-size: 12px; }
}

/* Photorealistic 3D cover: image-led, with lightweight GPU motion only. */
.cover-hero {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  width: calc(100% + 48px);
  min-height: clamp(620px, calc(100svh - 64px), 780px);
  margin-left: -24px;
  color: #f7fbff;
  background: #061421;
}
.cover-stage {
  position: absolute;
  z-index: 0;
  inset: -4%;
  overflow: hidden;
  background-color: #061421;
  background-image: var(--cover-desktop);
  background-position: center;
  background-size: cover;
  background-repeat: no-repeat;
  pointer-events: none;
}
.cover-cinema {
  position: absolute;
  inset: 0;
  background-image: var(--cover-desktop);
  background-position: center;
  background-size: cover;
  background-repeat: no-repeat;
  transform-origin: 72% 28%;
  animation: cover-cinema-flight 4.466s cubic-bezier(.18,.66,.18,1) infinite;
  will-change: transform;
}
.cover-video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
  background: #061421;
  opacity: 0;
  transition: opacity 420ms ease;
}
.cover-video.is-ready { opacity: 1; }
@keyframes cover-cinema-flight {
  0% { transform: scale(1.02) translate3d(0, 0, 0); }
  18% { transform: scale(1.1) translate3d(-1%, 1%, 0); }
  46% { transform: scale(1.26) translate3d(-3%, 3.5%, 0); }
  72% { transform: scale(1.42) translate3d(-5%, 6%, 0); }
  92%, 100% { transform: scale(1.58) translate3d(-7%, 8%, 0); }
}
.cover-cinema-mask {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(180deg, rgba(2,10,20,.38) 0, rgba(2,10,20,.06) 30%, transparent 62%, rgba(2,10,20,.58) 100%),
    linear-gradient(90deg, rgba(2,12,24,.9) 0, rgba(2,12,24,.7) 30%, rgba(2,12,24,.25) 50%, rgba(2,12,24,.03) 72%);
}
.cover-hero::before {
  content: "";
  position: absolute;
  z-index: 1;
  inset: 0;
  background:
    radial-gradient(circle at 76% 26%, rgba(174,225,255,.11), transparent 25%),
    linear-gradient(180deg, rgba(2,10,20,.18) 0, transparent 52%, rgba(2,10,20,.28) 100%);
  pointer-events: none;
}
.cover-glow {
  position: absolute;
  z-index: 1;
  top: -18%;
  right: -8%;
  width: 58%;
  height: 90%;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(186,231,255,.18), transparent 62%);
  mix-blend-mode: screen;
  animation: cover-glow-breathe 7s cubic-bezier(.22,.72,.2,1) infinite;
  pointer-events: none;
}
@keyframes cover-glow-breathe {
  0%, 18% { opacity: .2; transform: translate3d(5%, 7%, 0) scale(.86); }
  50% { opacity: .48; transform: translate3d(1%, 2%, 0) scale(.98); }
  72% { opacity: .82; transform: translate3d(-2%, -1%, 0) scale(1.1); }
  86%, 100% { opacity: 1; transform: translate3d(-4%, -3%, 0) scale(1.2); }
}
.kline-camera {
  position: absolute;
  z-index: 2;
  inset: 0;
  overflow: hidden;
  perspective: 1000px;
  pointer-events: none;
}
.kline-world {
  position: absolute;
  inset: 0;
  transform-style: preserve-3d;
  animation: kline-camera-climb 7s cubic-bezier(.22,.72,.2,1) infinite;
  will-change: transform;
}
@keyframes kline-camera-climb {
  0% { transform: translate3d(0, 6%, -120px) scale(.86); }
  12% { transform: translate3d(0, 5%, -90px) scale(.89); }
  62% { transform: translate3d(-1.5%, -1.5%, 0) scale(1.02); }
  84% { transform: translate3d(-2.5%, -3.5%, 40px) scale(1.08); }
  100% { transform: translate3d(-2.5%, -3.5%, 40px) scale(1.08); }
}
.kline-reveal {
  position: absolute;
  inset: 0;
  opacity: 0;
  clip-path: inset(100% 0 0 0);
  animation: kline-breakthrough 7s cubic-bezier(.2,.74,.18,1) infinite;
}
@keyframes kline-breakthrough {
  0%, 5% { opacity: 0; clip-path: inset(100% 0 0 0); }
  10% { opacity: 1; }
  62% { opacity: 1; clip-path: inset(0 0 0 0); }
  86% { opacity: 1; clip-path: inset(0 0 0 0); }
  100% { opacity: 0; clip-path: inset(0 0 0 0); }
}
.cover-candle {
  --red-front: #f22f3e;
  --red-side: #9b101b;
  --red-top: #ff8890;
  --green-front: #18a978;
  --green-side: #075c42;
  --green-top: #6ce0b5;
  position: absolute;
  left: var(--x);
  top: var(--y);
  width: clamp(10px, 1.05vw, 17px);
  height: calc(var(--h) + 28px);
  transform: translate(-50%, -50%) rotate(-3deg) translateZ(calc(var(--i) * 2px));
  transform-style: preserve-3d;
  filter: drop-shadow(0 0 8px rgba(242,47,62,.34));
}
.cover-candle.down { filter: drop-shadow(0 0 7px rgba(24,169,120,.28)); }
.cover-wick {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 2px;
  border-radius: 2px;
  background: var(--red-front);
  transform: translateX(-50%) translateZ(-2px);
}
.cover-body {
  position: absolute;
  top: 13px;
  right: 0;
  left: 0;
  height: var(--h);
  border-radius: 2px;
  background: linear-gradient(90deg, var(--red-side), var(--red-front) 28%, #ff5360 76%, var(--red-side));
  box-shadow: inset 1px 0 rgba(255,255,255,.48), inset -2px 0 rgba(70,0,8,.38), 0 8px 18px rgba(242,47,62,.3);
  transform-style: preserve-3d;
}
.cover-body::before {
  content: "";
  position: absolute;
  top: -5px;
  right: 3px;
  left: 0;
  height: 6px;
  border-radius: 2px 2px 0 0;
  background: var(--red-top);
  transform: skewX(-38deg);
  transform-origin: bottom;
}
.cover-body::after {
  content: "";
  position: absolute;
  top: -2px;
  right: -5px;
  width: 6px;
  height: calc(100% + 2px);
  border-radius: 0 2px 2px 0;
  background: var(--red-side);
  transform: skewY(-28deg);
  transform-origin: left;
}
.cover-candle.down .cover-wick { background: var(--green-front); }
.cover-candle.down .cover-body {
  background: linear-gradient(90deg, var(--green-side), var(--green-front) 28%, #38c895 76%, var(--green-side));
  box-shadow: inset 1px 0 rgba(255,255,255,.4), inset -2px 0 rgba(0,54,37,.4), 0 8px 16px rgba(24,169,120,.25);
}
.cover-candle.down .cover-body::before { background: var(--green-top); }
.cover-candle.down .cover-body::after { background: var(--green-side); }
.cover-cloud-veil {
  position: absolute;
  z-index: 3;
  top: 36%;
  right: -8%;
  left: 14%;
  height: 34%;
  background:
    radial-gradient(ellipse at 66% 45%, rgba(239,249,255,.74), rgba(177,204,220,.36) 32%, transparent 66%),
    radial-gradient(ellipse at 40% 60%, rgba(38,60,78,.72), transparent 68%);
  filter: blur(13px);
  mix-blend-mode: screen;
  opacity: .62;
  animation: cloud-veil-part 7s ease-in-out infinite;
  pointer-events: none;
}
@keyframes cloud-veil-part {
  0%, 26% { opacity: .76; transform: translate3d(3%, 3%, 0) scale(1.08); }
  54% { opacity: .62; transform: translate3d(0, 0, 0) scale(1.02); }
  72% { opacity: .34; transform: translate3d(-3%, -4%, 0) scale(.94); }
  86%, 100% { opacity: .16; transform: translate3d(-5%, -7%, 0) scale(.88); }
}
.cover-inner {
  position: relative;
  z-index: 4;
  width: min(1440px, 100%);
  min-height: inherit;
  margin: 0 auto;
  padding: clamp(68px, 10vh, 106px) clamp(28px, 6vw, 86px);
}
.cover-copy { width: min(610px, 54vw); }
.cover-eyebrow {
  display: flex;
  align-items: center;
  gap: 11px;
  margin: 0 0 20px;
  color: rgba(224,243,255,.82);
  font-size: 12px;
  font-weight: 680;
  letter-spacing: .16em;
  text-transform: uppercase;
  text-shadow: 0 2px 16px rgba(0,0,0,.5);
}
.cover-eyebrow::before { content: ""; width: 34px; height: 1px; background: #ff666b; }
.cover-hero h1 {
  max-width: 640px;
  color: #fff;
  font-family: "STSong", "Songti SC", "FZLanTingHeiS-UL-GB", "Microsoft YaHei", sans-serif;
  font-size: clamp(62px, 6.8vw, 102px);
  font-weight: 400;
  line-height: .98;
  letter-spacing: -.055em;
  text-shadow: 0 8px 38px rgba(0,5,14,.62);
}
.cover-hero .opportunity-word, .cover-hero .risk-word { color: inherit; }
.cover-hero .risk-word::after { display: none; }
.cover-subline {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 28px 0 0;
  color: rgba(235,247,253,.78);
  font-size: 14px;
  letter-spacing: .06em;
}
.cover-subline::before { content: ""; width: 28px; height: 1px; background: rgba(255,255,255,.48); }
.cover-live {
  position: absolute;
  top: clamp(52px, 7vh, 76px);
  right: clamp(28px, 5vw, 72px);
  width: min(330px, 34vw);
  padding: 16px 17px;
  border: 1px solid rgba(255,255,255,.17);
  border-radius: 16px;
  background: rgba(4,22,38,.42);
  box-shadow: 0 18px 52px rgba(0,8,18,.22);
  backdrop-filter: blur(14px);
}
.cover-live-top { display: flex; align-items: center; gap: 10px; }
.cover-live-top strong { flex: 1; min-width: 0; font-size: 14px; }
.cover-count {
  min-width: 53px;
  padding: 3px 8px;
  border: 1px solid rgba(255,255,255,.16);
  border-radius: 999px;
  color: #e1f2fa;
  font: 650 11px/1.5 ui-monospace, Consolas, monospace;
  text-align: center;
}
.cover-live .status-dot { margin-top: 0; background: #67dfaf; box-shadow: 0 0 0 4px rgba(103,223,175,.14); }
.cover-live .status-dot.stale { background: #f2c572; box-shadow: 0 0 0 4px rgba(242,197,114,.14); }
.cover-live .status-dot.error { background: #ff8a80; box-shadow: 0 0 0 4px rgba(255,138,128,.14); }
.cover-live .status-detail { margin-top: 7px; color: rgba(220,239,248,.7); font-size: 12px; }
.cover-time { margin-top: 10px; color: rgba(189,218,232,.64); font-size: 11px; }
.cover-time strong { margin-left: 8px; color: #f3f9fc; font: 650 12px/1.4 ui-monospace, Consolas, monospace; }
.cover-note {
  position: absolute;
  right: clamp(30px, 7vw, 100px);
  bottom: clamp(52px, 8vh, 82px);
  width: min(460px, 42vw);
  margin: 0;
  color: rgba(244,250,253,.94);
  font-size: clamp(15px, 1.35vw, 19px);
  line-height: 1.75;
  text-align: right;
  text-shadow: 0 3px 18px rgba(0,0,0,.82);
}
.cover-note strong { display: block; color: #fff; font-size: 1.08em; }
.cover-hero + .live-rail { margin-top: 20px; }
@media (max-width: 900px) {
  .cover-copy { width: 62vw; }
  .cover-live { top: 310px; width: min(300px, 38vw); }
  .cover-note { width: 48vw; }
}
@media (max-width: 760px) {
  .cover-hero { width: calc(100% + 32px); min-height: 680px; margin-left: -16px; }
  .cover-stage { inset: -4%; background-image: var(--cover-mobile); }
  .cover-cinema {
    background-image: var(--cover-mobile);
    transform-origin: 76% 30%;
    animation-name: cover-cinema-flight-mobile;
    animation-duration: 5.2s;
  }
  .cover-video { object-position: 66% center; }
  @keyframes cover-cinema-flight-mobile {
    0% { transform: scale(1.02) translate3d(0, 0, 0); }
    20% { transform: scale(1.07) translate3d(-.5%, 1%, 0); }
    50% { transform: scale(1.16) translate3d(-1.5%, 3%, 0); }
    76% { transform: scale(1.27) translate3d(-3%, 5%, 0); }
    94%, 100% { transform: scale(1.36) translate3d(-4.5%, 7%, 0); }
  }
  .cover-cinema-mask {
    background:
      linear-gradient(180deg, rgba(2,10,20,.58) 0, rgba(2,10,20,.16) 35%, rgba(2,10,20,.08) 58%, rgba(2,10,20,.68) 100%),
      linear-gradient(90deg, rgba(2,12,24,.84) 0, rgba(2,12,24,.58) 52%, rgba(2,12,24,.08) 100%);
  }
  .cover-hero::before {
    background:
      linear-gradient(180deg, rgba(2,12,24,.38) 0, rgba(2,12,24,.1) 42%, rgba(2,10,20,.65) 100%),
      linear-gradient(90deg, rgba(2,12,24,.44), rgba(2,12,24,.05) 72%);
  }
  .cover-inner { padding: 46px 20px; }
  .cover-copy { position: relative; isolation: isolate; width: 100%; }
  .cover-copy::before {
    content: "";
    position: absolute;
    z-index: -1;
    top: -22px;
    right: 12%;
    bottom: -18px;
    left: -28px;
    background: radial-gradient(ellipse at 30% 46%, rgba(3,17,30,.86), rgba(3,17,30,.5) 54%, transparent 76%);
    filter: blur(12px);
    pointer-events: none;
  }
  .cover-hero h1 { width: 100%; max-width: 390px; font-size: clamp(50px, 14vw, 64px); line-height: 1.02; }
  .cover-subline { margin-top: 17px; font-size: 12px; }
  .cover-live {
    top: 265px;
    right: 16px;
    left: 16px;
    width: auto;
    padding: 14px 15px;
  }
  .cover-note { right: 20px; bottom: 42px; width: min(315px, 84vw); font-size: 14px; }
  .cover-hero + .live-rail { margin-top: 14px; }
}
@media (max-width: 430px) {
  .cover-hero { min-height: 660px; }
  .cover-eyebrow { font-size: 10px; }
  .cover-hero h1 { font-size: clamp(47px, 14vw, 58px); }
  .cover-live { top: 250px; }
  .cover-note { bottom: 36px; }
}
@media (prefers-reduced-motion: reduce) {
  .risk-orbit::after { animation: none; }
  html.js .reveal, html.js .reveal.is-visible { opacity: 1; transform: none; }
  .quote-updated { animation: none; }
  .cover-cinema, .cover-visual, .cover-glow, .kline-world, .kline-reveal, .cover-cloud-veil { animation: none; }
  .kline-reveal { opacity: 1; clip-path: inset(0); }
}
"""


LIVE_SCRIPT = r"""
(() => {
  const root = document.documentElement;
  const themeButton = document.querySelector("#theme-toggle");
  const mediaTheme = window.matchMedia("(prefers-color-scheme: dark)");
  const savedTheme = window.localStorage.getItem("lushi-theme");
  const applyTheme = (theme) => {
    root.dataset.theme = theme;
    if (themeButton) {
      const next = theme === "dark" ? "浅色" : "深色";
      themeButton.setAttribute("aria-label", `切换到${next}模式`);
      themeButton.setAttribute("title", `切换到${next}模式`);
    }
  };
  applyTheme(savedTheme || (mediaTheme.matches ? "dark" : "light"));
  themeButton?.addEventListener("click", () => {
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    window.localStorage.setItem("lushi-theme", next);
    applyTheme(next);
  });

  const tabs = [...document.querySelectorAll("[data-pool-tab]")];
  const panels = [...document.querySelectorAll("[data-pool-panel]")];
  const selectPool = (name) => {
    tabs.forEach((tab) => {
      const selected = tab.dataset.poolTab === name;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    panels.forEach((panel) => { panel.hidden = panel.dataset.poolPanel !== name; });
  };
  tabs.forEach((tab) => tab.addEventListener("click", () => selectPool(tab.dataset.poolTab)));

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const reveals = document.querySelectorAll(".reveal");
  if (reduceMotion || !("IntersectionObserver" in window)) {
    reveals.forEach((item) => item.classList.add("is-visible"));
  } else {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: .08 });
    reveals.forEach((item) => observer.observe(item));
  }

  const coverVideo = document.querySelector("[data-cover-video]");
  if (coverVideo) {
    const saveData = Boolean(navigator.connection?.saveData);
    const narrowScreen = window.matchMedia("(max-width: 760px)").matches;
    const syncCoverPlayback = () => {
      if (reduceMotion || document.hidden) {
        coverVideo.pause();
        if (reduceMotion && coverVideo.readyState >= 1) coverVideo.currentTime = .3;
      } else {
        coverVideo.play().catch(() => {});
      }
    };
    const loadCoverVideo = () => {
      if (coverVideo.src || reduceMotion || saveData) return;
      const nestedPage = /\/results\//.test(window.location.pathname);
      coverVideo.src = `${nestedPage ? "../" : ""}assets/hero-cloudbreak-aigc-v2.webm`;
      coverVideo.load();
    };
    coverVideo.addEventListener("playing", () => coverVideo.classList.add("is-ready"));
    coverVideo.addEventListener("loadedmetadata", syncCoverPlayback, { once: true });
    document.addEventListener("visibilitychange", syncCoverPlayback);
    if (!reduceMotion && !saveData) {
      if (narrowScreen) {
        const deferLoad = () => loadCoverVideo();
        if ("requestIdleCallback" in window) {
          window.requestIdleCallback(deferLoad, { timeout: 1600 });
        } else {
          window.setTimeout(deferLoad, 800);
        }
      } else {
        loadCoverVideo();
      }
    }
  }

  const status = document.querySelector("#market-status");
  const detail = document.querySelector("#market-detail");
  const quoteTime = document.querySelector("#quote-time");
  const liveTradeDate = document.querySelector("[data-live-trade-date]");
  const closeTradeDate = document.querySelector("[data-close-trade-date]");
  const dot = document.querySelector("#status-dot");
  const lensValue = document.querySelector("#lens-value");
  const riskStage = document.querySelector(".risk-stage, .cover-hero");
  const ticker = document.querySelector("#ticker-track");
      const formatPct = (value) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
      const formatQuoteTime = (value) => {
        const stamp = String(value || "").trim();
        if (!stamp) return "";
        const dated = stamp.match(/^\d{4}-\d{2}-\d{2}[T ](\d{2}:\d{2})/);
        if (dated) return `${stamp.slice(5, 10)} ${dated[1]}`;
        const timed = stamp.match(/^(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?$/);
        if (timed) return timed[1];
        return stamp.slice(0, 16);
      };
  const setTone = (element, value) => {
    element.classList.toggle("positive", value >= 0);
    element.classList.toggle("negative", value < 0);
  };
  const operationTone = (label) => {
    const value = String(label || "");
    if (value.includes("等待收盘") || value.includes("触发")) return "confirm";
    if (value.includes("买入") && !value.includes("等待")) return "buy";
    if (value.includes("卖出") || value.includes("停止")) return "sell";
    if (value.includes("谨慎") || value.includes("取消")) return "caution";
    if (value.includes("持有")) return "hold";
    return "wait";
  };
  const setOperation = (element, label) => {
    if (!element) return;
    element.textContent = label || "继续观察";
    element.className = `operation-ticket ${operationTone(label)}`;
  };
  const quoteHref = (quote) => {
    const prefix = Number(quote.market) === 1 ? "sh" : Number(quote.market) === 0 ? "sz" : "bj";
    return `https://quote.eastmoney.com/${prefix}${quote.code}.html`;
  };
  const signalCell = (ok, note, label) => {
    const cell = document.createElement("td");
    cell.dataset.label = label;
    const signal = document.createElement("div");
    signal.className = "signal";
    const mark = document.createElement("span");
    mark.className = `signal-mark ${ok ? "yes" : "no"}`;
    mark.textContent = ok ? "✓" : "—";
    const subline = document.createElement("span");
    subline.className = "subline";
    subline.textContent = note || (ok ? "已满足" : "未命中");
    signal.append(mark, subline);
    cell.append(signal);
    return cell;
  };
  const paintPoolRows = (rows, area, mode) => {
    const body = document.querySelector(`#live-${area}-body`);
    if (!body) return;
    body.replaceChildren();
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.className = "empty";
      cell.colSpan = 7;
      cell.textContent = `当前没有符合条件的${area === "main" ? "主选" : "次选"}预选`;
      row.append(cell);
      body.append(row);
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement("tr");
      row.dataset.liveCode = item.code;

      const stockCell = document.createElement("td");
      stockCell.dataset.label = "股票";
      const link = document.createElement("a");
      link.className = "stock-link";
      link.href = quoteHref(item);
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = item.name || item.code;
      const code = document.createElement("span");
      code.className = "stock-code";
      code.textContent = item.code;
      stockCell.append(link, code);

      const priceCell = document.createElement("td");
      priceCell.dataset.label = "最新行情";
      const price = document.createElement("span");
      price.className = "numeric";
      price.dataset.livePrice = "";
      price.textContent = Number(item.price).toFixed(2);
      const quoteLine = document.createElement("span");
      quoteLine.className = "subline";
      const change = document.createElement("span");
      change.className = "numeric";
      change.dataset.liveChange = "";
      change.textContent = formatPct(Number(item.change_pct));
      setTone(change, Number(item.change_pct));
      const time = document.createElement("span");
      time.dataset.liveTime = "";
      const displayTime = formatQuoteTime(item.server_time);
      time.textContent = displayTime ? `${displayTime} 行情` : "最新行情";
      quoteLine.append(change, document.createTextNode(" · "), time);
      priceCell.append(price, quoteLine);

      const statusCell = document.createElement("td");
      statusCell.dataset.label = "状态 / 操作";
      statusCell.className = "live-pool-status";
      const statusOperation = document.createElement("div");
      statusOperation.className = "status-operation";
      const state = document.createElement("span");
      state.className = "state warn";
      const areaLabel = area === "main" ? "主选" : "次选";
      state.textContent = "待观察中";
      const operation = document.createElement("span");
      setOperation(
        operation,
        mode === "intraday" ? "等待收盘确认" : "等待买入",
      );
      const settlement = document.createElement("span");
      settlement.className = "subline status-detail-line";
      settlement.textContent = mode === "intraday"
        ? `新${areaLabel}信号，收盘后保存并进入买点观察`
        : `已形成${areaLabel}信号；10日内收盘突破前5日高点才建议买入`;
      statusOperation.append(state, operation);
      statusCell.append(statusOperation, settlement);

      row.append(
        stockCell,
        priceCell,
        signalCell(Boolean(item.bottom_ok), item.bottom_date || "未命中", "可能见底"),
        signalCell(Boolean(item.cross_ok), item.cross_date || "未命中", "龙腾跃虎"),
        signalCell(Boolean(item.limit_up_ok), item.limit_up_date || "未命中", "42日涨停"),
        signalCell(Boolean(item.yellow_ok), `${item.yellow_date || "有效窗口内"} · ${Number(item.yellow_count || 0)} 根`, "窗口黄柱"),
        statusCell,
      );
      body.append(row);
    });
  };
  const paintLivePools = (pools, mode, trackingCodes) => {
    if (!pools || !pools.available) return;
    const main = Array.isArray(pools.main) ? pools.main : [];
    const secondary = Array.isArray(pools.secondary) ? pools.secondary : [];
    const trackedMain = Array.isArray(trackingCodes?.main) ? trackingCodes.main : [];
    const trackedSecondary = Array.isArray(trackingCodes?.secondary) ? trackingCodes.secondary : [];
    const mainAreaCount = new Set([...main.map((item) => item.code), ...trackedMain]).size;
    const secondaryAreaCount = new Set([
      ...secondary.map((item) => item.code),
      ...trackedSecondary,
    ]).size;
    document.querySelectorAll("[data-live-main-count]").forEach((node) => {
      node.textContent = String(main.length);
    });
    document.querySelectorAll("[data-live-secondary-count]").forEach((node) => {
      node.textContent = String(secondary.length);
    });
    document.querySelectorAll("[data-tracked-main-count]").forEach((node) => {
      node.textContent = String(trackedMain.length);
    });
    document.querySelectorAll("[data-tracked-secondary-count]").forEach((node) => {
      node.textContent = String(trackedSecondary.length);
    });
    document.querySelectorAll("[data-area-main-count]").forEach((node) => {
      node.textContent = String(mainAreaCount);
    });
    document.querySelectorAll("[data-area-secondary-count]").forEach((node) => {
      node.textContent = String(secondaryAreaCount);
    });
    paintPoolRows(main, "main", mode);
    paintPoolRows(secondary, "secondary", mode);
  };
  const paintLiveTracking = (tracking) => {
    ["main", "secondary"].forEach((area) => {
      const items = Array.isArray(tracking?.[area]) ? tracking[area] : [];
      const byCode = new Map(items.map((item) => [String(item.code), item]));
      document.querySelectorAll(`[data-tracking-area="${area}"]`).forEach((row) => {
        const item = byCode.get(String(row.dataset.trackingCode || ""));
        if (!item) return;
        row.hidden = Boolean(item.trend_ended);
        const price = row.querySelector("[data-live-price]");
        const time = row.querySelector("[data-live-time]");
        const liveReturn = row.querySelector("[data-live-return]");
        const liveStatus = row.querySelector("[data-live-status]");
        const liveOperation = row.querySelector("[data-live-operation]");
        const statusDetail = row.querySelector("[data-live-status-detail]");
        if (price) price.textContent = Number(item.live_price).toFixed(2);
        if (time) {
          const display = formatQuoteTime(item.server_time);
          time.textContent = display ? `${display} 实时行情` : `${item.settled_date || "最近"} 收盘`;
        }
        if (liveReturn) {
          liveReturn.textContent = formatPct(Number(item.live_return_pct));
          setTone(liveReturn, Number(item.live_return_pct));
        }
        if (liveStatus) {
          liveStatus.textContent = item.status || "上升趋势中";
          liveStatus.className = `state ${item.trend_ended && !item.setup_cancelled ? "ended" : item.status === "待观察中" ? "warn" : item.status === "数据待确认" ? "neutral" : "good"}`;
        }
        setOperation(liveOperation, item.operation || "继续观察");
        if (statusDetail) statusDetail.textContent = item.status_detail || "盘中持续跟踪";
        row.classList.remove("quote-updated");
        void row.offsetWidth;
        row.classList.add("quote-updated");
      });

      const exitList = document.querySelector(`#live-${area}-exits`);
      if (!exitList) return;
      exitList.replaceChildren();
      items.filter((item) => item.provisional_exit || item.provisional_cancel).forEach((item) => {
        const card = document.createElement("div");
        card.className = "live-exit-item";
        const stock = document.createElement("div");
        stock.className = "live-exit-stock";
        const title = document.createElement("strong");
        title.textContent = `${item.name || item.code} · ${item.code}`;
        const reason = document.createElement("small");
        reason.textContent = item.status_detail || String(item.exit_reason || "等待收盘确认").replace(/^趋势结束：/, "");
        stock.append(title, reason);
        const result = document.createElement("div");
        result.className = "live-exit-result";
        const state = document.createElement("span");
        state.className = "state warn";
        state.textContent = item.provisional_cancel ? "候选待复核" : "卖点待确认";
        const operation = document.createElement("span");
        setOperation(operation, item.operation || "等待收盘确认");
        const returns = document.createElement("span");
        returns.className = "subline numeric";
        returns.textContent = item.provisional_cancel
          ? "未确认买点，不计收益"
          : `${formatPct(Number(item.live_return_pct))} · 仅盘中预告`;
        result.append(state, operation, returns);
        card.append(stock, result);
        exitList.append(card);
      });
      exitList.hidden = !exitList.children.length;
    });
  };
  const paintTicker = (quotes) => {
    if (!ticker) return;
    ticker.replaceChildren();
    Object.values(quotes).slice(0, 18).forEach((quote) => {
      const item = document.createElement("a");
      item.className = "ticker-item";
      item.href = quoteHref(quote);
      item.target = "_blank";
      item.rel = "noreferrer";
      item.setAttribute("aria-label", `${quote.name} ${Number(quote.price).toFixed(2)} 元，涨跌幅 ${formatPct(Number(quote.change_pct))}`);
      const name = document.createElement("span");
      name.className = "ticker-name";
      name.textContent = quote.name || quote.code;
      const price = document.createElement("strong");
      price.className = "ticker-price";
      price.textContent = Number(quote.price).toFixed(2);
      const change = document.createElement("span");
      change.className = "ticker-change";
      change.textContent = formatPct(Number(quote.change_pct));
      setTone(change, Number(quote.change_pct));
      item.append(name, price, change);
      ticker.append(item);
    });
    if (!ticker.children.length) {
      const empty = document.createElement("span");
      empty.className = "ticker-empty";
      empty.textContent = "当前没有需要刷新的跟踪行情";
      ticker.append(empty);
    }
  };
  async function refreshLive() {
    try {
      const response = await fetch(`live.json?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      status.textContent = data.market_label || "行情已更新";
      detail.textContent = data.note || "主选与次选盘中重算；趋势状态实时判断，统计收盘结算";
      quoteTime.textContent = data.generated_at_display || data.generated_at;
      if (liveTradeDate) {
        liveTradeDate.textContent = data.live_trade_date || data.close_trade_date || "等待行情";
      }
      if (closeTradeDate) {
        closeTradeDate.textContent = data.close_trade_date || closeTradeDate.textContent;
      }
      if (data.live_trade_date || data.close_trade_date) {
        document.title = `卢氏龙虎趋势池 · 盘中 ${data.live_trade_date || "—"} · 结算 ${data.close_trade_date || "—"}`;
      }
      dot.className = `status-dot ${data.is_stale ? "stale" : ""}`;
      const targetCount = Number(data.target_count || 0);
      const quoteCount = Number(data.quote_count || 0);
      const coverage = targetCount ? Math.min(1, quoteCount / targetCount) : 1;
      if (lensValue) lensValue.textContent = targetCount ? `${quoteCount}/${targetCount}` : "已就绪";
      if (riskStage) riskStage.style.setProperty("--coverage-angle", `${coverage * 360}deg`);
      paintLivePools(
        data.live_pools || {},
        data.selection_mode || "close",
        data.tracking_codes || {},
      );
      paintLiveTracking(data.live_tracking || {});
      paintTicker(data.quotes || {});
      Object.entries(data.quotes || {}).forEach(([code, quote]) => {
        document.querySelectorAll(`[data-live-code="${code}"]`).forEach((row) => {
          const price = row.querySelector("[data-live-price]");
          const change = row.querySelector("[data-live-change]");
          const time = row.querySelector("[data-live-time]");
          if (price) price.textContent = Number(quote.price).toFixed(2);
          if (change) {
            change.textContent = formatPct(Number(quote.change_pct));
            setTone(change, Number(quote.change_pct));
          }
          if (time) {
            const stamp = String(quote.server_time || data.latest_quote_time || "");
            const display = formatQuoteTime(stamp);
            time.textContent = display ? `${display} 行情` : "最新行情";
          }
          row.classList.remove("quote-updated");
          void row.offsetWidth;
          row.classList.add("quote-updated");
        });
      });
    } catch (error) {
      dot.className = "status-dot error";
      status.textContent = "实时行情暂不可用";
      detail.textContent = "当前仍显示最近一次已验证的收盘数据";
      if (lensValue) lensValue.textContent = "离线";
    }
  }
  refreshLive();
  window.setInterval(refreshLive, 60_000);
})();
"""


def _cover_candles() -> str:
    y_positions = [84, 81, 78, 74, 70, 66, 62, 58, 54, 50, 46, 42, 38, 34, 30, 27, 23, 20, 17, 14, 11, 8, 5]
    green_indices = {2, 6, 10, 15, 19}
    heights = [30, 44, 25, 52, 38, 48, 28, 56, 42, 50, 27, 58, 40, 55, 46, 26, 61, 45, 54, 28, 62, 49, 66]
    candles = []
    for index, (y, height) in enumerate(zip(y_positions, heights)):
        x = 32 + index * 2.65
        tone = "down" if index in green_indices else "up"
        candles.append(
            f'<span class="cover-candle {tone}" style="--x:{x:.2f}%;--y:{y}%;'
            f'--h:{height}px;--i:{index}">'
            '<i class="cover-wick"></i><b class="cover-body"></b></span>'
        )
    return "".join(candles)


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


def _rate(value: float | None) -> str:
    if value is None:
        return "—"
    return f'<span class="numeric positive">{value:.2f}%</span>'


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


def _operation_for_status(status: str, explicit: object = "", *, pending: bool = False) -> str:
    if str(explicit).strip():
        return str(explicit).strip()
    if pending:
        return "等待买入"
    return {
        "趋势开始": "建议买入",
        "上升趋势中": "继续持有",
        "待观察中": "谨慎持有",
        "趋势结束": "建议卖出",
        "数据待确认": "暂停操作",
    }.get(status, "继续观察")


def _operation_class(operation: str) -> str:
    if "等待收盘" in operation or "触发" in operation:
        return "confirm"
    if "买入" in operation and "等待" not in operation:
        return "buy"
    if "卖出" in operation or "停止" in operation:
        return "sell"
    if "谨慎" in operation or "取消" in operation:
        return "caution"
    if "持有" in operation:
        return "hold"
    return "wait"


def _operation_badge(operation: str, *, live: bool = False) -> str:
    live_attr = " data-live-operation" if live else ""
    return (
        f'<span class="operation-ticket {_operation_class(operation)}"'
        f'{live_attr}>{_esc(operation)}</span>'
    )


def _position_row(position: dict, area: str = "main") -> str:
    status = str(position.get("status", "上升趋势中"))
    status_class = (
        "warn" if status == "待观察中"
        else "ended" if status == "趋势结束"
        else "neutral" if status == "数据待确认"
        else "good"
    )
    entry = float(position["entry_price"])
    settled_return = float(position.get("return_pct", 0.0))
    return_class = "positive" if settled_return >= 0 else "negative"
    detail = str(
        position.get("status_detail")
        or (
            "龙虎线转弱观察，尚未触发趋势结束条件"
            if int(position.get("missing_streak", 0))
            else "趋势条件仍有效，盘中持续跟踪"
        )
    )
    operation = _operation_for_status(
        status,
        position.get("operation", ""),
    )
    return f"""
    <tr data-tracking-code="{_esc(position['code'])}" data-tracking-area="{_esc(area)}">
      <td data-label="股票">{_stock_cell(position['code'], position['name'], int(position['market']))}</td>
      <td data-label="加入日 / 价格" class="numeric">{position['entry_date']}<span class="subline">{entry:.2f} 元</span></td>
      <td data-label="最新价 / 时间"><span class="numeric" data-live-price>{float(position['last_close']):.2f}</span>
          <span class="subline" data-live-time>{_esc(position['last_date'])} 收盘</span></td>
      <td data-label="实时收益"><span class="numeric {return_class}" data-live-return>{settled_return:+.2f}%</span><span class="subline">盘中估算，收盘结算</span></td>
      <td data-label="跟踪时长" class="numeric">{int(position['holding_days'])} 日</td>
      <td data-label="状态 / 操作"><div class="status-operation"><span class="state {status_class}" data-live-status>{_esc(status)}</span>{_operation_badge(operation, live=True)}</div><span class="subline status-detail-line" data-live-status-detail>{_esc(detail)}</span></td>
    </tr>"""


def _pending_row(setup: dict, area: str = "main") -> str:
    setup_price = float(setup["setup_price"])
    last_close = float(setup.get("last_close", setup_price))
    setup_return = (
        (last_close / setup_price - 1.0) * 100.0 if setup_price else 0.0
    )
    return_class = "positive" if setup_return >= 0 else "negative"
    operation = _operation_for_status(
        "待观察中",
        setup.get("operation", ""),
        pending=True,
    )
    breakout_high = float(setup.get("breakout_high_5", 0.0) or 0.0)
    breakout_note = (
        f"收盘突破 {breakout_high:.2f} 元确认买点"
        if breakout_high > 0
        else "前5日高点数据等待更新"
    )
    return f"""
    <tr data-tracking-code="{_esc(setup['code'])}" data-tracking-area="{_esc(area)}" data-pending-setup="true">
      <td data-label="股票">{_stock_cell(setup['code'], setup['name'], int(setup['market']))}</td>
      <td data-label="信号日 / 价格" class="numeric">{_esc(setup['setup_date'])}<span class="subline">{setup_price:.2f} 元</span></td>
      <td data-label="最新价 / 时间"><span class="numeric" data-live-price>{last_close:.2f}</span>
          <span class="subline" data-live-time>{_esc(setup.get('last_date', setup['setup_date']))} 收盘</span></td>
      <td data-label="距信号涨幅"><span class="numeric {return_class}" data-live-return>{setup_return:+.2f}%</span><span class="subline">{_esc(breakout_note)}</span></td>
      <td data-label="等待时长" class="numeric">{int(setup.get('setup_elapsed_bars', 0))} 日</td>
      <td data-label="状态 / 操作"><div class="status-operation"><span class="state warn" data-live-status>待观察中</span>{_operation_badge(operation, live=True)}</div><span class="subline status-detail-line" data-live-status-detail>{_esc(setup.get('status_detail', '等待收盘突破前5日高点'))}</span></td>
    </tr>"""


def _closed_row(position: dict) -> str:
    operation = _operation_for_status(
        "趋势结束",
        position.get("operation", "建议卖出"),
    )
    return f"""
    <tr>
      <td>{_stock_cell(position['code'], position['name'], int(position['market']))}</td>
      <td class="numeric">{_esc(position['entry_date'])}<span class="subline">{float(position['entry_price']):.2f} 元</span></td>
      <td class="numeric">{_esc(position.get('exit_date', ''))}<span class="subline">{float(position.get('exit_price', 0)):.2f} 元</span></td>
      <td>{_pct(float(position.get('exit_return_pct', 0.0)))}</td>
      <td class="numeric">{int(position.get('holding_days', 0))} 日</td>
      <td class="muted">{_operation_badge(operation)}<span class="subline status-detail-line">{_esc(position.get('exit_reason', ''))}</span></td>
    </tr>"""


def _yellow_note(item) -> str:
    yellow_date = str(getattr(item, "yellow_date", ""))
    return f"{yellow_date or '有效窗口内'} · {int(item.yellow_count)} 根"


def _observation_yellow(item) -> tuple[bool, str]:
    ok = bool(getattr(item, "observation_yellow_ok", item.yellow_ok))
    date = str(
        getattr(item, "observation_yellow_date", getattr(item, "yellow_date", ""))
    )
    count = int(
        getattr(item, "observation_yellow_count", item.yellow_count)
    )
    return ok, f"{date or '未出现'} · 连续 {count} 根"


def _evaluation_row(item, observation: bool = False) -> str:
    entry_price = float(item.close)
    chart = str(item.chart).replace(
        'aria-label="最近',
        f'aria-label="{_esc(item.name)} 最近',
        1,
    )
    base = f"""
    <tr data-live-code="{_esc(item.code)}" data-entry-price="{entry_price:.4f}">
      <td>{_stock_cell(item.code, item.name, int(item.market))}</td>
      <td><span class="numeric" data-live-price>{entry_price:.2f}</span>
          <span class="subline"><span class="numeric" data-live-change>{item.change_pct:+.2f}%</span>
          · <span data-live-time>{_esc(item.date)} 收盘</span></span></td>
      <td class="chart-cell">{chart}</td>"""
    if observation:
        priority = "龙虎优先" if item.cross_ok else "见底候选" if item.bottom_ok else "普通观察"
        observation_yellow_ok, observation_yellow_note = _observation_yellow(item)
        return base + f"""
      <td>{_signal(item.cross_ok, item.cross_date or '未出现')}</td>
      <td>{_signal(item.bottom_ok, item.bottom_date or '未出现')}</td>
      <td>{_signal(observation_yellow_ok, observation_yellow_note)}</td>
      <td>{_signal(item.limit_up_ok, item.limit_up_date or '未出现')}</td>
      <td><span class="state neutral">{priority}</span></td>
    </tr>"""
    return base + f"""
      <td>{_signal(item.bottom_ok, item.bottom_date or '未命中')}</td>
      <td>{_signal(item.cross_ok, item.cross_date or '未命中')}</td>
      <td>{_signal(item.limit_up_ok, item.limit_up_date or '未命中')}</td>
      <td>{_signal(item.yellow_ok, _yellow_note(item))}</td>
    </tr>"""


def _live_pool_row(item, area: str) -> str:
    label = "最近收盘主选信号" if area == "main" else "最近收盘次选信号"
    return f"""
    <tr data-live-code="{_esc(item.code)}">
      <td data-label="股票">{_stock_cell(item.code, item.name, int(item.market))}</td>
      <td data-label="最新行情"><span class="numeric" data-live-price>{float(item.close):.2f}</span>
          <span class="subline"><span class="numeric" data-live-change>{item.change_pct:+.2f}%</span>
          · <span data-live-time>{_esc(item.date)} 收盘</span></span></td>
      <td data-label="可能见底">{_signal(item.bottom_ok, item.bottom_date or '未命中')}</td>
      <td data-label="龙腾跃虎">{_signal(item.cross_ok, item.cross_date or '未命中')}</td>
      <td data-label="42日涨停">{_signal(item.limit_up_ok, item.limit_up_date or '未命中')}</td>
      <td data-label="窗口黄柱">{_signal(item.yellow_ok, _yellow_note(item))}</td>
      <td data-label="状态 / 操作" class="live-pool-status"><div class="status-operation"><span class="state warn">待观察中</span>{_operation_badge('等待买入')}</div>
          <span class="subline status-detail-line">{label}已形成；10日内收盘突破此前5日最高价才确认趋势开始</span></td>
    </tr>"""


def _observation_compact_row(item) -> str:
    priority = "龙虎优先" if item.cross_ok else "见底候选" if item.bottom_ok else "普通观察"
    observation_yellow_ok, observation_yellow_note = _observation_yellow(item)
    return f"""
    <tr data-live-code="{_esc(item.code)}">
      <td>{_stock_cell(item.code, item.name, int(item.market))}</td>
      <td><span class="numeric" data-live-price>{float(item.close):.2f}</span>
          <span class="subline"><span class="numeric" data-live-change>{item.change_pct:+.2f}%</span>
          · <span data-live-time>{_esc(item.date)} 收盘</span></span></td>
      <td>{_signal(item.cross_ok, item.cross_date or '未出现')}</td>
      <td>{_signal(item.bottom_ok, item.bottom_date or '未出现')}</td>
      <td>{_signal(observation_yellow_ok, observation_yellow_note)}</td>
      <td>{_signal(item.limit_up_ok, item.limit_up_date or '未出现')}</td>
      <td><span class="state neutral">{priority}</span></td>
    </tr>"""


def _events(events: Sequence[dict]) -> str:
    labels = {
        "added": "确认主选趋势开始",
        "signal_lost": "龙虎信号转弱",
        "signal_restored": "龙虎信号恢复",
        "removed": "趋势结束，已移出主选区",
        "ineligible_removed": "股票名称含 ST，已移出",
        "secondary_added": "确认次选趋势开始",
        "secondary_removed": "趋势结束，已移出次选区",
        "trend_warning": "趋势转弱预警，继续跟踪止盈线",
        "secondary_promoted": "条件补齐，升级主选区；持有期不断开",
        "setup_added": "主选信号形成，等待收盘突破前5日高点",
        "secondary_setup_added": "次选信号形成，等待收盘突破前5日高点",
        "setup_promoted": "候选条件补齐，升级为主选等待确认",
        "setup_cancelled": "候选信号失效，未产生建议买点",
        "trend_started": "收盘突破前5日高点，确认趋势开始并建议买入",
    }
    items = []
    for event in events:
        suffix = (
            f"，阶段收益 {float(event['return_pct']):+.2f}%"
            if "return_pct" in event
            else ""
        )
        if event.get("reason"):
            suffix += f"，原因：{_esc(event['reason'])}"
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


def _trend_case_chart() -> str:
    path = Path(__file__).resolve().parent / "results" / "trend_case.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        bars = payload["bars"]
        dragon = [float(value) for value in payload["dragon"]]
        tiger = [float(value) for value in payload["tiger"]]
        wave_dragon = [float(value) for value in payload["wave_dragon"]]
        wave_tiger = [float(value) for value in payload["wave_tiger"]]
        yellow_dates = {str(value) for value in payload["yellow_dates"]}
        signal_index = next(
            index
            for index, bar in enumerate(bars)
            if bar["date"] == payload.get("entry_date", payload["signal_date"])
        )
        peak_index = next(
            index
            for index, bar in enumerate(bars)
            if bar["date"] == payload["peak_date"]
        )
        exit_index = next(
            index
            for index, bar in enumerate(bars)
            if bar["date"] == payload["exit_date"]
        )
        cross_index = next(
            index
            for index, bar in enumerate(bars)
            if bar["date"] == payload["cross_date"]
        )
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return ""
    if (
        len(bars) < 3
        or len(dragon) != len(tiger)
        or not dragon
        or len(dragon) > signal_index + 1
        or len(wave_dragon) != len(bars)
        or len(wave_tiger) != len(bars)
        or wave_dragon[: len(dragon)] != dragon
        or wave_tiger[: len(tiger)] != tiger
    ):
        return ""

    formula_yellow_dates = {
        str(bar["date"])
        for index, bar in enumerate(bars)
        if wave_dragon[index] > min(float(bar["open"]), float(bar["close"]))
    }

    width, height = 900.0, 320.0
    left, right, top, bottom = 45.0, 48.0, 39.0, 33.0
    plot_width = width - left - right
    plot_height = height - top - bottom
    lowest = min(float(bar["low"]) for bar in bars)
    highest = max(float(bar["high"]) for bar in bars)
    padding = max((highest - lowest) * 0.07, 0.5)
    price_min = lowest - padding
    price_max = highest + padding

    def x_at(index: int) -> float:
        return left + plot_width * index / max(1, len(bars) - 1)

    def y_at(price: float) -> float:
        return top + (price_max - price) / (price_max - price_min) * plot_height

    grid = []
    for step in range(5):
        price = price_min + (price_max - price_min) * step / 4
        y = y_at(price)
        grid.append(
            f'<line class="case-grid" x1="{left:.1f}" y1="{y:.1f}" '
            f'x2="{width-right:.1f}" y2="{y:.1f}"/>'
            f'<text class="case-axis-label" x="7" y="{y+3:.1f}">{price:.1f}</text>'
        )

    candle_width = max(3.2, min(8.6, plot_width / len(bars) * 0.52))
    candles = []
    for index, bar in enumerate(bars):
        open_price = float(bar["open"])
        close_price = float(bar["close"])
        body_low = min(open_price, close_price)
        body_high = max(open_price, close_price)
        x = x_at(index)
        y_open = y_at(open_price)
        y_close = y_at(close_price)
        y_high = y_at(float(bar["high"]))
        y_low = y_at(float(bar["low"]))
        body_y = min(y_open, y_close)
        body_height = max(1.5, abs(y_open - y_close))
        tone = "up" if close_price >= open_price else "down"
        title = (
            f"{bar['date']} 开{open_price:.2f} 高{float(bar['high']):.2f} "
            f"低{float(bar['low']):.2f} 收{close_price:.2f}"
        )
        yellow_part = ""
        if str(bar["date"]) in formula_yellow_dates:
            yellow_top_price = min(body_high, wave_dragon[index])
            if yellow_top_price > body_low:
                yellow_y = y_at(yellow_top_price)
                yellow_height = max(2.2, y_at(body_low) - yellow_y)
                yellow_kind = (
                    "qualified" if str(bar["date"]) in yellow_dates
                    else "contextual"
                )
                yellow_part = (
                    f'<rect class="case-yellow-body {yellow_kind}" '
                    f'x="{x-candle_width/2:.1f}" y="{yellow_y:.1f}" '
                    f'width="{candle_width:.1f}" height="{yellow_height:.1f}" rx="1"/>'
                )
        candles.append(
            f'<g class="case-candle {tone}" style="--i:{index}">'
            f'<title>{_esc(title)}</title>'
            f'<line class="case-wick" x1="{x:.1f}" y1="{y_high:.1f}" '
            f'x2="{x:.1f}" y2="{y_low:.1f}"/>'
            f'<rect class="case-body" x="{x-candle_width/2:.1f}" y="{body_y:.1f}" '
            f'width="{candle_width:.1f}" height="{body_height:.1f}" rx="1"/>'
            f'{yellow_part}</g>'
        )

    wave_dragon_line = " ".join(
        f"{x_at(index):.1f},{y_at(value):.1f}"
        for index, value in enumerate(wave_dragon)
    )
    wave_tiger_line = " ".join(
        f"{x_at(index):.1f},{y_at(value):.1f}"
        for index, value in enumerate(wave_tiger)
    )

    signal_x = x_at(signal_index)
    signal_y = y_at(float(bars[signal_index]["high"]))
    cross_x = x_at(cross_index)
    cross_y = y_at(wave_dragon[cross_index])
    peak_x = x_at(peak_index)
    peak_y = y_at(float(payload["peak_close"]))
    exit_x = x_at(exit_index)
    exit_y = y_at(float(payload["exit_close"]))
    line_label_x = x_at(len(bars) - 1) + 8
    dragon_label_y = y_at(wave_dragon[-1]) + 3
    tiger_label_y = y_at(wave_tiger[-1]) + 3
    stop_drawdown = 2.0 if "回撤2%" in str(payload["exit_reason"]) else 5.0
    stop_price = float(payload["peak_close"]) * (1.0 - stop_drawdown / 100.0)
    stop_y = y_at(stop_price)
    stop_markup = ""
    if "回撤" in str(payload["exit_reason"]):
        stop_markup = (
            f'<line class="case-stop-line" x1="{peak_x:.1f}" y1="{stop_y:.1f}" '
            f'x2="{exit_x:.1f}" y2="{stop_y:.1f}"/>'
            f'<text class="case-stop-label" x="{peak_x+7:.1f}" '
            f'y="{stop_y-6:.1f}">高点回撤{stop_drawdown:.0f}%</text>'
        )
    end_path_start_x = min(width - right - 78, exit_x - 76)
    end_path_start_y = top + 42
    date_ticks = []
    tick_indices = [0, signal_index, peak_index, exit_index]
    if len(bars) - 1 - exit_index >= 3:
        tick_indices.append(len(bars) - 1)
    for index in tick_indices:
        date_ticks.append(
            f'<text class="case-axis-label" text-anchor="middle" '
            f'x="{x_at(index):.1f}" y="{height-10:.1f}">'
            f'{_esc(str(bars[index]["date"])[5:])}</text>'
        )

    return f"""
    <div class="trend-case" aria-label="历史真实案例：{_esc(payload['name'])}信号确认与建议结束点">
      <div class="trend-case-head">
        <div><strong>真实案例 · {_esc(payload['name'])} {_esc(payload['code'])}</strong><span>前复权 · 逐日无未来数据重放</span></div>
        <div class="trend-case-legend" aria-label="完整波段图图例"><span><i class="dragon"></i>龙线</span><span><i class="tiger"></i>虎线</span><span><i class="yellow-formula"></i>公式黄柱</span><span><i class="yellow-qualified"></i>有效窗口黄柱</span></div>
      </div>
      <div class="trend-case-wave-head"><strong>完整波段 · 龙虎线与黄柱</strong><span>蓝箭头指建议买点，红箭头落在规则卖点K线上</span></div>
      <div class="trend-case-canvas">
        <div class="case-pin start"><b>趋势开始</b><small>{_esc(payload.get('entry_date', payload['signal_date']))}</small></div>
        <div class="case-pin peak"><b>波段高点</b><small>+{float(payload['peak_return_pct']):.2f}%</small></div>
        <div class="case-pin end"><b>建议结束</b><small>{_esc(payload['exit_date'])}</small></div>
        <svg class="trend-case-svg" viewBox="0 0 900 320" preserveAspectRatio="none" role="img" aria-labelledby="trend-case-title trend-case-desc">
          <title id="trend-case-title">{_esc(payload['name'])}历史案例K线图</title>
          <desc id="trend-case-desc">{_esc(payload['signal_date'])}形成入选信号，{_esc(payload.get('entry_date', payload['signal_date']))}收盘突破此前5日最高价确认趋势开始，{_esc(payload['exit_date'])}按规则结束。</desc>
          <defs>
            <marker id="case-arrow-blue" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="#2457d6"/></marker>
            <marker id="case-arrow-red" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="#d4512f"/></marker>
          </defs>
          {''.join(grid)}
          {''.join(candles)}
          <polyline class="case-tiger-line" points="{wave_tiger_line}"/>
          <polyline class="case-dragon-line" points="{wave_dragon_line}"/>
          <text class="case-line-label dragon" x="{line_label_x:.1f}" y="{dragon_label_y:.1f}">龙</text>
          <text class="case-line-label tiger" x="{line_label_x:.1f}" y="{tiger_label_y:.1f}">虎</text>
          {stop_markup}
          <line class="case-cross-guide" x1="{cross_x:.1f}" y1="{cross_y-31:.1f}" x2="{cross_x:.1f}" y2="{cross_y-7:.1f}"/>
          <circle class="case-cross-ring" cx="{cross_x:.1f}" cy="{cross_y:.1f}" r="5"/>
          <text class="case-cross-label" x="{cross_x+8:.1f}" y="{cross_y-14:.1f}">2/5 回看上穿</text>
          <line class="case-peak-guide" x1="{peak_x:.1f}" y1="{top+22:.1f}" x2="{peak_x:.1f}" y2="{peak_y-7:.1f}"/>
          <circle class="case-peak-ring" cx="{peak_x:.1f}" cy="{peak_y:.1f}" r="5"/>
          <path class="case-arrow-start" d="M {max(left+8,signal_x-63):.1f} {top+24:.1f} C {signal_x-51:.1f} {top+54:.1f}, {signal_x-17:.1f} {signal_y-24:.1f}, {signal_x:.1f} {signal_y-6:.1f}"/>
          <path class="case-arrow-end" d="M {end_path_start_x:.1f} {end_path_start_y:.1f} C {end_path_start_x+31:.1f} {end_path_start_y+12:.1f}, {exit_x-19:.1f} {exit_y-34:.1f}, {exit_x:.1f} {exit_y-8:.1f}"/>
          <circle class="case-exit-target" cx="{exit_x:.1f}" cy="{exit_y:.1f}" r="5.5"/>
          {''.join(date_ticks)}
        </svg>
      </div>
      <div class="trend-case-notes">
        <div class="trend-case-note start"><span>信号形成 / 趋势开始（建议买点）</span><strong>{_esc(payload['signal_date'])} / {_esc(payload.get('entry_date', payload['signal_date']))} · {float(payload.get('entry_close', payload['signal_close'])):.2f}元</strong></div>
        <div class="trend-case-note peak"><span>最高收盘</span><strong>{_esc(payload['peak_date'])} · +{float(payload['peak_return_pct']):.2f}%</strong></div>
        <div class="trend-case-note end"><span>建议结束</span><strong>{_esc(payload['exit_date'])} · +{float(payload['exit_return_pct']):.2f}%</strong></div>
      </div>
      <div class="trend-case-foot">{_esc(payload['source'])}。{_esc(payload['signal_date'])}满足入选条件，只进入待观察；{_esc(payload.get('entry_date', payload['signal_date']))}收盘突破此前5日最高价，蓝色箭头标记正式建议买点。龙虎线按每天当时可见的数据逐日重算，淡黄表示公式黄柱，金色描边表示有效配对黄柱。红色箭头与圆环共同指向{_esc(payload['exit_date'])}收盘触发的“{_esc(payload['exit_reason'])}”。图中保留卖点后的行情，用于直观看到规则可能提前保护利润、也可能错过后续再加速；未计费用、滑点和涨跌停无法成交。</div>
    </div>"""


def _repaint_comparison_panel() -> str:
    """Render live-repainted signals separately from hindsight-only final charts."""
    path = Path(__file__).resolve().parent / "results" / "signal_repaint_comparison.json"
    window_path = Path(__file__).resolve().parent / "results" / "signal_window_optimization.json"
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        window_payload = json.loads(window_path.read_text(encoding="utf-8"))
        coverage = payload["coverage"]
        live = payload["causal_live_signals"]
        final = payload["final_chart_signals"]
        disappeared_wave = live["disappeared_wave"]
        retained_wave = live["cross_retained_wave"]
        final_wave = final["wave"]
        disappeared_rows = {
            str(item["id"]): item
            for item in live["disappeared_strategy_rows"]
        }
        retained_rows = {
            str(item["id"]): item
            for item in live["cross_retained_strategy_rows"]
        }
        erased_exit = disappeared_rows[
            "confirm_0_close__erasure_or_relationship"
        ]["overall"]
        hold_20 = disappeared_rows["confirm_0_close__hold_20"]["overall"]
        trail_8_3 = disappeared_rows["confirm_0_close__trail_8_3"]["overall"]
        wait_1 = disappeared_rows["confirm_1_close__hold_20"]
        retained_relationship = retained_rows[
            "confirm_0_close__relationship"
        ]["overall"]
        final_hindsight_exit = final[
            "hindsight_strategy_comparison"
        ]["highest_average"]["overall"]
        failures = list(final.get("strict_failure_examples", []))
        short_term_count = int(window_payload["signals"]["recalculated_away_count"])
        short_term_total = int(window_payload["signals"]["common_trade_cohort_count"])
        short_term_rate = float(window_payload["signals"]["recalculated_away_rate_pct"])
    except (OSError, ValueError, KeyError, TypeError):
        return ""

    failure_cards = []
    for item in failures:
        code = str(item["code"])
        market = 1 if code.startswith("6") else 0
        failure_cards.append(
            '<div class="repaint-failure">'
            f'<a href="{_link(code, market)}" target="_blank" rel="noreferrer">'
            f'{_esc(item["name"])} {_esc(code)}</a>'
            f'<span>{_esc(item["signal_date"])} · 后续波段高点 '
            f'{float(item["peak_high_return_pct"]):+.2f}%</span></div>'
        )

    return f"""
      <article class="repaint-panel" aria-label="龙腾跃虎信号重绘对照">
        <div class="repaint-head">
          <div><span class="section-kicker">Signal lineage</span><h3>信号重绘对照 · 独立统计</h3>
          <p>同一套“交叉前2日至后7日出现至少1根黄柱”规则，分别统计当时实盘可见的信号、后来被重绘的信号，以及今天完整历史图留下的信号。</p></div>
          <span class="repaint-badge">全 A 股 · {int(coverage['analyzed_stock_count'])} 只</span>
        </div>
        <div class="repaint-lineage">
          <div class="lineage-origin"><span>当时逐日计算曾确认</span><strong>{int(live['total']):,}</strong><small>次独立信号事件</small></div>
          <div class="lineage-fork" aria-hidden="true"></div>
          <div class="lineage-branches">
            <div class="lineage-branch lost"><span>原交叉日期后来消失或迁移</span><strong>{int(live['disappeared_count']):,} · {float(live['disappeared_rate_pct']):.2f}%</strong><small>长时间加入未来K线后的最终重绘结果</small></div>
            <div class="lineage-branch kept"><span>原交叉日期最终仍保留</span><strong>{int(live['cross_retained_count']):,} · {float(live['cross_retained_rate_pct']):.2f}%</strong><small>同一天交叉在当前完整历史图仍可见</small></div>
          </div>
        </div>
        <div class="repaint-warning"><strong>两个“消失率”不是一回事：</strong>同口径的 {short_term_total:,} 个实盘信号中，有 {short_term_count:,} 个（{short_term_rate:.2f}%）在原信号显示期内被重算掉，这是实盘短期可观察风险；98.96% 指把所有后续行情加入后，原交叉日期最终被 XMA 重绘或迁移。附近日期若出现新交叉，原日期仍计为消失。</div>
        <div class="repaint-columns">
          <section class="repaint-cohort">
            <h4>当时出现，后来消失或迁移</h4>
            <p>这是实盘会真正遇到的主体样本。收益从当时信号日收盘起算，到龙虎关系结束或最长60日内的本轮高点。</p>
            <div class="repaint-stats">
              <div class="repaint-stat"><span>可计算样本</span><strong>{int(disappeared_wave['sample_count']):,}</strong></div>
              <div class="repaint-stat"><span>后续曾高于信号价</span><strong>{float(disappeared_wave['ever_rise_rate_pct']):.2f}%</strong></div>
              <div class="repaint-stat"><span>本轮曾达到5%</span><strong>{float(disappeared_wave['ever_reach_5pct_rate_pct']):.2f}%</strong></div>
              <div class="repaint-stat"><span>本轮高点平均涨幅</span><strong>{float(disappeared_wave['average_peak_high_return_pct']):+.2f}%</strong></div>
              <div class="repaint-stat"><span>消失即卖实际胜率</span><strong>{float(erased_exit['positive_rate_pct']):.2f}%</strong></div>
              <div class="repaint-stat"><span>消失即卖平均收益</span><strong>{float(erased_exit['average_pct']):+.2f}%</strong></div>
            </div>
          </section>
          <section class="repaint-cohort">
            <h4>当时出现，同一交叉日期最终保留</h4>
            <p>精确匹配到同一天的样本只有 {int(retained_wave['sample_count'])} 次，分类要等未来走完才知道，样本小，不能在当时提前识别。</p>
            <div class="repaint-stats">
              <div class="repaint-stat"><span>精确保留样本</span><strong>{int(retained_wave['sample_count'])}</strong></div>
              <div class="repaint-stat"><span>后续曾高于信号价</span><strong>{float(retained_wave['ever_rise_rate_pct']):.2f}%</strong></div>
              <div class="repaint-stat"><span>本轮曾达到5%</span><strong>{float(retained_wave['ever_reach_5pct_rate_pct']):.2f}%</strong></div>
              <div class="repaint-stat"><span>本轮高点平均涨幅</span><strong>{float(retained_wave['average_peak_high_return_pct']):+.2f}%</strong></div>
              <div class="repaint-stat"><span>龙虎关系结束卖出胜率</span><strong>{float(retained_relationship['positive_rate_pct']):.2f}%</strong></div>
              <div class="repaint-stat"><span>龙虎关系结束平均收益</span><strong>{float(retained_relationship['average_pct']):+.2f}%</strong></div>
            </div>
          </section>
          <section class="repaint-cohort hindsight">
            <h4>只看今天完整历史图的全部交叉</h4>
            <p>这是事后倒推的形态上限，交叉本身已经使用未来K线重绘，不是当时可执行的买入信号。</p>
            <div class="repaint-stats">
              <div class="repaint-stat"><span>可计算样本</span><strong>{int(final_wave['sample_count']):,}</strong></div>
              <div class="repaint-stat"><span>后续曾高于信号价</span><strong>{float(final_wave['ever_rise_rate_pct']):.2f}%</strong></div>
              <div class="repaint-stat"><span>本轮曾达到5%</span><strong>{float(final_wave['ever_reach_5pct_rate_pct']):.2f}%</strong></div>
              <div class="repaint-stat"><span>本轮高点平均涨幅</span><strong>{float(final_wave['average_peak_high_return_pct']):+.2f}%</strong></div>
              <div class="repaint-stat"><span>事后规则卖出胜率</span><strong>{float(final_hindsight_exit['positive_rate_pct']):.2f}%</strong></div>
              <div class="repaint-stat"><span>事后规则平均收益</span><strong>{float(final_hindsight_exit['average_pct']):+.2f}%</strong></div>
            </div>
          </section>
          <section class="repaint-cohort hindsight">
            <h4>为什么最终图数字会异常漂亮</h4>
            <p>只有未来上涨后最终被保留下来的交叉，更容易在今天的历史图中被看见，形成严重的未来函数偏差。</p>
            <div class="repaint-stats">
              <div class="repaint-stat"><span>严格未上涨案例</span><strong>{int(final['strict_failure_count'])}</strong></div>
              <div class="repaint-stat"><span>严格未上涨占比</span><strong>{100 * int(final['strict_failure_count']) / int(final_wave['sample_count']):.3f}%</strong></div>
              <div class="repaint-stat"><span>结论属性</span><strong>形态验证</strong></div>
            </div>
          </section>
        </div>
        <div class="repaint-warning"><strong>最终历史图不是实盘买点：</strong>99.98% 和平均 +50.52% 不能作为实时成功率。鞍钢股份 2026-03-11 属于“当时短暂出现、后来消失”，不再列入最终历史图失败案例。</div>
        <div class="repaint-strategy">
          <div class="repaint-strategy-card"><strong>买入：不要靠“多等几天看交叉还在不在”</strong><p>强制等1日后只剩 <em>{float(wait_1['entry_rate_pct']):.2f}%</em> 的信号，20日退出平均收益仅 <em>{float(wait_1['overall']['average_pct']):+.2f}%</em>，没有提高胜率。更合理的是：信号形成先记“待观察”，用价格真正启动确认买点；确认前若信号消失就取消。</p></div>
          <div class="repaint-strategy-card"><strong>卖出：已买入后，消失只降级为风险提示</strong><p>短暂信号“消失即卖”平均 <em>{float(erased_exit['average_pct']):+.2f}%</em>、胜率 <em>{float(erased_exit['positive_rate_pct']):.2f}%</em>；改为最长20日且龙虎关系结束才卖为 <em>{float(hold_20['average_pct']):+.2f}% / {float(hold_20['positive_rate_pct']):.2f}%</em>，8%启动后回撤3%为 <em>{float(trail_8_3['average_pct']):+.2f}% / {float(trail_8_3['positive_rate_pct']):.2f}%</em>。因此交叉消失不宜单独触发卖出，应与龙线不再高于虎线或价格回撤联合判断。</p></div>
        </div>
        <details class="repaint-failures"><summary>展开查看当前完整历史图中严格未上涨的 {int(final['strict_failure_count'])} 个案例</summary><div class="repaint-failure-list">{''.join(failure_cards)}</div></details>
      </article>"""


def _strategy_grid_panel() -> str:
    path = Path(__file__).resolve().parent / "results" / "strategy_grid_optimization.json"
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        coverage = payload["coverage"]
        optimization = payload["optimization"]
        candidates = {
            str(item["id"]): item
            for item in optimization["all_candidates"]
        }
        profiles = (
            (
                "success",
                "高成功率",
                "更常兑现小目标",
                candidates["reclaim_dragon__target_3"],
            ),
            (
                "balanced recommended",
                "正式执行策略",
                "胜率与波段空间兼顾 · 已启用",
                candidates["break_5day_high__trail_3_2"],
            ),
            (
                "return",
                "高收益率",
                "接受更低胜率换取更大波段",
                candidates["break_5day_high__trail_8_2"],
            ),
        )
        baseline = candidates["confirm_5__trail_5_5"]
        rejected = candidates["confirm_8__target_3"]
        common_signals = int(payload["signals"]["common_trade_cohort_count"])
    except (OSError, ValueError, KeyError, TypeError):
        return ""

    cards = []
    for css, name, note, row in profiles:
        overall = row["overall"]
        development = row["development_before_2024"]
        validation = row["validation_2024_2025"]
        holdout = row["holdout_2026"]
        phases = (
            ("2024年前", development),
            ("2024—25", validation),
            ("2026留出", holdout),
        )
        phase_markup = "".join(
            f'<div class="strategy-phase"><span>{_esc(label)}</span>'
            f'<div class="strategy-phase-track"><i style="--phase:{float(stats["positive_rate_pct"]):.2f}%"></i></div>'
            f'<b>{float(stats["positive_rate_pct"]):.2f}%</b></div>'
            for label, stats in phases
        )
        cards.append(
            f"""
            <article class="strategy-ticket {css}">
              <div class="strategy-ticket-head"><span class="strategy-ticket-kicker">{_esc(note)}</span><h4>{_esc(name)}</h4><small>仅 {float(row['entry_rate_pct']):.2f}% 的原始信号会确认买点</small></div>
              <div class="strategy-orders"><div class="strategy-order"><b>BUY</b><span>{_esc(row['entry_label'])}</span></div><div class="strategy-order"><b>SELL</b><span>{_esc(row['exit_label'])}</span></div></div>
              <div class="strategy-numbers">
                <div class="strategy-number"><span>已实现成功率</span><strong>{float(overall['positive_rate_pct']):.2f}%</strong></div>
                <div class="strategy-number"><span>每笔平均收益</span><strong>{float(overall['average_pct']):+.2f}%</strong></div>
                <div class="strategy-number"><span>收益中位数</span><strong>{float(overall['median_pct']):+.2f}%</strong></div>
                <div class="strategy-number"><span>完整交易样本</span><strong>{int(overall['sample_count']):,}</strong></div>
                <div class="strategy-number"><span>2026成功率</span><strong>{float(holdout['positive_rate_pct']):.2f}%</strong></div>
                <div class="strategy-number"><span>2026平均收益</span><strong>{float(holdout['average_pct']):+.2f}%</strong></div>
              </div>
              <div class="strategy-phases">{phase_markup}</div>
            </article>"""
        )

    return f"""
      <article class="strategy-lab" aria-label="扩展买卖点全市场回测">
        <div class="strategy-lab-head">
          <div><span class="section-kicker">Execution lab</span><h3>正式策略与两档对照</h3><p>12种买点与88种卖点交叉形成1,056种组合。先用2024年前开发、2024—2025验证，再用2026留出期验收；最终历史图的未来重绘信号不参与选参。</p></div>
          <div class="strategy-lab-stamp"><strong>{int(coverage['analyzed_stock_count']):,}</strong><small>只非ST沪深A股</small><strong>{common_signals:,}</strong><small>次共同信号样本</small></div>
        </div>
        <div class="strategy-tickets">{''.join(cards)}</div>
        <div class="strategy-lab-baseline"><p><strong>上一版同口径基准：</strong>信号后上涨5%确认买入，买后再达到5%浮盈并回撤5%卖出，历史成功率 {float(baseline['overall']['positive_rate_pct']):.2f}%、平均 {float(baseline['overall']['average_pct']):+.2f}%；2026为 {float(baseline['holdout_2026']['positive_rate_pct']):.2f}% / {float(baseline['holdout_2026']['average_pct']):+.2f}%。正式策略与对照方案均改善了至少一个核心目标。</p><div class="strategy-baseline-numbers"><span>组合数 <b>{int(optimization['candidate_count']):,}</b></span><span>行情失败 <b>{int(coverage['error_count'])}</b></span></div></div>
        <p class="strategy-lab-note"><strong>当前正式执行：</strong>信号形成后先等待，10个交易日内收盘严格突破此前5日最高价才建议买入；买入后浮盈曾达到3%，再较最高收盘回撤2%时建议卖出，龙线不再高于虎线或满60日也结束。盘中触发只提示等待收盘确认。高成功率与高收益率方案继续保留为对照，不自动切换。历史表面最高胜率方案为 {float(rejected['overall']['positive_rate_pct']):.2f}%，但2026仅 {int(rejected['holdout_2026']['sample_count'])} 笔且平均 {float(rejected['holdout_2026']['average_pct']):+.2f}%，因此淘汰。收益未计手续费、滑点及涨跌停无法成交，2026样本仍较少。</p>
      </article>"""


def _validation_section() -> str:
    path = Path(__file__).resolve().parent / "results" / "rolling_validation.json"
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        coverage = payload["coverage"]
        forward_60 = payload["base_signal_forward_returns"]["overall"]["60"]
        take_profit = payload["take_profit_analysis"]["rules"]
        weakening = take_profit["weakening_or_cross"]["summary"]
        trailing_10 = take_profit["trailing_10"]["summary"]
        trailing_15 = take_profit["trailing_15"]["summary"]
        trailing_20 = take_profit["trailing_20"]["summary"]
        chart_60 = payload["retrospective_chart_analysis"]["forward_returns"]["overall"]["60"]
        yellow_analysis = payload["yellow_window_analysis"]
        yellow_variants = {
            str(item["id"]): item
            for item in yellow_analysis.get("variants", [])
        }
        recommended_window = yellow_variants[
            str(yellow_analysis["recommended_id"])
        ]
        lifecycle = payload["trend_lifecycle_analysis"]
        lifecycle_candidates = {
            str(item["id"]): item
            for item in lifecycle.get("candidates", [])
        }
        operational_rule = lifecycle_candidates[
            str(
                lifecycle.get(
                    "operational_recommended_id",
                    lifecycle["recommended_id"],
                )
            )
        ]
        literal_expiry_rule = lifecycle_candidates["signal_window_end"]
        relationship_rule = lifecycle_candidates["death_cross"]
        persistence = lifecycle["signal_persistence_analysis"]
        grid_payload = json.loads(
            (
                Path(__file__).resolve().parent
                / "results"
                / "strategy_grid_optimization.json"
            ).read_text(encoding="utf-8")
        )
        balanced_rule = next(
            item
            for item in grid_payload["optimization"]["all_candidates"]
            if item["id"] == "break_5day_high__trail_3_2"
        )
    except (OSError, ValueError, KeyError, TypeError):
        return ""

    if "rally_occurrence_rate_pct" not in forward_60:
        return ""
    rally_5_rate = float(forward_60["rally_5pct_rate_pct"])
    any_rally_rate = float(forward_60["rally_occurrence_rate_pct"])
    if rally_5_rate >= 70.0:
        verdict = f"每100次信号，约有{rally_5_rate:.0f}次在60个交易日内涨到过5%"
    elif rally_5_rate >= 50.0:
        verdict = f"每100次信号，约有{rally_5_rate:.0f}次在60个交易日内涨到过5%"
    elif any_rally_rate >= 50.0:
        verdict = "多数信号曾经上涨，但每100次中不到50次涨到过5%"
    else:
        verdict = "历史样本未验证信号后多数能形成5%涨势"
    def take_profit_row(name: str, stats: dict, note: str) -> str:
        return f"""
        <tr>
          <td><strong>{_esc(name)}</strong><span class="subline">{_esc(note)}</span></td>
          <td class="numeric">{int(stats['successful_trend_count'])}</td>
          <td>{_pct(float(stats['median_pct']))}</td>
          <td>{_rate(float(stats['positive_rate_pct']))}</td>
          <td>{_rate(float(stats['premature_exit_rate_pct']))}</td>
          <td>{_rate(float(stats['median_retained_peak_pct']))}</td>
          <td class="numeric">第 {float(stats['median_exit_day']):.1f} 日</td>
        </tr>"""

    def lifecycle_row(name: str, candidate: dict, note: str) -> str:
        stats = candidate["overall"]
        recent = candidate["holdout_2026"]
        return f"""
        <tr>
          <td><strong>{_esc(name)}</strong><span class="subline">{_esc(note)}</span></td>
          <td class="numeric">{int(stats['sample_count'])}</td>
          <td>{_rate(float(stats['success_rate_pct']))}</td>
          <td>{_pct(float(stats['average_pct']))}</td>
          <td>{_pct(float(stats['median_pct']))}</td>
          <td class="numeric">{float(stats['median_holding_bars']):.1f} 日</td>
          <td>{_rate(float(recent['success_rate_pct']))}<span class="subline">均值 {float(recent['average_pct']):+.2f}%</span></td>
        </tr>"""

    def grid_lifecycle_row(name: str, candidate: dict, note: str) -> str:
        stats = candidate["overall"]
        recent = candidate["holdout_2026"]
        return f"""
        <tr>
          <td><strong>{_esc(name)}</strong><span class="subline">{_esc(note)}</span></td>
          <td class="numeric">{int(stats['sample_count'])}</td>
          <td>{_rate(float(stats['positive_rate_pct']))}</td>
          <td>{_pct(float(stats['average_pct']))}</td>
          <td>{_pct(float(stats['median_pct']))}</td>
          <td class="numeric">{float(stats['median_holding_bars']):.1f} 日</td>
          <td>{_rate(float(recent['positive_rate_pct']))}<span class="subline">均值 {float(recent['average_pct']):+.2f}%</span></td>
        </tr>"""

    return f"""
    <section class="section reveal" id="validation">
      <div class="section-head"><div><span class="section-kicker">Walk-forward evidence</span><h2>历史滚动验证</h2>
      <p class="section-copy">逐日重放，每一天只使用当时已经存在的行情；XMA 尾部按当日可见数据重新计算，因此能识别实盘中短暂出现后又被重算掉的龙腾跃虎信号。买点与卖点按完整波段共同验证。</p></div></div>
      <div class="validation-lead">
        <article class="validation-verdict"><strong>{_esc(verdict)}</strong>
          <p>首次满足主选或次选只记为“信号形成”，不立刻给买点。历史中有 {float(persistence['erased_before_natural_expiry_rate_pct']):.2f}% 的首次入选信号在自然显示期限内被后续 K 线重算掉；正式规则要求信号未被重算消失，并在 10 个交易日内收盘严格突破此前 5 日最高价，当天才确认“趋势开始 / 建议买入”。随后从建议买点跟踪到建议卖点，结束价高于买入价才算成功；尚未结束的实时样本不计成功率。</p>
          {_trend_case_chart().lstrip()}
        </article>
        <div class="validation-facts">
          <div class="validation-fact"><span>形成信号后最终确认买点</span><strong>{int(balanced_rule['overall']['sample_count'])} 次</strong></div>
          <div class="validation-fact"><span>完整波段成功率</span><strong>{float(balanced_rule['overall']['positive_rate_pct']):.2f}%</strong></div>
          <div class="validation-fact"><span>每个完整波段平均收益</span><strong>{float(balanced_rule['overall']['average_pct']):+.2f}%</strong></div>
          <div class="validation-fact"><span>完整波段收益中位数</span><strong>{float(balanced_rule['overall']['median_pct']):+.2f}%</strong></div>
          <div class="validation-fact"><span>通常持有</span><strong>{float(balanced_rule['overall']['median_holding_bars']):.1f} 个交易日</strong></div>
          <div class="validation-fact"><span>2026 年独立时段</span><strong>{float(balanced_rule['holdout_2026']['positive_rate_pct']):.2f}% / {float(balanced_rule['holdout_2026']['average_pct']):+.2f}%</strong></div>
          <div class="validation-fact"><span>回测覆盖股票</span><strong>{int(coverage['analyzed_stock_count'])} 只</strong></div>
          <div class="validation-fact"><span>未取得完整历史行情</span><strong>{int(coverage.get('error_count', 0))} 只</strong></div>
        </div>
      </div>
      {_repaint_comparison_panel().lstrip()}
      <!-- strategy-grid:start -->
      {_strategy_grid_panel().lstrip()}
      <!-- strategy-grid:end -->
      <article class="panel">
        <div class="panel-head"><div><h3>买点与卖点联合比较</h3><p>所有统计都从实际建议买点算到建议卖点；未确认买点和未结束持仓不混入成功率。</p></div></div>
        <div class="table-scroll"><table><thead><tr><th>规则</th><th>完整波段</th><th>成功率</th><th>平均收益</th><th>收益中位数</th><th>通常持有</th><th>2026 年</th></tr></thead>
        <tbody>{grid_lifecycle_row('正式采用：突破5日高点 + 3%/2%移动止盈', balanced_rule, '信号持续；10日内收盘突破此前5日最高价才买入；买入后达到3%浮盈，再从最高收盘回撤2%卖出；龙线不再高于虎线或60日结束')}{lifecycle_row('上一版：5%确认启动 + 5%移动止盈', operational_rule, '仅作历史对照，已停止新增样本')}{lifecycle_row('首次入选即买，等龙虎关系结束', relationship_rule, '用于比较延后确认买点的价值')}</tbody></table></div>
        <p class="validation-method">正式状态：首次入选为“待观察中 / 等待买入”；突破前5日高点的收盘日为“趋势开始 / 建议买入”；未触发风险时为“上升趋势中 / 继续持有”；标签重算消失、龙虎同步转弱或接近止盈线时为“待观察中 / 谨慎持有”；龙线不再高于虎线、达到3%浮盈后从最高收盘回撤2%，或满60个后续交易日时为“趋势结束 / 建议卖出”。盘中触发只显示“等待收盘确认”，不提前移出或结算。回测覆盖 {_esc(str(coverage['start_date']))}—{_esc(str(coverage['end_date']))}，分析 {int(coverage['analyzed_stock_count'])}/{int(coverage['requested_stock_count'])} 只，失败 {int(coverage.get('error_count', 0))} 只。未计手续费、滑点和涨跌停无法成交，并存在当前上市股票样本的幸存者偏差。本结果用于规则验证，不构成收益承诺。</p>
      </article>
    </section>"""


def render_report(
    evaluations: Sequence,
    cfg: dict,
    scanned: int,
    errors: Sequence[str],
    strategy_state: dict,
    events: Sequence[dict],
) -> str:
    selected = [item for item in evaluations if item.selected and item.eligible]
    tracked_main_codes = {
        str(item["code"]) for item in strategy_state["active"]
    }
    pending_main_codes = {
        str(item["code"])
        for item in strategy_state.get("pending_main", [])
    }
    tracked_secondary_codes = {
        str(item["code"])
        for item in strategy_state.get("secondary_active", [])
    }
    pending_secondary_codes = {
        str(item["code"])
        for item in strategy_state.get("pending_secondary", [])
    }
    main_area_codes = (
        {str(item.code) for item in selected}
        | tracked_main_codes
        | pending_main_codes
    )
    secondary = [
        item
        for item in evaluations
        if item.eligible
        and not item.selected
        and str(item.code) not in main_area_codes
        and item.cross_ok
        and item.yellow_ok
        and (item.bottom_ok or item.limit_up_ok)
    ]
    occupied_codes = (
        main_area_codes
        | {str(item.code) for item in secondary}
        | tracked_secondary_codes
        | pending_secondary_codes
    )
    near = [
        item
        for item in visible_observations(
            evaluations,
            cfg["near_match_minimum"],
        )
        if str(item.code) not in occupied_codes
    ]
    trade_date = max((item.date for item in evaluations), default="无数据")
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    cover_desktop = "assets/hero-aigc-v2-poster.webp"
    cover_mobile = "assets/hero-aigc-v2-poster-mobile.webp"
    main_stats = strategy_stats(strategy_state)
    secondary_stats = secondary_strategy_stats(strategy_state)
    legacy_active_total = int(main_stats.get("legacy_active_count", 0)) + int(
        secondary_stats.get("legacy_active_count", 0)
    )
    migration_note = (
        f'<div class="events"><strong>策略切换说明</strong><ul><li>现有 {legacy_active_total} 只旧规则持仓继续按新的卖点实时管理，但不混入新策略成功率；新成功率只统计本次切换后完成的完整买卖波段。</li></ul></div>'
        if legacy_active_total
        else ""
    )
    tracked_main_count = len(strategy_state["active"])
    tracked_secondary_count = len(strategy_state.get("secondary_active", []))
    pending_main_count = len(strategy_state.get("pending_main", []))
    pending_secondary_count = len(strategy_state.get("pending_secondary", []))
    active_rows = "".join(
        [
            *(
                _pending_row(item, "main")
                for item in strategy_state.get("pending_main", [])
            ),
            *(
                _position_row(item, "main")
                for item in strategy_state["active"]
            ),
        ]
    )
    secondary_active_rows = "".join(
        [
            *(
                _pending_row(item, "secondary")
                for item in strategy_state.get("pending_secondary", [])
            ),
            *(
                _position_row(item, "secondary")
                for item in strategy_state.get("secondary_active", [])
            ),
        ]
    )
    main_area_count = len(main_area_codes)
    secondary_area_count = len(
        {item.code for item in secondary}
        | {
            str(item["code"])
            for item in strategy_state.get("secondary_active", [])
        }
        | pending_secondary_codes
    )
    main_pool_rows = "".join(_live_pool_row(item, "main") for item in selected)
    secondary_pool_rows = "".join(
        _live_pool_row(item, "secondary")
        for item in secondary
    )
    selected_rows = "".join(_evaluation_row(item) for item in selected)
    near_featured = near[:5]
    near_compact = near[5:]
    near_rows = "".join(_evaluation_row(item, True) for item in near_featured)
    near_compact_rows = "".join(_observation_compact_row(item) for item in near_compact)
    near_compact_section = (
        f"""<details class="panel"><summary>展开更多：其余 {len(near_compact)} 只观察标的</summary>
        <div class="table-scroll"><table><thead><tr><th>股票</th><th>价格 / 涨跌</th><th>龙腾跃虎</th><th>可能见底</th><th>连续黄柱</th><th>42日涨停</th><th>优先级</th></tr></thead>
        <tbody>{near_compact_rows}</tbody></table></div>
      </details>"""
        if near_compact
        else ""
    )
    closed_rows = "".join(_closed_row(item) for item in strategy_state["closed"][:50])
    secondary_closed_rows = "".join(
        _closed_row(item) for item in strategy_state.get("secondary_closed", [])[:50]
    )
    empty6 = '<tr><td class="empty" colspan="6">当前没有符合条件的记录</td></tr>'
    empty7 = '<tr><td class="empty" colspan="7">今日没有股票同时满足四项条件</td></tr>'
    empty8 = (
        f'<tr><td class="empty" colspan="8">当前没有满足至少 '
        f'{cfg["near_match_minimum"]} 项条件的观察标的</td></tr>'
    )
    validation_section = _validation_section()
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
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='15' fill='%231e40af'/%3E%3Cpath d='M15 43V27m11 16V18m11 25V31m11 12V12' stroke='white' stroke-width='5' stroke-linecap='round'/%3E%3C/svg%3E">
  <title>卢氏龙虎趋势池 · 结算 {trade_date}</title>
  <script>document.documentElement.classList.add("js")</script>
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
    <div class="top-actions">
      <nav class="nav" aria-label="页面导航">
        <a href="#pool">趋势池</a><a href="#signals">今日信号</a><a href="#watch">观察区</a><a href="#validation">验证</a><a href="#rules">规则</a>
      </nav>
      <button class="theme-toggle" id="theme-toggle" type="button" aria-label="切换显示模式" title="切换显示模式">
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="3.5" stroke="currentColor" stroke-width="1.8"/><path d="M12 2.8v2.1m0 14.2v2.1M2.8 12h2.1m14.2 0h2.1M5.5 5.5 7 7m10 10 1.5 1.5m0-13L17 7M7 17l-1.5 1.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      </button>
    </div>
  </header>

  <main id="content">
    <section class="cover-hero reveal" style="--cover-desktop:url('{cover_desktop}'),url('../{cover_desktop}');--cover-mobile:url('{cover_mobile}'),url('../{cover_mobile}')">
      <div class="cover-stage" aria-hidden="true">
        <video class="cover-video" data-cover-video muted loop playsinline preload="none"></video>
        <div class="cover-cinema-mask"></div>
      </div>
      <div class="cover-inner">
        <div class="cover-copy">
          <p class="cover-eyebrow">A-share risk & opportunity</p>
          <h1>有人找<span class="opportunity-word">机会</span>，<br>有人专挑<span class="risk-word">风险</span></h1>
          <p class="cover-subline">上涨为红，下跌为绿 · 先过规则，再谈机会</p>
        </div>
        <aside class="cover-live" aria-live="polite">
          <div class="cover-live-top">
            <span class="status-dot" id="status-dot" aria-hidden="true"></span>
            <strong id="market-status">收盘数据已验证</strong>
            <span class="cover-count" id="lens-value">等待行情</span>
          </div>
          <div class="status-detail" id="market-detail">交易日 {trade_date} · 云端行情自动刷新</div>
          <div class="cover-time">最新行情<strong id="quote-time">{generated}</strong></div>
          <div class="date-strip">
            <span class="date-chip">盘中行情日<strong data-live-trade-date>等待行情</strong></span>
            <span class="date-chip">收盘结算日<strong data-close-trade-date>{trade_date}</strong></span>
          </div>
        </aside>
        <p class="cover-note"><strong>机会可以等，风险必须先看。</strong>主选与次选盘中实时判断趋势；价格、收益和状态随行情更新，成功率与实现收益收盘结算。</p>
      </div>
    </section>

    <section class="live-rail reveal" aria-label="盘中行情">
      <div class="live-rail-label">跟踪行情</div>
      <div class="ticker-track" id="ticker-track"><span class="ticker-empty">正在连接最新行情…</span></div>
    </section>

    <section class="kpi-grid reveal" aria-label="核心概览">
      <article class="kpi"><span class="kpi-label">主选实时预选</span><strong class="kpi-value" data-live-main-count>{len(selected)}</strong><span class="kpi-note">严格四项同时满足</span></article>
        <article class="kpi"><span class="kpi-label">次选实时预选</span><strong class="kpi-value" data-live-secondary-count>{len(secondary)}</strong><span class="kpi-note">龙虎 + 窗口黄柱 + 另一项</span></article>
      <article class="kpi"><span class="kpi-label">主选信号监控</span><strong class="kpi-value" data-tracked-main-count>{tracked_main_count + pending_main_count}</strong><span class="kpi-note">含待确认与趋势跟踪</span></article>
      <article class="kpi"><span class="kpi-label">观察标的</span><strong class="kpi-value">{len(near)}</strong><span class="kpi-note">仅观察，不计入选</span></article>
      <article class="kpi"><span class="kpi-label">市场扫描</span><strong class="kpi-value">{scanned}</strong><span class="kpi-note">失败 {len(errors)} 只 · ST 排除</span></article>
    </section>

    <section class="section reveal" id="pool">
      <div class="section-head"><div><span class="section-kicker">Tracked portfolio</span><h2>{POOL_NAME}</h2>
      <p class="section-copy">首次入选先显示“待观察中 / 等待买入”；信号未被重算消失且10日内收盘突破此前5日最高价，才显示“趋势开始 / 建议买入”。买入后页面同步给出继续持有、谨慎持有或卖出触发，正式结束与收益只在收盘结算。</p></div></div>
{_events(events)}
{migration_note}
      <div class="pool-switcher" role="tablist" aria-label="趋势池区域切换">
        <button class="pool-tab" id="tab-main" type="button" role="tab" aria-selected="true" aria-controls="pool-main" data-pool-tab="main">主选区 · <span data-area-main-count>{main_area_count}</span></button>
        <button class="pool-tab" id="tab-secondary" type="button" role="tab" aria-selected="false" aria-controls="pool-secondary" data-pool-tab="secondary" tabindex="-1">次选区 · <span data-area-secondary-count>{secondary_area_count}</span></button>
      </div>
      <article class="panel" id="pool-main" role="tabpanel" aria-labelledby="tab-main" data-pool-panel="main">
        <div class="panel-head"><div><h3>主选区</h3><p>10日内收盘突破前5日最高价建议买入；浮盈达到3%后较最高收盘回撤2%、龙线不再高于虎线或满60日建议卖出</p>
          <div class="pool-composition"><span>盘中新信号 <strong data-live-main-count>{len(selected)}</strong> 只</span><span>实时监控 <strong data-tracked-main-count>{tracked_main_count + pending_main_count}</strong> 只</span><span>其中已确认趋势 {tracked_main_count} 只</span></div>
        </div><span class="count-badge"><span data-area-main-count>{main_area_count}</span> 只</span></div>
        <div class="pool-group-head"><strong>盘中新信号</strong><span>随最新行情重算，收盘确认后加入跟踪</span></div>
        <div class="table-scroll pool-table-shell"><table class="pool-table"><thead><tr><th>股票</th><th>最新价 / 涨跌</th><th>可能见底</th><th>龙腾跃虎</th><th>42日涨停</th><th>黄柱</th><th>状态 / 操作</th></tr></thead>
        <tbody id="live-main-body">{main_pool_rows or '<tr><td class="empty" colspan="7">当前没有符合条件的主选预选</td></tr>'}</tbody></table></div>
        <div class="pool-group-head settled"><strong>实时信号与趋势跟踪</strong><span>待确认信号看前5日突破价；确认买点后再计算策略收益</span></div>
        <div class="table-scroll pool-table-shell"><table class="pool-table"><thead><tr><th>股票</th><th>加入日 / 价格</th><th>最新价 / 时间</th><th>实时收益</th><th>时长</th><th>状态 / 操作</th></tr></thead>
        <tbody id="tracking-main-body">{active_rows or empty6}</tbody></table></div>
        <div class="live-exit-list" id="live-main-exits" hidden aria-live="polite"></div>
        <p class="settlement-note">实时收益只用于盘中判断；趋势结束后的成功率、实现收益和正式移出记录，以收盘确认结果为准。</p>
        <div class="metrics">
          {_metric('完整波段成功率', _pct(main_stats['closed_success_rate']))}
          {_metric('完整波段平均收益', _pct(main_stats['all_average_return']))}
          {_metric('等待确认', f"{pending_main_count} 只")}
          {_metric('累计实现收益', _pct(main_stats['realized_compound_return']))}
          {_metric('已移出', f"{main_stats['closed_count']} 只")}
          {_metric('完整波段样本', f"{main_stats['sample_count']} 只")}
        </div>
      </article>

      <article class="panel" id="pool-secondary" role="tabpanel" aria-labelledby="tab-secondary" data-pool-panel="secondary" hidden>
        <div class="panel-head"><div><h3>次选区</h3><p>候选需龙虎、窗口黄柱及另一项；10日内收盘突破前5日最高价才建议买入，卖点与主选一致</p>
          <div class="pool-composition"><span>盘中新信号 <strong data-live-secondary-count>{len(secondary)}</strong> 只</span><span>实时监控 <strong data-tracked-secondary-count>{tracked_secondary_count + pending_secondary_count}</strong> 只</span><span>其中已确认趋势 {tracked_secondary_count} 只</span></div>
        </div><span class="count-badge"><span data-area-secondary-count>{secondary_area_count}</span> 只</span></div>
        <div class="pool-group-head"><strong>盘中新信号</strong><span>随最新行情重算，收盘确认后加入跟踪</span></div>
        <div class="table-scroll pool-table-shell"><table class="pool-table"><thead><tr><th>股票</th><th>最新价 / 涨跌</th><th>可能见底</th><th>龙腾跃虎</th><th>42日涨停</th><th>黄柱</th><th>状态 / 操作</th></tr></thead>
        <tbody id="live-secondary-body">{secondary_pool_rows or '<tr><td class="empty" colspan="7">当前没有符合条件的次选预选</td></tr>'}</tbody></table></div>
        <div class="pool-group-head settled"><strong>实时信号与趋势跟踪</strong><span>待确认信号看前5日突破价；确认买点后再计算策略收益</span></div>
        <div class="table-scroll pool-table-shell"><table class="pool-table"><thead><tr><th>股票</th><th>加入日 / 价格</th><th>最新价 / 时间</th><th>实时收益</th><th>时长</th><th>状态 / 操作</th></tr></thead>
        <tbody id="tracking-secondary-body">{secondary_active_rows or empty6}</tbody></table></div>
        <div class="live-exit-list" id="live-secondary-exits" hidden aria-live="polite"></div>
        <p class="settlement-note">实时收益只用于盘中判断；趋势结束后的成功率、实现收益和正式移出记录，以收盘确认结果为准。</p>
        <div class="metrics">
          {_metric('完整波段成功率', _pct(secondary_stats['closed_success_rate']))}
          {_metric('完整波段平均收益', _pct(secondary_stats['all_average_return']))}
          {_metric('等待确认', f"{pending_secondary_count} 只")}
          {_metric('累计实现收益', _pct(secondary_stats['realized_compound_return']))}
          {_metric('已移出', f"{secondary_stats['closed_count']} 只")}
          {_metric('完整波段样本', f"{secondary_stats['sample_count']} 只")}
        </div>
      </article>
    </section>

    <section class="section reveal" id="signals">
      <div class="section-head"><div><span class="section-kicker">Daily selection</span><h2>最近收盘主选信号</h2>
      </div><span class="count-badge">{len(selected)} 只</span></div>
{legend}
      <div class="panel table-scroll"><table><thead><tr><th>股票</th><th>收盘 / 涨跌</th><th>近42日 K 线与龙虎线</th><th>可能见底</th><th>龙腾跃虎</th><th>42日涨停</th><th>连续黄柱</th></tr></thead>
      <tbody>{selected_rows or empty7}</tbody></table></div>
    </section>

    <section class="section reveal" id="watch">
      <div class="section-head"><div><span class="section-kicker">Watchlist</span><h2>观察区</h2>
      <p class="section-copy">满足至少 {cfg['near_match_minimum']} 项的接近标的，仅用于观察，不纳入主选或次选收益。默认展示优先级最高的 {len(near_featured)} 只完整走势图，其余可展开查看。</p></div><span class="count-badge">{len(near)} 只</span></div>
{legend}
      <div class="panel table-scroll"><table><thead><tr><th>股票</th><th>价格 / 涨跌</th><th>近42日 K 线与龙虎线</th><th>龙腾跃虎</th><th>可能见底</th><th>连续黄柱</th><th>42日涨停</th><th>优先级</th></tr></thead>
      <tbody>{near_rows or empty8}</tbody></table></div>
      {near_compact_section}
    </section>

    <section class="section reveal" id="rules">
      <div class="section-head"><div><span class="section-kicker">Methodology</span><h2>筛选规则</h2></div></div>
      <div class="rules">
        <article class="rule"><span class="rule-num">01</span><strong>可能见底</strong><p>最近 {cfg['bottom_lookback_days']} 个交易日出现信号。</p></article>
        <article class="rule"><span class="rule-num">02</span><strong>龙腾跃虎</strong><p>交叉显示窗口用于完成黄柱配对，不是卖出倒计时。自然到期不退出；应显示期间被后续K线重算掉，才视为短暂信号失效。</p></article>
        <article class="rule"><span class="rule-num">03</span><strong>近期涨停</strong><p>最近 {cfg['limit_up_lookback_days']} 个交易日至少一次收盘涨停。</p></article>
        <article class="rule"><span class="rule-num">04</span><strong>窗口黄柱</strong><p>龙腾跃虎日前 {cfg.get('yellow_before_cross_days', 2)} 日至后 {cfg.get('yellow_after_cross_days', 2)} 个交易日内出现黄柱即可配对；当前至少 {cfg['yellow_consecutive_days']} 根。</p></article>
        <article class="rule"><span class="rule-num">05</span><strong>建议买入</strong><p>入选后第1—10个交易日，信号仍有效且收盘严格突破此前5日最高价；盘中突破只提示等待收盘确认。</p></article>
        <article class="rule"><span class="rule-num">06</span><strong>建议卖出</strong><p>浮盈曾达到3%后较最高收盘回撤2%，或龙线不再高于虎线，或完成60个后续交易日；盘中触发不提前结算。</p></article>
      </div>
    </section>

{validation_section}

    <section class="section reveal">
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
<nav class="mobile-dock" aria-label="手机快捷导航">
  <a href="#content"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 19V10l8-6 8 6v9H4Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M9.5 19v-5h5v5" stroke="currentColor" stroke-width="1.8"/></svg><span>概览</span></a>
  <a href="#pool"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 17l5-5 4 3 7-8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M16 7h4v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><span>趋势池</span></a>
  <a href="#signals"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.8"/><path d="M12 7v5l3 2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><span>信号</span></a>
  <a href="#rules"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M6 4h12v16H6z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M9 8h6m-6 4h6m-6 4h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><span>规则</span></a>
</nav>
<script>{LIVE_SCRIPT}</script>
</body>
</html>"""
