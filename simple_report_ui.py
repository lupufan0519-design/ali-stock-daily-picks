from __future__ import annotations

import html
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from selection_history import empty_history, load_history
from simple_strategy import FIRST_TIER, SECOND_TIER, THIRD_TIER, split_tiers


ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "results" / "history.json"


STYLES = r"""
:root {
  color-scheme: light;
  --safe-top: env(safe-area-inset-top, 0px);
  --topbar-height: calc(72px + var(--safe-top));
  --paper: #f4f4ef;
  --surface: #ffffff;
  --ink: #14171c;
  --muted: #6b7280;
  --line: #d9dcd7;
  --red: #c83d34;
  --red-soft: #f7e5e2;
  --blue: #315da8;
  --blue-soft: #e7edf8;
  --yellow: #c99a24;
  --yellow-soft: #f5edcf;
  --green: #177b55;
  --shadow: 0 18px 44px rgba(20, 23, 28, .08);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  min-width: 320px;
  background: var(--paper);
  color: var(--ink);
  font-family: "IBM Plex Sans SC", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
}
button, a { font: inherit; }
button { color: inherit; }
a { color: inherit; }
.shell { width: min(1120px, calc(100% - 40px)); margin: 0 auto; }
.topbar {
  position: sticky;
  z-index: 40;
  top: 0;
  padding-top: var(--safe-top);
  border-bottom: 1px solid rgba(20, 23, 28, .1);
  background: rgba(244, 244, 239, .94);
  backdrop-filter: blur(18px);
}
.topbar-inner {
  min-height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}
.brand { display: flex; align-items: center; gap: 12px; font-weight: 750; letter-spacing: -.02em; }
.brand-mark {
  position: relative;
  width: 34px;
  height: 34px;
  border: 1px solid var(--ink);
  border-radius: 50%;
}
.brand-mark::before, .brand-mark::after {
  content: "";
  position: absolute;
  top: 7px;
  bottom: 7px;
  width: 2px;
}
.brand-mark::before { left: 12px; background: var(--red); }
.brand-mark::after { right: 12px; background: var(--blue); }
.market-state { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 13px; }
.market-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 5px rgba(23,123,85,.1); }
.selection-notice { margin: 0 0 22px; padding: 16px 18px; border-left: 4px solid var(--yellow); background: var(--yellow-soft); color: var(--ink); border-radius: 4px 12px 12px 4px; }
.selection-notice[hidden] { display: none; }
.selection-notice strong { display: block; margin-bottom: 6px; }
.selection-notice p { margin: 0; font-size: 13px; line-height: 1.65; overflow-wrap: anywhere; }
.data-provenance { display: flex; flex-wrap: wrap; gap: 5px 20px; margin: 14px 0 20px; font-size: 12px; color: var(--muted); line-height: 1.6; }
.history-group.corrected { margin-top: 20px; padding-top: 20px; border-top: 1px dashed var(--yellow); }
.history-group.corrected h3::before { border-radius: 2px; background: var(--yellow); }
.history-group.corrected .removal-status { max-width: 250px; }
.view-dock {
  position: sticky;
  z-index: 30;
  top: var(--topbar-height);
  padding: 12px 0 10px;
  border-bottom: 1px solid rgba(20, 23, 28, .06);
  background: linear-gradient(180deg, rgba(244,244,239,.96) 0%, rgba(244,244,239,.88) 76%, rgba(244,244,239,.72) 100%);
  backdrop-filter: blur(18px) saturate(1.08);
  -webkit-backdrop-filter: blur(18px) saturate(1.08);
}
.view-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  width: min(420px, 100%);
  margin: 0 auto;
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: rgba(255,255,255,.72);
  box-shadow: 0 8px 28px rgba(20,23,28,.08);
}
.view-button {
  min-height: 48px;
  border: 0;
  border-radius: 12px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-weight: 700;
  touch-action: manipulation;
  transition: background .2s ease, color .2s ease, box-shadow .2s ease;
}
.view-button:hover { color: var(--ink); background: rgba(255,255,255,.58); }
.view-button:active { background: rgba(20,23,28,.06); }
.view-button[aria-selected="true"] { color: var(--ink); background: var(--surface); box-shadow: 0 4px 16px rgba(20,23,28,.08); }
.view-button:focus-visible, .calendar-nav:focus-visible, .calendar-day:focus-visible, .stock-link:focus-visible { outline: 3px solid rgba(49,93,168,.28); outline-offset: 2px; }
main { padding: 18px 0 80px; }
.view-panel { animation: panel-in .28s ease both; }
.view-panel[hidden] { display: none; }
@keyframes panel-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.day-head {
  display: grid;
  grid-template-columns: 190px 1fr auto;
  align-items: end;
  gap: 30px;
  padding: 48px 0 34px;
  border-bottom: 1px solid var(--ink);
}
.date-seal { display: flex; align-items: baseline; gap: 12px; font-family: "SFMono-Regular", Consolas, monospace; }
.date-day { font-size: clamp(72px, 10vw, 128px); line-height: .76; letter-spacing: -.09em; }
.date-month { font-size: 14px; color: var(--muted); line-height: 1.45; }
.eyebrow { margin: 0 0 10px; color: var(--blue); font-size: 12px; font-weight: 800; letter-spacing: .16em; text-transform: uppercase; }
h1, h2, h3, p { margin-top: 0; }
h1 { margin-bottom: 8px; font-family: "Noto Serif SC", "Songti SC", serif; font-size: clamp(32px, 5vw, 58px); line-height: 1.06; letter-spacing: -.045em; font-weight: 760; }
.intro { max-width: 580px; margin-bottom: 0; color: var(--muted); line-height: 1.75; }
.today-total { text-align: right; font-family: "SFMono-Regular", Consolas, monospace; }
.today-total strong { display: block; font-size: 38px; line-height: 1; }
.today-total span { color: var(--muted); font-size: 12px; }
.sort-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px 24px; padding: 18px 0; border-bottom: 1px solid var(--line); }
.sort-controls { display: flex; align-items: center; gap: 10px; min-width: 0; }
.sort-label { flex-shrink: 0; font-size: 13px; font-weight: 700; }
.sort-select, .sort-direction { min-height: 44px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); color: var(--ink); font: inherit; font-size: 13px; }
.sort-select { min-width: 0; width: 210px; padding: 9px 10px; cursor: pointer; }
.sort-direction { flex-shrink: 0; padding: 9px 12px; cursor: pointer; touch-action: manipulation; }
.sort-direction:hover { border-color: var(--blue); background: var(--blue-soft); }
.sort-select:focus-visible, .sort-direction:focus-visible { outline: 3px solid rgba(49,93,168,.28); outline-offset: 2px; }
.sort-hint { margin: 0; color: var(--muted); font-size: 11px; line-height: 1.6; }
.tier-section { padding: 38px 0 12px; }
.tier-title-row { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 16px; }
.tier-kicker { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; color: var(--muted); font-size: 12px; font-weight: 750; letter-spacing: .1em; }
.tier-index { display: inline-grid; place-items: center; min-width: 30px; height: 22px; border: 1px solid currentColor; border-radius: 99px; font-family: Consolas, monospace; letter-spacing: 0; }
.tier-section.first .tier-kicker { color: var(--red); }
.tier-section.second .tier-kicker { color: var(--blue); }
.tier-section.third .tier-kicker { color: var(--yellow); }
.tier-title-row h2 { margin-bottom: 0; font-size: clamp(24px, 3vw, 34px); letter-spacing: -.035em; }
.tier-rule { max-width: 460px; margin: 0; color: var(--muted); font-size: 13px; text-align: right; }
.pick-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.pick-card {
  position: relative;
  overflow: hidden;
  min-height: 174px;
  padding: 22px 22px 18px 30px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: var(--surface);
  box-shadow: 0 8px 26px rgba(20,23,28,.035);
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
}
.pick-card:hover { transform: translateY(-2px); border-color: #bcc1ba; box-shadow: var(--shadow); }
.line-rail { position: absolute; inset: 18px auto 18px 12px; width: 8px; }
.line-rail i { position: absolute; top: 0; bottom: 0; width: 2px; border-radius: 2px; }
.line-rail i:nth-child(1) { left: 0; background: var(--red); }
.line-rail i:nth-child(2) { left: 3px; background: var(--blue); }
.line-rail i:nth-child(3) { left: 6px; background: var(--yellow); }
.pick-card.first .line-rail i:nth-child(3) { display: none; }
.pick-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.stock-link { text-decoration: none; }
.stock-name { display: block; font-size: 20px; font-weight: 780; letter-spacing: -.025em; }
.stock-code { display: block; margin-top: 4px; color: var(--muted); font-family: Consolas, monospace; font-size: 12px; }
.price { text-align: right; font-family: Consolas, monospace; }
.price strong { display: block; font-size: 22px; }
.change { font-size: 12px; }
.positive { color: var(--red); }
.negative { color: var(--green); }
.neutral { color: var(--muted); }
.reason { margin: 16px 0 13px; color: #373c44; font-size: 13px; line-height: 1.65; }
.financial-summary { margin: 0 0 16px; }
.financial-heading { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 4px 12px; margin-bottom: 8px; font-size: 11px; line-height: 1.5; }
.financial-period { color: var(--muted); }
.financial-source { color: var(--blue); text-decoration: underline; text-decoration-color: #c3cfe3; text-underline-offset: 3px; }
.financial-source:hover { text-decoration-color: currentColor; }
.financial-source:focus-visible, .financial-note summary:focus-visible { outline: 3px solid rgba(49,93,168,.28); outline-offset: 3px; border-radius: 3px; }
.financial-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; border: 1px solid #e2e4df; border-radius: 10px; background: #f8f8f5; overflow: hidden; }
.financial-cell { min-width: 0; display: flex; flex-direction: column; justify-content: space-between; padding: 10px 12px; }
.financial-cell:nth-child(even) { border-left: 1px solid #e2e4df; }
.financial-cell:nth-child(n+3) { border-top: 1px solid #e2e4df; }
.financial-label { margin: 0; color: #555b63; font-size: 11px; line-height: 1.5; }
.financial-value { margin: 5px 0 0; font: 700 20px/1.2 Consolas, monospace; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.financial-value.unavailable { font-family: inherit; font-size: 15px; font-weight: 500; }
.financial-value.cash-ratio { color: var(--ink); }
.financial-value.cash-ratio.unavailable { color: var(--muted); }
.financial-note { margin-top: 7px; color: var(--muted); font-size: 11px; line-height: 1.65; }
.financial-note summary { width: fit-content; max-width: 100%; cursor: pointer; padding: 3px 0; }
.financial-note p { margin: 5px 0 0; }
.company-tags { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 14px; }
.company-tag { padding: 5px 8px; border: 1px solid #e2e4df; border-radius: 999px; background: #f8f8f5; color: #555b63; font-size: 11px; line-height: 1; }
.company-tag.industry { border-color: #d5dce8; background: #f2f5fa; color: #315a91; }
.signal-price {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 7px;
  margin: 0 0 12px;
}
.signal-price span {
  padding: 7px 8px;
  border: 1px solid #e3e5e0;
  border-radius: 8px;
  background: #fafaf7;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.35;
}
.signal-price strong { display: block; margin-top: 2px; color: var(--ink); font: 700 12px/1.2 Consolas, monospace; }
.line-values { display: flex; flex-wrap: wrap; gap: 7px; }
.line-chip { padding: 5px 8px; border-radius: 7px; font: 11px/1 Consolas, monospace; }
.line-chip.dragon { background: var(--red-soft); color: #9f2e27; }
.line-chip.tiger { background: var(--blue-soft); color: #234780; }
.line-chip.yellow { background: var(--yellow-soft); color: #806013; }
.empty {
  grid-column: 1 / -1;
  padding: 44px 24px;
  border: 1px dashed #bfc4bd;
  border-radius: 18px;
  color: var(--muted);
  text-align: center;
  background: rgba(255,255,255,.35);
}
.history-head { padding: 48px 0 26px; border-bottom: 1px solid var(--ink); }
.history-head h1 { max-width: 720px; }
.metric-strip { display: grid; grid-template-columns: repeat(3, 1fr); border-bottom: 1px solid var(--line); }
.metric { padding: 24px 22px 24px 0; }
.metric + .metric { padding-left: 22px; border-left: 1px solid var(--line); }
.metric span { display: block; color: var(--muted); font-size: 12px; }
.metric strong { display: block; margin-top: 7px; font: 700 clamp(24px, 4vw, 40px)/1 Consolas, monospace; letter-spacing: -.05em; }
.metric small { display: block; margin-top: 8px; color: var(--muted); font-size: 11px; line-height: 1.45; }
.calendar-layout { display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(330px, .92fr); gap: 28px; padding-top: 34px; }
.calendar-panel, .history-detail { border: 1px solid var(--line); border-radius: 20px; background: var(--surface); }
.calendar-panel { padding: 22px; align-self: start; }
.calendar-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.calendar-toolbar strong { font: 700 18px Consolas, monospace; }
.calendar-actions { display: flex; gap: 6px; }
.calendar-nav { width: 36px; height: 36px; border: 1px solid var(--line); border-radius: 50%; background: transparent; cursor: pointer; }
.calendar-week, .calendar-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px; }
.calendar-week span { padding: 4px 0 10px; color: var(--muted); font-size: 11px; text-align: center; }
.calendar-day {
  position: relative;
  min-height: 62px;
  padding: 8px;
  border: 1px solid transparent;
  border-radius: 12px;
  background: transparent;
  text-align: left;
  cursor: default;
}
.calendar-day.has-picks { cursor: pointer; background: #f7f7f4; }
.calendar-day.has-picks:hover { border-color: #c7cbc5; }
.calendar-day.selected { border-color: var(--ink); background: var(--ink); color: white; }
.calendar-day .num { font: 13px Consolas, monospace; }
.calendar-day .count { position: absolute; right: 7px; bottom: 7px; font: 10px Consolas, monospace; color: var(--muted); }
.calendar-day.selected .count { color: #d6d7d9; }
.calendar-day .dots { position: absolute; left: 8px; bottom: 9px; display: flex; gap: 3px; }
.calendar-day .dots i { width: 5px; height: 5px; border-radius: 50%; }
.calendar-day .dots .f { background: var(--red); }
.calendar-day .dots .s { background: var(--blue); }
.calendar-day .dots .t { background: var(--yellow); }
.calendar-day .dots .r { background: #8a8f98; }
.history-detail { min-height: 410px; padding: 24px; }
.detail-date { display: flex; justify-content: space-between; align-items: baseline; gap: 14px; padding-bottom: 18px; border-bottom: 1px solid var(--line); }
.detail-date h2 { margin: 0; font: 700 22px Consolas, monospace; }
.detail-date span { color: var(--muted); font-size: 12px; }
.history-group { padding-top: 20px; }
.history-group h3 { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 14px; }
.history-group h3::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--red); }
.history-group.second h3::before { background: var(--blue); }
.history-group.third h3::before { background: var(--yellow); }
.history-group.removed { margin-top: 8px; padding-top: 20px; border-top: 1px dashed #c9ccc6; }
.history-group.removed h3::before { border-radius: 2px; background: #8a8f98; }
.history-group.removed .history-row { color: #656a72; }
.removal-status { text-align: right; }
.removal-status strong { display: block; color: #656a72; font-size: 12px; }
.removal-status small { display: block; margin-top: 3px; color: var(--muted); font-size: 10px; }
.history-row { display: grid; grid-template-columns: 1fr auto; gap: 10px; padding: 13px 0; border-top: 1px solid #eceeea; }
.history-row:first-of-type { border-top: 0; }
.history-stock strong { display: block; font-size: 14px; }
.history-stock small { color: var(--muted); font: 11px Consolas, monospace; }
.history-return { text-align: right; font-family: Consolas, monospace; }
.history-return strong { display: block; }
.history-return small { color: var(--muted); font-size: 10px; }
.detail-empty { display: grid; min-height: 310px; place-items: center; color: var(--muted); text-align: center; line-height: 1.7; }
.footnote { margin: 34px 0 0; padding-top: 18px; border-top: 1px solid var(--line); color: var(--muted); font-size: 11px; line-height: 1.7; }
@media (max-width: 820px) {
  :root { --topbar-height: calc(62px + var(--safe-top)); }
  .shell { width: min(100% - 28px, 680px); }
  .topbar-inner { min-height: 62px; }
  .market-state span:last-child { display: none; }
  .view-dock { padding: 10px 0 8px; }
  .day-head { grid-template-columns: 112px 1fr; gap: 18px; padding: 38px 0 26px; }
  .date-day { font-size: 76px; }
  .today-total { grid-column: 1 / -1; display: flex; align-items: baseline; justify-content: flex-start; gap: 8px; text-align: left; }
  .today-total strong { font-size: 28px; }
  .tier-title-row { display: block; }
  .tier-rule { margin-top: 8px; text-align: left; }
  .pick-grid { grid-template-columns: 1fr; }
  .calendar-layout { grid-template-columns: 1fr; }
  .metric { padding: 18px 12px 18px 0; }
  .metric + .metric { padding-left: 12px; }
}
@media (max-width: 520px) {
  .shell { width: calc(100% - 24px); }
  .brand { font-size: 14px; }
  .market-state { font-size: 11px; }
  .view-switch { width: 100%; }
  main { padding-top: 8px; }
  .day-head { grid-template-columns: 1fr; gap: 16px; padding-top: 28px; }
  .date-seal { display: none; }
  h1 { font-size: 34px; }
  .tier-section { padding-top: 30px; }
  .sort-toolbar { gap: 8px; padding: 14px 0; }
  .sort-controls { width: 100%; gap: 8px; }
  .sort-select { flex: 1; width: 0; }
  .sort-direction { padding: 9px 10px; }
  .pick-card { min-height: 0; padding: 19px 17px 17px 28px; }
  .financial-cell { padding: 9px 10px; }
  .financial-value { font-size: 19px; }
  .metric-strip { grid-template-columns: 1fr 1fr; }
  .metric:last-child { grid-column: 1 / -1; border-top: 1px solid var(--line); border-left: 0; padding-left: 0; }
  .calendar-panel, .history-detail { border-radius: 16px; }
  .calendar-panel { padding: 14px; }
  .calendar-week, .calendar-grid { gap: 3px; }
  .calendar-day { min-height: 48px; padding: 6px; border-radius: 9px; }
  .calendar-day .count { display: none; }
  .history-detail { padding: 18px; }
  .history-group.corrected .history-row { grid-template-columns: 1fr; gap: 6px; }
  .history-group.corrected .removal-status { max-width: none; text-align: left; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
"""


SCRIPT = r"""
(function () {
  "use strict";
  var initialNode = document.getElementById("initial-data");
  var state = JSON.parse(initialNode.textContent || "{}");
  var selectedDate = "";
  var calendarCursor = null;
  var SORT_OPTIONS = {
    gap: { label: "见底后差额（绝对值）", direction: "asc" },
    change: { label: "今日涨跌幅", direction: "desc" },
    revenue: { label: "总营收同比", direction: "desc" },
    parent: { label: "归母净利润同比", direction: "desc" },
    adjusted: { label: "扣非净利润同比", direction: "desc" },
    cash: { label: "经营现金流 / 归母净利", direction: "desc" }
  };
  var sortPreference = readSortPreference();

  function validSortKey(key) {
    return Object.prototype.hasOwnProperty.call(SORT_OPTIONS, key);
  }
  function readSortPreference() {
    try {
      var saved = JSON.parse(localStorage.getItem("stock-card-sort-v1") || "null");
      if (saved && validSortKey(saved.key)) {
        return { key: saved.key, direction: saved.direction === "asc" || saved.direction === "desc" ? saved.direction : SORT_OPTIONS[saved.key].direction };
      }
    } catch (error) { /* Storage may be disabled; keep sorting available. */ }
    return { key: "gap", direction: "asc" };
  }
  function saveSortPreference(preference) {
    try { localStorage.setItem("stock-card-sort-v1", JSON.stringify(preference)); }
    catch (error) { /* This page still retains the selection until it is closed. */ }
  }
  function sortValue(item, key) {
    if (!validSortKey(key)) return null;
    item = item || {};
    if (key === "gap") {
      var gap = financialNumber(item.bottom_price_gap_abs);
      if (gap !== null && gap >= 0) return gap;
      var price = financialNumber(item.price);
      if (price === null || price <= 0) price = financialNumber(item.close);
      var bottom = financialNumber(item.bottom_price);
      return price !== null && price > 0 && bottom !== null && bottom > 0 ? Math.abs(price - bottom) : null;
    }
    if (key === "change") return financialNumber(item.change_pct);
    var data = item.financials || {};
    var fields = { revenue: "revenue_yoy_pct", parent: "parent_profit_yoy_pct", adjusted: "adjusted_profit_yoy_pct", cash: "operating_cash_to_parent_profit" };
    if (key === "cash" && data.cash_ratio_status !== "ok") return null;
    return financialNumber(data[fields[key]]);
  }
  function sortedRows(rows, key, direction) {
    key = validSortKey(key) ? key : "gap";
    direction = direction === "asc" || direction === "desc" ? direction : SORT_OPTIONS[key].direction;
    return rows.map(function (item, index) {
      return { item: item, index: index, value: sortValue(item, key) };
    }).sort(function (a, b) {
      if (a.value === null && b.value === null) return a.index - b.index;
      if (a.value === null) return 1;
      if (b.value === null) return -1;
      if (a.value === b.value) return a.index - b.index;
      return direction === "asc" ? a.value - b.value : b.value - a.value;
    }).map(function (entry) { return entry.item; });
  }
  function syncSortControls() {
    document.getElementById("sort-key").value = sortPreference.key;
    var ascending = sortPreference.direction === "asc";
    var button = document.getElementById("sort-direction");
    button.textContent = ascending ? "从小到大 ↑" : "从大到小 ↓";
    button.setAttribute("aria-label", "当前" + (ascending ? "从小到大，点击改为从大到小" : "从大到小，点击改为从小到大"));
  }
  function initSortControls() {
    var select = document.getElementById("sort-key");
    Object.keys(SORT_OPTIONS).forEach(function (key) {
      var option = node("option", "", SORT_OPTIONS[key].label);
      option.value = key;
      select.appendChild(option);
    });
    select.addEventListener("change", function () {
      if (!validSortKey(select.value)) return;
      sortPreference = { key: select.value, direction: SORT_OPTIONS[select.value].direction };
      saveSortPreference(sortPreference);
      syncSortControls();
      updateToday();
    });
    document.getElementById("sort-direction").addEventListener("click", function () {
      sortPreference.direction = sortPreference.direction === "asc" ? "desc" : "asc";
      saveSortPreference(sortPreference);
      syncSortControls();
      updateToday();
    });
    syncSortControls();
  }

  function node(tag, className, text) {
    var item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = text;
    return item;
  }
  function number(value, digits) {
    var n = Number(value);
    return Number.isFinite(n) ? n.toFixed(digits === undefined ? 2 : digits) : "—";
  }
  function signed(value) {
    if ((typeof value !== "number" && typeof value !== "string") || (typeof value === "string" && !value.trim())) return "—";
    var n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return (n > 0 ? "+" : "") + n.toFixed(2) + "%";
  }
  function tone(value) {
    var n = Number(value);
    return n > 0 ? "positive" : n < 0 ? "negative" : "neutral";
  }
  function marketPrefix(item) {
    return Number(item.market) === 1 ? "sh" : Number(item.market) === 0 ? "sz" : "bj";
  }
  function quoteUrl(item) {
    return "https://quote.eastmoney.com/" + marketPrefix(item) + item.code + ".html";
  }
  function financialNumber(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }
  function financialSourceUrl(value) {
    if (typeof value !== "string") return "";
    try {
      var url = new URL(value);
      var allowedHost = url.hostname === "eastmoney.com" || url.hostname.endsWith(".eastmoney.com");
      return url.protocol === "https:" && allowedHost && !url.username && !url.password && !url.port ? url.href : "";
    } catch (error) {
      return "";
    }
  }
  function financialSummary(item) {
    var data = item.financials && typeof item.financials === "object" ? item.financials : {};
    var section = node("section", "financial-summary");
    section.setAttribute("aria-label", "财务指标");
    var heading = node("div", "financial-heading");
    var period = data.report_label || data.report_date || "报告期暂无";
    heading.appendChild(node("span", "financial-period", period + " · 年初至报告期末" + (data.stale ? " · 待更新" : "")));
    var sourceUrl = financialSourceUrl(data.source_url);
    if (sourceUrl) {
      var source = node("a", "financial-source", "东方财富 ↗");
      source.href = sourceUrl;
      source.target = "_blank";
      source.rel = "noopener noreferrer";
      source.setAttribute("aria-label", "在新窗口查看东方财富财务数据");
      heading.appendChild(source);
    }
    section.appendChild(heading);
    var grid = node("dl", "financial-grid");
    [
      ["总营收同比", "revenue_yoy_pct"],
      ["归母净利润同比", "parent_profit_yoy_pct"],
      ["扣非净利润同比", "adjusted_profit_yoy_pct"]
    ].forEach(function (metric) {
      var value = financialNumber(data[metric[1]]);
      var cell = node("div", "financial-cell");
      cell.append(node("dt", "financial-label", metric[0]), node("dd", "financial-value " + (value === null ? "neutral unavailable" : tone(value)), value === null ? "暂无" : signed(value)));
      grid.appendChild(cell);
    });
    var cashValue = financialNumber(data.operating_cash_to_parent_profit);
    var cashAvailable = data.cash_ratio_status === "ok" && cashValue !== null;
    var cashText = data.cash_ratio_status === "nonpositive_profit" ? "不适用" : cashAvailable ? number(cashValue) + " 倍" : "暂无";
    var cashCell = node("div", "financial-cell");
    cashCell.append(node("dt", "financial-label", "经营现金流 / 归母净利"), node("dd", "financial-value cash-ratio" + (cashAvailable ? "" : " unavailable"), cashText));
    grid.appendChild(cashCell);
    section.appendChild(grid);
    var note = node("details", "financial-note");
    note.append(
      node("summary", "", "指标口径与现金流比值"),
      node("p", "", "同比均为年初至报告期末累计值，与上年同期比较。现金流比值 = 同期经营活动产生的现金流量净额 ÷ 归属于母公司股东的净利润，单位为倍。"),
      node("p", "", "归母净利润为零或负数时标为“不适用”，缺失数据标为“暂无”。该比值受回款和营运资金变化影响，并非越高越好。")
    );
    if (data.notice_date) note.appendChild(node("p", "", "公告日期：" + data.notice_date));
    if (data.stale) note.appendChild(node("p", "", "本次更新未取得新数据，暂用最近一次缓存，请以最新公告为准。"));
    section.appendChild(note);
    return section;
  }
  function picks() {
    var pools = state.live_pools || {};
    if (selectionBlocked()) return {first: [], second: [], third: []};
    return {
      first: pools.first || pools.main || [],
      second: pools.second || pools.secondary || [],
      third: pools.third || []
    };
  }
  function selectionBlocked() {
    return (state.live_pools || {}).available === false ||
      ["blocked", "stale", "paused", "unavailable", "stale_baseline"].includes(state.selection_status);
  }
  function renderCards(targetId, rows, tier) {
    var target = document.getElementById(targetId);
    target.replaceChildren();
    if (!rows.length) {
      var emptyLabel = tier === "first" ? "第一梯队" : tier === "second" ? "第二梯队" : "第三梯队";
      target.appendChild(node("div", "empty", selectionBlocked() ? "选股暂停展示，等待有效策略数据。" : "今天暂时没有" + emptyLabel + "股票。"));
      return;
    }
    rows.forEach(function (item) {
      var card = node("article", "pick-card " + tier);
      var rail = node("span", "line-rail");
      rail.setAttribute("aria-hidden", "true");
      rail.append(node("i"), node("i"), node("i"));
      card.appendChild(rail);
      var top = node("div", "pick-top");
      var link = node("a", "stock-link");
      link.href = quoteUrl(item);
      link.target = "_blank";
      link.rel = "noreferrer";
      link.append(node("span", "stock-name", item.name || "未命名"), node("span", "stock-code", item.code || ""));
      var price = node("div", "price");
      price.append(node("strong", "", number(item.price || item.close)), node("span", "change " + tone(item.change_pct), signed(item.change_pct)));
      top.append(link, price);
      card.appendChild(top);
      var intro = item.company_intro || (item.industry ? "主要提供" + item.industry + "相关产品与服务。" : "公司主营业务资料正在自动补全。");
      card.appendChild(node("p", "reason", intro));
      card.appendChild(financialSummary(item));
      var tags = node("div", "company-tags");
      if (item.industry) tags.appendChild(node("span", "company-tag industry", "板块 · " + item.industry));
      (Array.isArray(item.concepts) ? item.concepts : []).slice(0, 3).forEach(function (concept) {
        tags.appendChild(node("span", "company-tag", "概念 · " + concept));
      });
      if (tags.childNodes.length) card.appendChild(tags);
      var signalPrice = node("div", "signal-price");
      var signalCell = node("span", "", "见底日收盘" + (item.bottom_date ? " · " + String(item.bottom_date).slice(5) : ""));
      signalCell.appendChild(node("strong", "", number(item.bottom_price)));
      var todayCell = node("span", "", "今日价");
      todayCell.appendChild(node("strong", "", number(item.price || item.close)));
      var gapCell = node("span", "", "绝对差额");
      gapCell.appendChild(node("strong", "", number(item.bottom_price_gap_abs)));
      signalPrice.append(signalCell, todayCell, gapCell);
      card.appendChild(signalPrice);
      var values = node("div", "line-values");
      values.append(
        node("span", "line-chip dragon", "龙 " + number(item.dragon_value)),
        node("span", "line-chip tiger", "虎 " + number(item.tiger_value))
      );
      if (tier !== "first") values.appendChild(node("span", "line-chip yellow", "黄 " + number(item.yellow_line_value)));
      card.appendChild(values);
      target.appendChild(card);
    });
  }
  function updateToday() {
    var blocked = selectionBlocked();
    var notice = document.getElementById("selection-notice");
    notice.hidden = !blocked && state.selection_status !== "partial";
    document.getElementById("selection-notice-title").textContent = blocked ? "选股暂停：计算数据待更新" : "部分股票数据待补齐";
    document.getElementById("selection-note").textContent = state.selection_note || "策略计算数据已过期，正在补齐日线并重算。当前暂停展示选股，不能据此判断今天没有符合条件的股票。";
    document.getElementById("quote-time").textContent = state.quote_timestamp ? "行情时间：" + state.quote_timestamp : "行情日期：" + (state.live_trade_date || state.close_trade_date || "待确认") + "（最新可用）";
    document.getElementById("signal-base-time").textContent = "策略基准日：" + (state.signal_base_date || state.close_trade_date || "待确认");
    var current = picks();
    renderCards("first-picks", sortedRows(current.first, sortPreference.key, sortPreference.direction), "first");
    renderCards("second-picks", sortedRows(current.second, sortPreference.key, sortPreference.direction), "second");
    renderCards("third-picks", sortedRows(current.third, sortPreference.key, sortPreference.direction), "third");
    document.getElementById("first-count").textContent = String(current.first.length);
    document.getElementById("second-count").textContent = String(current.second.length);
    document.getElementById("third-count").textContent = String(current.third.length);
    document.getElementById("today-total-value").textContent = blocked ? "—" : String(current.first.length + current.second.length + current.third.length);
    var date = state.live_trade_date || state.close_trade_date || "";
    if (date) {
      var parts = date.split("-");
      document.getElementById("date-day").textContent = parts[2] || "--";
      document.getElementById("date-month").textContent = (parts[0] || "") + " / " + (parts[1] || "");
      document.getElementById("today-date-copy").textContent = date;
    }
    document.getElementById("market-label").textContent = blocked ? "选股暂停 · 数据待修复" : state.market_label || "收盘选股";
    document.getElementById("update-time").textContent = state.generated_at_display || state.generated_at || "";
  }
  function historyDates() {
    var history = state.history || {};
    return Array.isArray(history.dates) ? history.dates : [];
  }
  function validHistoryRecord(item) {
    return item && !item.invalid_signal && item.performance_eligible !== false;
  }
  function monthlySummary(year, month) {
    var prefix = year + "-" + String(month + 1).padStart(2, "0") + "-";
    var records = [];
    historyDates().forEach(function (day) {
      if (!String(day.trade_date || "").startsWith(prefix)) return;
      ["first", "second", "third"].forEach(function (tier) {
        var values = day[tier];
        if (Array.isArray(values)) records = records.concat(values.filter(validHistoryRecord));
      });
    });
    function finiteValue(value) {
      if (typeof value !== "number" && typeof value !== "string") return null;
      if (typeof value === "string" && !value.trim()) return null;
      var parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : null;
    }
    var evaluated = records.filter(function (item) {
      var selectedPrice = finiteValue(item.selected_price);
      var currentPrice = finiteValue(item.current_price);
      return String(item.current_date || "") > String(item.trade_date || "") &&
        selectedPrice !== null && selectedPrice > 0 &&
        currentPrice !== null && currentPrice > 0 && finiteValue(item.return_pct) !== null;
    });
    var successful = evaluated.filter(function (item) { return finiteValue(item.return_pct) > 0; });
    var returns = evaluated.map(function (item) { return finiteValue(item.return_pct); });
    return {
      label: year + "年" + String(month + 1) + "月",
      evaluatedCount: evaluated.length,
      successRate: evaluated.length ? successful.length / evaluated.length * 100 : null,
      returnCount: returns.length,
      averageReturn: returns.length ? returns.reduce(function (sum, value) { return sum + value; }, 0) / returns.length : null
    };
  }
  function updateMetrics(year, month) {
    var summary = (state.history || {}).summary || {};
    if (year === undefined || month === undefined) {
      if (calendarCursor) {
        year = calendarCursor.getFullYear();
        month = calendarCursor.getMonth();
      } else {
        var parts = defaultCalendarDate().split("-");
        year = Number(parts[0]);
        month = Number(parts[1]) - 1;
      }
    }
    var monthly = monthlySummary(year, month);
    document.getElementById("history-count").textContent = String(summary.selection_count || 0);
    document.getElementById("success-rate").textContent = monthly.successRate === null ? "—" : number(monthly.successRate) + "%";
    document.getElementById("average-return").textContent = monthly.averageReturn === null ? "—" : signed(monthly.averageReturn);
    document.getElementById("success-sample").textContent = monthly.label + " · 已产生后续行情 " + String(monthly.evaluatedCount) + " 条";
    document.getElementById("return-sample").textContent = monthly.label + "入选 · 收益至今 · 有效样本 " + String(monthly.returnCount) + " 条";
  }
  function dateMap() {
    var map = new Map();
    historyDates().forEach(function (item) { map.set(item.trade_date, item); });
    return map;
  }
  function latestHistoryDate() {
    var dates = historyDates().map(function (item) { return item.trade_date; }).filter(Boolean).sort();
    return dates.length ? dates[dates.length - 1] : (state.close_trade_date || new Date().toISOString().slice(0, 10));
  }
  function defaultCalendarDate() {
    var summary = (state.history || {}).summary || {};
    var summaryMonth = (summary.current_month || {}).month || "";
    var candidates = [
      state.live_trade_date || "",
      state.close_trade_date || "",
      summaryMonth ? summaryMonth + "-01" : "",
      latestHistoryDate()
    ].filter(Boolean).sort();
    return candidates.length ? candidates[candidates.length - 1] : new Date().toISOString().slice(0, 10);
  }
  function latestHistoryDateInMonth(monthPrefix) {
    var dates = historyDates().map(function (item) { return item.trade_date; })
      .filter(function (value) { return String(value || "").startsWith(monthPrefix + "-"); })
      .sort();
    return dates.length ? dates[dates.length - 1] : "";
  }
  function renderHistoryRows(container, rows, tier) {
    container.replaceChildren();
    if (!rows.length) {
      container.appendChild(node("div", "neutral", "无"));
      return;
    }
    rows.forEach(function (item) {
      var row = node("div", "history-row");
      var stock = node("div", "history-stock");
      stock.append(node("strong", "", item.name || "未命名"), node("small", "", item.code + " · 入选 " + number(item.selected_price)));
      if (item.signal_integrity === "legacy_unverified") stock.appendChild(node("small", "", "历史基准信息不全，待核验"));
      var result = node("div", "history-return " + tone(item.return_pct));
      result.append(node("strong", "", signed(item.return_pct)), node("small", "", item.status || "待观察"));
      row.append(stock, result);
      container.appendChild(row);
    });
  }
  function tierLabel(tier) {
    return tier === "first" ? "第一梯队" : tier === "second" ? "第二梯队" : "第三梯队";
  }
  function shortTime(value) {
    var text = String(value || "");
    return text.length >= 16 ? text.slice(11, 16) : "";
  }
  function uniqueRemovedRows(rows) {
    var byCode = new Map();
    rows.forEach(function (item) {
      var code = String(item.code || "");
      if (!code) return;
      var key = code + (item.invalid_signal ? ":correction" : ":signal-removal");
      if (!byCode.has(key)) byCode.set(key, item);
    });
    return Array.from(byCode.values());
  }
  function renderRemovedRows(container, rows) {
    container.replaceChildren();
    rows.forEach(function (item) {
      var row = node("div", "history-row removed-row");
      var stock = node("div", "history-stock");
      stock.append(
        node("strong", "", item.name || "未命名"),
        node("small", "", item.code + " · 曾入选" + tierLabel(item.selected_tier || item.tier))
      );
      var result = node("div", "removal-status");
      var restored = Boolean(item.active_again);
      result.append(
        node("strong", "", item.invalid_signal ? "历史纠错 · 不计绩效" : restored ? "曾移除，已重新入选" : "已移除"),
        node(
          "small",
          "",
          (item.removal_reason || "可能见底信号消失") +
            (shortTime(item.removed_at) ? " · " + shortTime(item.removed_at) : "")
        )
      );
      row.append(stock, result);
      container.appendChild(row);
    });
  }
  function renderDayDetail(day) {
    var detail = document.getElementById("history-detail");
    detail.replaceChildren();
    if (!day) {
      detail.appendChild(node("div", "detail-empty", "选择一个有记录的日期，查看当天三梯队股票和它们的至今收益。"));
      return;
    }
    var first = (day.first || []).filter(validHistoryRecord);
    var second = (day.second || []).filter(validHistoryRecord);
    var third = (day.third || []).filter(validHistoryRecord);
    var allRemoved = uniqueRemovedRows(day.removed || []);
    var removed = allRemoved.filter(function (item) { return !item.invalid_signal; });
    var corrected = allRemoved.filter(function (item) { return item.invalid_signal; });
    var head = node("div", "detail-date");
    var countCopy = "共 " + (first.length + second.length + third.length) + " 只";
    if (removed.length) countCopy += " · 移除 " + removed.length + " 只";
    if (corrected.length) countCopy += " · 纠错 " + corrected.length + " 只";
    head.append(node("h2", "", day.trade_date), node("span", "", countCopy));
    detail.appendChild(head);
    var groupFirst = node("section", "history-group first");
    groupFirst.appendChild(node("h3", "", "第一梯队"));
    var firstRows = node("div");
    renderHistoryRows(firstRows, first, "first");
    groupFirst.appendChild(firstRows);
    var groupSecond = node("section", "history-group second");
    groupSecond.appendChild(node("h3", "", "第二梯队"));
    var secondRows = node("div");
    renderHistoryRows(secondRows, second, "second");
    groupSecond.appendChild(secondRows);
    var groupThird = node("section", "history-group third");
    groupThird.appendChild(node("h3", "", "第三梯队"));
    var thirdRows = node("div");
    renderHistoryRows(thirdRows, third, "third");
    groupThird.appendChild(thirdRows);
    detail.append(groupFirst, groupSecond, groupThird);
    if (removed.length) {
      var groupRemoved = node("section", "history-group removed");
      groupRemoved.appendChild(node("h3", "", "盘中移除"));
      var removedRows = node("div");
      renderRemovedRows(removedRows, removed);
      groupRemoved.appendChild(removedRows);
      detail.appendChild(groupRemoved);
    }
    if (corrected.length) {
      var groupCorrected = node("section", "history-group corrected");
      groupCorrected.appendChild(node("h3", "", "历史纠错"));
      groupCorrected.appendChild(node("p", "neutral", "保留当时记录供核对；不属于有效入选，不计胜率或收益。与真实信号消失的盘中移除分开记录。"));
      var correctedRows = node("div");
      renderRemovedRows(correctedRows, corrected);
      groupCorrected.appendChild(correctedRows);
      detail.appendChild(groupCorrected);
    }
  }
  function renderCalendar() {
    var map = dateMap();
    if (!calendarCursor) calendarCursor = new Date(defaultCalendarDate() + "T00:00:00");
    var year = calendarCursor.getFullYear();
    var month = calendarCursor.getMonth();
    updateMetrics(year, month);
    document.getElementById("calendar-label").textContent = year + " / " + String(month + 1).padStart(2, "0");
    var grid = document.getElementById("calendar-grid");
    grid.replaceChildren();
    var firstWeekday = new Date(year, month, 1).getDay();
    var totalDays = new Date(year, month + 1, 0).getDate();
    for (var blank = 0; blank < firstWeekday; blank += 1) grid.appendChild(node("span"));
    for (var dayNumber = 1; dayNumber <= totalDays; dayNumber += 1) {
      var key = year + "-" + String(month + 1).padStart(2, "0") + "-" + String(dayNumber).padStart(2, "0");
      var record = map.get(key);
      var button = node("button", "calendar-day" + (record ? " has-picks" : "") + (key === selectedDate ? " selected" : ""));
      button.type = "button";
      button.disabled = !record;
      button.appendChild(node("span", "num", String(dayNumber)));
      if (record) {
        var first = (record.first || []).filter(validHistoryRecord);
        var second = (record.second || []).filter(validHistoryRecord);
        var third = (record.third || []).filter(validHistoryRecord);
        var removed = record.removed || [];
        var dots = node("span", "dots");
        if (first.length) dots.appendChild(node("i", "f"));
        if (second.length) dots.appendChild(node("i", "s"));
        if (third.length) dots.appendChild(node("i", "t"));
        if (removed.length) dots.appendChild(node("i", "r"));
        button.append(dots, node("span", "count", String(first.length + second.length + third.length)));
        button.setAttribute("aria-label", key + "，共 " + (first.length + second.length + third.length) + " 只");
        button.addEventListener("click", function (dateKey, dateRecord) {
          return function () {
            selectedDate = dateKey;
            renderCalendar();
            renderDayDetail(dateRecord);
          };
        }(key, record));
      }
      grid.appendChild(button);
    }
  }
  function setView(view) {
    document.querySelectorAll(".view-button").forEach(function (button) {
      var active = button.dataset.view === view;
      button.setAttribute("aria-selected", active ? "true" : "false");
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    document.getElementById("today-view").hidden = view !== "today";
    document.getElementById("history-view").hidden = view !== "history";
    if (view === "history") {
      if (!calendarCursor) {
        var defaultDate = defaultCalendarDate();
        calendarCursor = new Date(defaultDate + "T00:00:00");
        selectedDate = latestHistoryDateInMonth(defaultDate.slice(0, 7));
      }
      renderCalendar();
      renderDayDetail(dateMap().get(selectedDate));
    }
  }
  document.querySelectorAll(".view-button").forEach(function (button) {
    button.addEventListener("click", function () { setView(button.dataset.view); });
  });
  document.getElementById("calendar-prev").addEventListener("click", function () {
    calendarCursor = new Date(calendarCursor.getFullYear(), calendarCursor.getMonth() - 1, 1);
    renderCalendar();
  });
  document.getElementById("calendar-next").addEventListener("click", function () {
    calendarCursor = new Date(calendarCursor.getFullYear(), calendarCursor.getMonth() + 1, 1);
    renderCalendar();
  });
  async function refresh() {
    try {
      var response = await fetch("live.json?t=" + Date.now(), { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      var live = await response.json();
      if (live && live.live_pools) {
        state = live;
        updateToday();
        updateMetrics();
        if (!document.getElementById("history-view").hidden) {
          renderCalendar();
          renderDayDetail(dateMap().get(selectedDate));
        }
      }
    } catch (error) {
      document.getElementById("market-label").textContent = selectionBlocked() ? "选股暂停 · 数据待修复" : "使用最近一次数据";
    }
  }
  initSortControls();
  updateToday();
  updateMetrics();
  setView("today");
  window.setInterval(refresh, 60000);
  refresh();
}());
"""


def _row(item: object) -> dict:
    if is_dataclass(item):
        return asdict(item)
    if isinstance(item, Mapping):
        return dict(item)
    return dict(vars(item))


def _safe_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render_report(
    evaluations: Sequence[object],
    cfg: Mapping[str, object],
    scanned: int,
    errors: Sequence[str],
    strategy_state: Mapping[str, object] | None = None,
    events: Sequence[Mapping[str, object]] | None = None,
    history: Mapping[str, object] | None = None,
    trade_date_override: str = "",
    live_state: Mapping[str, object] | None = None,
) -> str:
    rows = [_row(item) for item in evaluations]
    tiers = split_tiers(rows, cfg)
    trade_date = trade_date_override or max(
        (str(item.get("date", "")) for item in rows),
        default="",
    )
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    history_payload = dict(history or load_history(HISTORY_PATH) or empty_history(trade_date))
    initial = {
        "generated_at": generated_at,
        "generated_at_display": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "market_label": "收盘选股",
        "close_trade_date": trade_date,
        "live_trade_date": trade_date,
        "signal_base_date": trade_date,
        "live_pools": {
            FIRST_TIER: tiers[FIRST_TIER],
            SECOND_TIER: tiers[SECOND_TIER],
            THIRD_TIER: tiers[THIRD_TIER],
            "available": True,
        },
        "history": history_payload,
        "target_count": scanned,
        "quote_count": max(0, scanned - len(errors)),
    }
    if live_state is not None:
        for key in (
            "generated_at", "generated_at_display", "market_label", "close_trade_date",
            "live_trade_date", "signal_base_date", "strategy_base_date", "quote_timestamp",
            "selection_status", "selection_note", "strategy_is_stale", "is_stale",
            "target_count", "quote_count",
        ):
            if key in live_state:
                initial[key] = live_state[key]
        # Rebuilds must not turn quote time into a fresh strategy base or hide a
        # blocked selection while the first live.json fetch is still pending.
        initial["signal_base_date"] = str(live_state.get("signal_base_date") or live_state.get("close_trade_date") or "")
        live_pools = live_state.get("live_pools")
        if isinstance(live_pools, Mapping):
            blocked = live_pools.get("available") is False or live_state.get("selection_status") == "blocked"
            initial["live_pools"] = {
                tier: [] if blocked else live_pools.get(tier, [])
                for tier in (FIRST_TIER, SECOND_TIER, THIRD_TIER)
            }
            initial["live_pools"]["available"] = not blocked
    title = f"每日三梯队选股 · {trade_date or '等待数据'}"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <meta name="theme-color" content="#f4f4ef">
  <meta name="description" content="每日第一梯队、第二梯队、第三梯队选股与历史收益日历">
  <title>{html.escape(title)}</title>
  <style>{STYLES}</style>
</head>
<body>
  <header class="topbar">
    <div class="shell topbar-inner">
      <div class="brand"><span class="brand-mark" aria-hidden="true"></span><span>每日三梯队选股</span></div>
      <div class="market-state"><i class="market-dot" aria-hidden="true"></i><span id="market-label">收盘选股</span><span id="update-time">{html.escape(initial['generated_at_display'])}</span></div>
    </div>
  </header>
  <div class="view-dock">
    <div class="shell">
      <nav class="view-switch" aria-label="页面功能">
        <button class="view-button" type="button" data-view="today" aria-selected="true" aria-current="page">今日选股</button>
        <button class="view-button" type="button" data-view="history" aria-selected="false">历史日历</button>
      </nav>
    </div>
  </div>
  <main class="shell">
    <section id="today-view" class="view-panel">
      <header class="day-head">
        <div class="date-seal" aria-label="交易日期"><span id="date-day" class="date-day">{html.escape(trade_date[-2:] if trade_date else '--')}</span><span id="date-month" class="date-month">{html.escape(trade_date[:7].replace('-', ' / ') if trade_date else '')}</span></div>
        <div><p class="eyebrow">TODAY / <span id="today-date-copy">{html.escape(trade_date)}</span></p><h1>今天，只看三梯队。</h1><p class="intro">第一梯队看龙虎线靠拢，第二梯队看当前价格是否处在黄线下方，第三梯队收纳其余近 4 个交易日见底信号。</p></div>
        <div class="today-total"><strong id="today-total-value">0</strong><span>今日合计</span></div>
      </header>
      <div class="data-provenance"><span id="quote-time"></span><span id="signal-base-time"></span></div>
      <aside id="selection-notice" class="selection-notice" role="status" hidden><strong id="selection-notice-title">选股暂停：计算数据待更新</strong><p id="selection-note"></p></aside>
      <div class="sort-toolbar" aria-label="今日选股排序">
        <div class="sort-controls">
          <label class="sort-label" for="sort-key">排序</label>
          <select id="sort-key" class="sort-select" aria-describedby="sort-hint"></select>
          <button id="sort-direction" class="sort-direction" type="button">从小到大 ↑</button>
        </div>
        <p id="sort-hint" class="sort-hint">仅改变各梯队的显示顺序，暂无或不适用排末。</p>
      </div>
      <section class="tier-section first">
        <div class="tier-title-row"><div><div class="tier-kicker"><span class="tier-index">01</span>优先查看</div><h2>第一梯队 <span id="first-count">0</span></h2></div><p class="tier-rule">近 4 个交易日出现可能见底，且此前连续 3 个交易日的龙虎线差值绝对值，每一天都不大于 0.5。</p></div>
        <div id="first-picks" class="pick-grid"></div>
      </section>
      <section class="tier-section second">
        <div class="tier-title-row"><div><div class="tier-kicker"><span class="tier-index">02</span>继续留意</div><h2>第二梯队 <span id="second-count">0</span></h2></div><p class="tier-rule">近 4 个交易日出现可能见底，且当前价不高于黄线。</p></div>
        <div id="second-picks" class="pick-grid"></div>
      </section>
      <section class="tier-section third">
        <div class="tier-title-row"><div><div class="tier-kicker"><span class="tier-index">03</span>新近信号</div><h2>第三梯队 <span id="third-count">0</span></h2></div><p class="tier-rule">近 4 个交易日出现可能见底，且没有进入第一梯队或第二梯队。</p></div>
        <div id="third-picks" class="pick-grid"></div>
      </section>
    </section>
    <section id="history-view" class="view-panel" hidden>
      <header class="history-head"><p class="eyebrow">HISTORY LEDGER</p><h1>每一天的选择，都留在日历里。</h1><p class="intro">点击有标记的日期查看当日股票、入选价、最新价和至今收益。真实信号消失保留在盘中移除区；过期数据导致的误选保留在历史纠错区，不计入胜率和收益。</p></header>
      <div class="metric-strip">
        <div class="metric"><span>累计入选记录</span><strong id="history-count">0</strong><small>同一股票不同日期入选，按独立记录计算</small></div>
        <div class="metric"><span>当月胜率</span><strong id="success-rate">—</strong><small id="success-sample">当月已产生后续行情 0 条</small></div>
        <div class="metric"><span>当月入选平均至今收益</span><strong id="average-return">—</strong><small id="return-sample">当月入选 · 收益至今 · 有效样本 0 条</small></div>
      </div>
      <div class="calendar-layout">
        <section class="calendar-panel" aria-label="历史选股日历">
          <div class="calendar-toolbar"><strong id="calendar-label"></strong><div class="calendar-actions"><button id="calendar-prev" class="calendar-nav" type="button" aria-label="上一个月">←</button><button id="calendar-next" class="calendar-nav" type="button" aria-label="下一个月">→</button></div></div>
          <div class="calendar-week" aria-hidden="true"><span>日</span><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span></div>
          <div id="calendar-grid" class="calendar-grid"></div>
        </section>
        <section id="history-detail" class="history-detail" aria-live="polite"></section>
      </div>
      <p class="footnote">“可能见底”按公式逐次重算：当天仍在形成低点、文字标记尚未出现时不入选；低点经过至少一个后续交易日且文字标记已经出现后，才进入梯队。后续重绘消失时，股票会从今日梯队移除，并保留在历史日历的当日移除区。当月胜率与平均至今收益按入选日归入日历当前显示的月份，切换月份会同步重算；收益按该月入选记录等权计算至今。入选当日尚无后续行情的记录不计胜负或平均收益，价格或收益缺失的记录不计平均收益。新规则自 {html.escape(str(history_payload.get('started_on') or trade_date or '首次发布日'))} 起独立记录，未计交易费用、滑点及涨跌停无法成交。</p>
    </section>
  </main>
  <noscript><p class="shell empty">需要启用 JavaScript 才能切换日历和自动刷新最新行情。</p></noscript>
  <script id="initial-data" type="application/json">{_safe_json(initial)}</script>
  <script>{SCRIPT}</script>
</body>
</html>"""
