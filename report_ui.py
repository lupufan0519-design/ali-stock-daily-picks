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

/* Cinematic opening scene: market candles break through a storm front. */
.cinema-hero {
  --coverage-angle: 0deg;
  position: relative;
  isolation: isolate;
  overflow: hidden;
  width: calc(100% + 48px);
  min-height: clamp(620px, calc(100svh - 64px), 790px);
  margin-left: -24px;
  color: #f7fbff;
  background: #07182a;
}
.cinema-hero::before {
  content: "";
  position: absolute;
  z-index: 1;
  inset: 0;
  background:
    linear-gradient(90deg, rgba(3,16,30,.48) 0, rgba(3,16,30,.06) 46%, rgba(3,16,30,.08) 70%, rgba(3,16,30,.34) 100%),
    linear-gradient(180deg, rgba(1,14,27,.08) 0, transparent 46%, rgba(1,10,20,.5) 100%);
  pointer-events: none;
}
.cinema-hero::after {
  content: "";
  position: absolute;
  z-index: 2;
  right: 0;
  bottom: 0;
  left: 0;
  height: 38%;
  background: linear-gradient(180deg, transparent, rgba(2,10,20,.28));
  pointer-events: none;
}
.cinema-scene {
  position: absolute;
  z-index: 0;
  inset: 0;
  width: 100%;
  height: 100%;
}
.cinema-cloud-far { animation: cloud-drift-far 32s ease-in-out infinite alternate; transform-origin: center; }
.cinema-cloud-near { animation: cloud-drift-near 24s ease-in-out infinite alternate; transform-origin: center; }
.cloud-textured { filter: url(#cloudRough); }
@keyframes cloud-drift-far { to { transform: translate3d(18px,-4px,0) scale(1.015); } }
@keyframes cloud-drift-near { to { transform: translate3d(-22px,6px,0) scale(1.018); } }
.cinema-trend-glow {
  fill: none;
  stroke: rgba(255,255,255,.32);
  stroke-width: 2;
  stroke-linejoin: round;
  filter: url(#candleGlow);
  stroke-dasharray: 2200;
  stroke-dashoffset: 2200;
  animation: trend-reveal 3.4s .2s cubic-bezier(.2,.75,.2,1) forwards;
}
@keyframes trend-reveal { to { stroke-dashoffset: 0; } }
.cinema-candle {
  opacity: 0;
  transform: translateY(18px);
  transform-box: fill-box;
  transform-origin: center;
  animation: candle-arrive 440ms cubic-bezier(.2,.8,.2,1) forwards;
  animation-delay: calc(300ms + var(--candle-index) * 55ms);
}
@keyframes candle-arrive { to { opacity: 1; transform: translateY(0); } }
.cinema-candle line { stroke-width: 2.2; stroke-linecap: round; }
.cinema-candle.up line, .cinema-candle.up rect { stroke: #ff5a5f; fill: #ff5a5f; }
.cinema-candle.down line, .cinema-candle.down rect { stroke: #2ec4a6; fill: #2ec4a6; }
.market-pulse { fill: #fff4d5; filter: url(#pulseGlow); }
.cinema-inner {
  position: relative;
  z-index: 3;
  width: min(1440px, 100%);
  min-height: inherit;
  margin: 0 auto;
  padding: clamp(64px, 9vh, 100px) clamp(24px, 5vw, 72px);
}
.cinema-copy { width: min(620px, 58vw); }
.cinema-hero .eyebrow {
  margin-bottom: 18px;
  color: #c8e8ff;
  text-shadow: 0 2px 20px rgba(0,0,0,.36);
}
.cinema-hero h1 {
  max-width: 640px;
  color: #f8fbff;
  font-family: "FZLanTingHeiS-UL-GB", "STSong", "Songti SC", "Microsoft YaHei", sans-serif;
  font-size: clamp(58px, 6.4vw, 96px);
  font-weight: 500;
  line-height: .98;
  letter-spacing: -.055em;
  text-shadow: 0 8px 36px rgba(0,10,22,.42);
}
.cinema-hero .opportunity-word { color: #e8f5ff; }
.cinema-hero .risk-word { color: #fff; }
.cinema-hero .risk-word::after { height: 2px; bottom: -.06em; background: #ff6569; opacity: .9; }
.cinema-kicker {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  margin-top: 28px;
  color: rgba(235,247,255,.78);
  font-size: 14px;
  letter-spacing: .08em;
}
.cinema-kicker::before { content: ""; width: 32px; height: 1px; background: #ff6569; }
.cinema-live-card {
  position: absolute;
  top: clamp(54px, 8vh, 82px);
  right: clamp(24px, 5vw, 72px);
  width: min(330px, 34vw);
  padding: 17px 18px;
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 16px;
  background: rgba(5,25,43,.42);
  box-shadow: 0 18px 50px rgba(0,10,22,.18);
  backdrop-filter: blur(14px);
}
.cinema-live-top { display: flex; align-items: center; gap: 10px; }
.cinema-live-top strong { flex: 1; min-width: 0; font-size: 14px; }
.cinema-coverage {
  flex: 0 0 auto;
  min-width: 54px;
  padding: 3px 8px;
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 999px;
  color: #d8ecf7;
  font: 650 11px/1.5 ui-monospace, Consolas, monospace;
  text-align: center;
}
.cinema-live-card .status-dot { margin-top: 0; background: #66e1b2; box-shadow: 0 0 0 4px rgba(102,225,178,.13); }
.cinema-live-card .status-dot.stale { background: #f2c572; box-shadow: 0 0 0 4px rgba(242,197,114,.13); }
.cinema-live-card .status-dot.error { background: #ff8a80; box-shadow: 0 0 0 4px rgba(255,138,128,.13); }
.cinema-live-card .status-detail { margin-top: 7px; color: rgba(220,238,248,.7); font-size: 12px; }
.cinema-time { margin-top: 10px; color: rgba(188,216,231,.64); font-size: 11px; }
.cinema-time strong { margin-left: 8px; color: #f2f8fb; font: 650 12px/1.4 ui-monospace, Consolas, monospace; }
.cinema-risk-note {
  position: absolute;
  right: clamp(24px, 7vw, 100px);
  bottom: clamp(58px, 8vh, 82px);
  width: min(430px, 40vw);
  margin: 0;
  color: rgba(243,249,252,.92);
  font-size: clamp(15px, 1.35vw, 19px);
  line-height: 1.7;
  text-align: right;
  text-shadow: 0 3px 18px rgba(0,0,0,.8);
}
.cinema-risk-note strong { display: block; color: #fff; font-weight: 650; }
.cinema-scroll {
  position: absolute;
  bottom: clamp(48px, 7vh, 70px);
  left: clamp(24px, 5vw, 72px);
  display: flex;
  align-items: center;
  gap: 10px;
  color: rgba(223,239,248,.62);
  font-size: 11px;
  letter-spacing: .16em;
  text-transform: uppercase;
}
.cinema-scroll i { position: relative; width: 42px; height: 1px; overflow: hidden; background: rgba(255,255,255,.22); }
.cinema-scroll i::after {
  content: "";
  position: absolute;
  inset: 0;
  background: #fff;
  transform: translateX(-100%);
  animation: scroll-line 1.2s .8s ease-out 1 forwards;
}
@keyframes scroll-line { to { transform: translateX(100%); } }
.cinema-hero + .live-rail { margin-top: 20px; }
@media (max-width: 900px) {
  .cinema-copy { width: min(560px, 64vw); }
  .cinema-live-card { top: 310px; width: min(300px, 38vw); }
  .cinema-risk-note { width: 48vw; }
}
@media (max-width: 760px) {
  .cinema-hero { min-height: 690px; }
  .cinema-hero { width: calc(100% + 32px); margin-left: -16px; }
  .cinema-inner { padding: 48px 20px; }
  .cinema-copy { width: 100%; }
  .cinema-hero h1 { width: 100%; max-width: 390px; font-size: clamp(50px, 14vw, 64px); line-height: 1.02; }
  .cinema-kicker { margin-top: 18px; font-size: 12px; }
  .cinema-live-card {
    top: 265px;
    right: 16px;
    left: 16px;
    width: auto;
    padding: 14px 15px;
    background: rgba(5,25,43,.48);
  }
  .cinema-risk-note {
    right: 20px;
    bottom: 54px;
    width: min(310px, 84vw);
    font-size: 14px;
  }
  .cinema-scroll { display: none; }
  .cinema-scene { width: 150%; max-width: none; transform: translateX(-23%); }
  .cloud-textured { filter: none; }
  .cinema-hero + .live-rail { margin-top: 14px; }
}
@media (max-width: 430px) {
  .cinema-hero { min-height: 660px; }
  .cinema-hero .eyebrow { font-size: 11px; }
  .cinema-hero h1 { font-size: clamp(46px, 13.8vw, 58px); }
  .cinema-live-card { top: 250px; }
  .cinema-risk-note { bottom: 42px; }
}
@media (prefers-reduced-motion: reduce) {
  .risk-orbit::after { animation: none; }
  html.js .reveal, html.js .reveal.is-visible { opacity: 1; transform: none; }
  .quote-updated { animation: none; }
  .cinema-cloud-far, .cinema-cloud-near, .cinema-trend-glow,
  .cinema-candle, .cinema-scroll i::after { animation: none; }
  .cinema-trend-glow { stroke-dashoffset: 0; }
  .cinema-candle { opacity: 1; transform: none; }
  .market-pulse { display: none; }
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

  const status = document.querySelector("#market-status");
  const detail = document.querySelector("#market-detail");
  const quoteTime = document.querySelector("#quote-time");
  const dot = document.querySelector("#status-dot");
  const lensValue = document.querySelector("#lens-value");
  const riskStage = document.querySelector(".risk-stage, .cinema-hero");
  const ticker = document.querySelector("#ticker-track");
  const formatPct = (value) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
  const setTone = (element, value) => {
    element.classList.toggle("positive", value >= 0);
    element.classList.toggle("negative", value < 0);
  };
  const quoteHref = (quote) => {
    const prefix = Number(quote.market) === 1 ? "sh" : Number(quote.market) === 0 ? "sz" : "bj";
    return `https://quote.eastmoney.com/${prefix}${quote.code}.html`;
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
      detail.textContent = data.note || "盘中行情只更新价格，不改变收盘筛选信号";
      quoteTime.textContent = data.generated_at_display || data.generated_at;
      dot.className = `status-dot ${data.is_stale ? "stale" : ""}`;
      const targetCount = Number(data.target_count || 0);
      const quoteCount = Number(data.quote_count || 0);
      const coverage = targetCount ? Math.min(1, quoteCount / targetCount) : 1;
      if (lensValue) lensValue.textContent = targetCount ? `${quoteCount}/${targetCount}` : "已就绪";
      if (riskStage) riskStage.style.setProperty("--coverage-angle", `${coverage * 360}deg`);
      paintTicker(data.quotes || {});
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


def _hero_candles_svg() -> str:
    closes = [
        550, 558, 568, 577, 590, 604, 618, 634, 648, 662, 650, 636,
        616, 588, 556, 522, 490, 456, 420, 386, 352, 318, 286, 252,
        220, 190, 160, 132, 106, 82, 62, 46,
    ]
    rising = [
        False, True, False, False, True, False, False, True,
        False, False, True, True, True, True, False, True,
        True, True, False, True, True, True, False, True,
        True, True, True, False, True, True, True, True,
    ]
    parts = []
    points = []
    for index, (close_y, is_up) in enumerate(zip(closes, rising)):
        x = 96 + index * 46
        open_y = close_y + (18 if is_up else -14)
        high_y = min(open_y, close_y) - (9 + index % 5)
        low_y = max(open_y, close_y) + (10 + (index * 3) % 6)
        y = min(open_y, close_y)
        height = max(5, abs(open_y - close_y))
        tone = "up" if is_up else "down"
        parts.append(
            f'<g class="cinema-candle {tone}" style="--candle-index:{index}">'
            f'<line x1="{x}" y1="{high_y}" x2="{x}" y2="{low_y}"/>'
            f'<rect x="{x - 5}" y="{y}" width="10" height="{height}" rx="1.5"/>'
            "</g>"
        )
        points.append(f"{x},{close_y}")
    return (
        f'<polyline class="cinema-trend-glow" points="{" ".join(points)}"/>'
        f'{"".join(parts)}'
        '<circle class="market-pulse" r="8">'
        '<animateMotion dur="8s" repeatCount="indefinite" '
        f'path="M {" L ".join(points)}"/></circle>'
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
        <a href="#pool">趋势池</a><a href="#signals">今日信号</a><a href="#watch">观察区</a><a href="#rules">规则</a>
      </nav>
      <button class="theme-toggle" id="theme-toggle" type="button" aria-label="切换显示模式" title="切换显示模式">
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="3.5" stroke="currentColor" stroke-width="1.8"/><path d="M12 2.8v2.1m0 14.2v2.1M2.8 12h2.1m14.2 0h2.1M5.5 5.5 7 7m10 10 1.5 1.5m0-13L17 7M7 17l-1.5 1.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      </button>
    </div>
  </header>

  <main id="content">
    <section class="cinema-hero reveal">
      <svg class="cinema-scene" viewBox="0 0 1600 820" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <defs>
          <linearGradient id="skyField" x1="0" y1="1" x2=".82" y2="0">
            <stop offset="0" stop-color="#081a2c"/><stop offset=".42" stop-color="#16507b"/>
            <stop offset=".76" stop-color="#278fc9"/><stop offset="1" stop-color="#8ed8f4"/>
          </linearGradient>
          <radialGradient id="skyGlow"><stop offset="0" stop-color="#fff" stop-opacity=".82"/><stop offset=".35" stop-color="#dff5ff" stop-opacity=".34"/><stop offset="1" stop-color="#b5e6ff" stop-opacity="0"/></radialGradient>
          <linearGradient id="cloudFace" x1=".45" y1="0" x2=".5" y2="1">
            <stop offset="0" stop-color="#f4fbff"/><stop offset=".43" stop-color="#c6d8e3"/><stop offset="1" stop-color="#62788b"/>
          </linearGradient>
          <linearGradient id="stormFace" x1=".5" y1="0" x2=".5" y2="1">
            <stop offset="0" stop-color="#41586c"/><stop offset=".34" stop-color="#1d3448"/><stop offset="1" stop-color="#071523"/>
          </linearGradient>
          <linearGradient id="cloudEdge" x1="0" y1=".2" x2="1" y2=".8">
            <stop offset="0" stop-color="#e9f5fa"/><stop offset=".55" stop-color="#849bac"/><stop offset="1" stop-color="#2a4155"/>
          </linearGradient>
          <filter id="softCloud" x="-20%" y="-30%" width="140%" height="170%">
            <feGaussianBlur stdDeviation="4"/>
          </filter>
          <filter id="cloudRough" x="-15%" y="-20%" width="130%" height="145%">
            <feTurbulence type="fractalNoise" baseFrequency=".007 .018" numOctaves="3" seed="11" result="noise"/>
            <feDisplacementMap in="SourceGraphic" in2="noise" scale="20" xChannelSelector="R" yChannelSelector="B"/>
            <feGaussianBlur stdDeviation=".8"/>
          </filter>
          <filter id="candleGlow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="6" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <filter id="pulseGlow" x="-400%" y="-400%" width="800%" height="800%">
            <feGaussianBlur stdDeviation="10" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <pattern id="cityLights" width="38" height="22" patternUnits="userSpaceOnUse">
            <circle cx="7" cy="8" r="1.2" fill="#82c8e9" opacity=".75"/><circle cx="28" cy="16" r=".8" fill="#ffd99b" opacity=".58"/>
          </pattern>
        </defs>
        <rect width="1600" height="820" fill="url(#skyField)"/>
        <ellipse cx="1250" cy="72" rx="420" ry="260" fill="url(#skyGlow)"/>
        <g class="cinema-cloud-far">
          <path d="M0 186C154 117 307 170 424 208c128 42 226-60 359-18 124 39 219 25 332-19 154-61 337-32 485 37v166H0Z" fill="#e5f5fc" opacity=".19" filter="url(#softCloud)"/>
          <g class="cloud-textured" fill="#eff9fd" opacity=".72">
            <ellipse cx="132" cy="298" rx="155" ry="74"/><ellipse cx="278" cy="276" rx="126" ry="98"/>
            <ellipse cx="424" cy="312" rx="190" ry="78"/><ellipse cx="594" cy="277" rx="132" ry="100"/>
            <ellipse cx="742" cy="302" rx="186" ry="83"/><ellipse cx="917" cy="274" rx="145" ry="110"/>
            <ellipse cx="1084" cy="308" rx="204" ry="86"/><ellipse cx="1270" cy="272" rx="150" ry="106"/>
            <ellipse cx="1454" cy="304" rx="205" ry="94"/>
          </g>
          <path d="M0 333c191-85 295 1 464-22 150-20 244-93 403-28 151 61 285-35 425-16 114 16 215 48 308 82v160H0Z" fill="url(#cloudFace)"/>
          <g class="cloud-textured" fill="url(#cloudEdge)" opacity=".92">
            <ellipse cx="68" cy="394" rx="151" ry="77"/><ellipse cx="229" cy="364" rx="128" ry="93"/>
            <ellipse cx="388" cy="397" rx="174" ry="82"/><ellipse cx="558" cy="359" rx="144" ry="111"/>
            <ellipse cx="744" cy="397" rx="185" ry="92"/><ellipse cx="925" cy="353" rx="150" ry="116"/>
            <ellipse cx="1116" cy="397" rx="195" ry="91"/><ellipse cx="1302" cy="356" rx="154" ry="113"/>
            <ellipse cx="1510" cy="394" rx="196" ry="96"/>
          </g>
        </g>
        <g class="cinema-cloud-near">
          <path d="M0 450c119-49 251-72 372-20 94 40 174 36 272-13 126-63 245 2 347 22 122 23 233-51 361-21 100 23 176 60 248 82v320H0Z" fill="url(#stormFace)"/>
          <g class="cloud-textured" fill="#1c3347" opacity=".95">
            <ellipse cx="87" cy="492" rx="181" ry="96"/><ellipse cx="270" cy="478" rx="147" ry="112"/>
            <ellipse cx="447" cy="512" rx="193" ry="100"/><ellipse cx="632" cy="474" rx="156" ry="118"/>
            <ellipse cx="830" cy="516" rx="202" ry="102"/><ellipse cx="1025" cy="474" rx="162" ry="120"/>
            <ellipse cx="1236" cy="510" rx="209" ry="104"/><ellipse cx="1453" cy="476" rx="182" ry="118"/>
          </g>
          <path d="M0 560c182-38 302 48 458 16 152-30 229-75 378-33 163 45 270-22 409-22 128 1 244 54 355 83v216H0Z" fill="#06131f" opacity=".88"/>
        </g>
        <g opacity=".72">
          <path d="M0 742h90v-34h46v34h58v-61h44v61h82v-27h36v27h66v-83h55v83h73v-48h43v48h90v-97h60v97h68v-40h45v40h93v-65h56v65h72v-35h42v35h76v-90h54v90h82v-53h44v53h92v78H0Z" fill="#020a12"/>
          <rect y="650" width="1600" height="170" fill="url(#cityLights)" opacity=".5"/>
        </g>
        <g>{_hero_candles_svg()}</g>
      </svg>
      <div class="cinema-inner">
        <div class="cinema-copy">
          <p class="eyebrow">A-share risk & opportunity</p>
          <h1>有人找<span class="opportunity-word">机会</span>，<br>有人专挑<span class="risk-word">风险</span></h1>
          <p class="cinema-kicker">先过规则，再谈机会</p>
        </div>
        <aside class="cinema-live-card" aria-live="polite">
          <div class="cinema-live-top">
            <span class="status-dot" id="status-dot" aria-hidden="true"></span>
            <strong id="market-status">收盘数据已验证</strong>
            <span class="cinema-coverage" id="lens-value">等待行情</span>
          </div>
          <div class="status-detail" id="market-detail">交易日 {trade_date} · 云端行情自动刷新</div>
          <div class="cinema-time">最新行情<strong id="quote-time">{generated}</strong></div>
        </aside>
        <p class="cinema-risk-note"><strong>机会可以等，风险必须先看。</strong>主选与次选只在收盘后确认，盘中变化不替你提前做决定。</p>
        <div class="cinema-scroll" aria-hidden="true"><i></i>Scroll to signals</div>
      </div>
    </section>

    <section class="live-rail reveal" aria-label="盘中行情">
      <div class="live-rail-label">跟踪行情</div>
      <div class="ticker-track" id="ticker-track"><span class="ticker-empty">正在连接最新行情…</span></div>
    </section>

    <section class="kpi-grid reveal" aria-label="核心概览">
      <article class="kpi"><span class="kpi-label">主选跟踪</span><strong class="kpi-value">{main_stats['active_count']}</strong><span class="kpi-note">严格四项同时满足</span></article>
      <article class="kpi"><span class="kpi-label">次选跟踪</span><strong class="kpi-value">{secondary_stats['active_count']}</strong><span class="kpi-note">龙虎 + 黄柱 + 另一项</span></article>
      <article class="kpi"><span class="kpi-label">今日严格命中</span><strong class="kpi-value">{len(selected)}</strong><span class="kpi-note">eligible=true</span></article>
      <article class="kpi"><span class="kpi-label">观察标的</span><strong class="kpi-value">{len(near)}</strong><span class="kpi-note">仅观察，不计入选</span></article>
      <article class="kpi"><span class="kpi-label">市场扫描</span><strong class="kpi-value">{scanned}</strong><span class="kpi-note">失败 {len(errors)} 只 · ST 排除</span></article>
    </section>

    <section class="section reveal" id="pool">
      <div class="section-head"><div><span class="section-kicker">Tracked portfolio</span><h2>{POOL_NAME}</h2>
      <p class="section-copy">加入日收盘价作为基准，盘中收益由最新行情计算；策略状态只在收盘完整扫描后变化。</p></div></div>
{_events(events)}
      <div class="pool-switcher" role="tablist" aria-label="趋势池区域切换">
        <button class="pool-tab" id="tab-main" type="button" role="tab" aria-selected="true" aria-controls="pool-main" data-pool-tab="main">主选区 · {main_stats['active_count']}</button>
        <button class="pool-tab" id="tab-secondary" type="button" role="tab" aria-selected="false" aria-controls="pool-secondary" data-pool-tab="secondary" tabindex="-1">次选区 · {secondary_stats['active_count']}</button>
      </div>
      <article class="panel" id="pool-main" role="tabpanel" aria-labelledby="tab-main" data-pool-panel="main">
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

      <article class="panel" id="pool-secondary" role="tabpanel" aria-labelledby="tab-secondary" data-pool-panel="secondary" hidden>
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

    <section class="section reveal" id="signals">
      <div class="section-head"><div><span class="section-kicker">Daily selection</span><h2>今日严格入选</h2>
      </div><span class="count-badge">{len(selected)} 只</span></div>
{legend}
      <div class="panel table-scroll"><table><thead><tr><th>股票</th><th>收盘 / 涨跌</th><th>近42日 K 线与龙虎线</th><th>可能见底</th><th>龙腾跃虎</th><th>42日涨停</th><th>连续黄柱</th></tr></thead>
      <tbody>{selected_rows or empty7}</tbody></table></div>
    </section>

    <section class="section reveal" id="watch">
      <div class="section-head"><div><span class="section-kicker">Watchlist</span><h2>观察区</h2>
      <p class="section-copy">满足至少三项的接近标的，仅用于观察，不纳入主选或次选收益。</p></div><span class="count-badge">{len(near)} 只</span></div>
{legend}
      <div class="panel table-scroll"><table><thead><tr><th>股票</th><th>价格 / 涨跌</th><th>近42日 K 线与龙虎线</th><th>龙腾跃虎</th><th>可能见底</th><th>连续黄柱</th><th>42日涨停</th><th>优先级</th></tr></thead>
      <tbody>{near_rows or empty8}</tbody></table></div>
    </section>

    <section class="section reveal" id="rules">
      <div class="section-head"><div><span class="section-kicker">Methodology</span><h2>筛选规则</h2></div></div>
      <div class="rules">
        <article class="rule"><span class="rule-num">01</span><strong>可能见底</strong><p>最近 {cfg['bottom_lookback_days']} 个交易日出现信号。</p></article>
        <article class="rule"><span class="rule-num">02</span><strong>龙腾跃虎</strong><p>最近 {cfg['cross_lookback_days']} 日出现交叉，且龙线仍在虎线上方。</p></article>
        <article class="rule"><span class="rule-num">03</span><strong>近期涨停</strong><p>最近 {cfg['limit_up_lookback_days']} 个交易日至少一次收盘涨停。</p></article>
        <article class="rule"><span class="rule-num">04</span><strong>连续黄柱</strong><p>实体在龙线下方的部分呈黄色，连续至少 {cfg['yellow_consecutive_days']} 日。</p></article>
      </div>
    </section>

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
