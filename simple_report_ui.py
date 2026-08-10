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
.customer-summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  margin: -2px 0 14px;
  padding: 10px 12px;
  border-left: 2px solid #c6a84a;
  background: #faf8f0;
  color: #4b4f55;
  font-size: 12px;
  line-height: 1.55;
}
.customer-summary span { color: #806013; font-weight: 700; white-space: nowrap; }
.customer-summary p { margin: 0; }
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
  .pick-card { min-height: 0; padding: 19px 17px 17px 28px; }
  .metric-strip { grid-template-columns: 1fr 1fr; }
  .metric:last-child { grid-column: 1 / -1; border-top: 1px solid var(--line); border-left: 0; padding-left: 0; }
  .calendar-panel, .history-detail { border-radius: 16px; }
  .calendar-panel { padding: 14px; }
  .calendar-week, .calendar-grid { gap: 3px; }
  .calendar-day { min-height: 48px; padding: 6px; border-radius: 9px; }
  .calendar-day .count { display: none; }
  .history-detail { padding: 18px; }
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
  function picks() {
    var pools = state.live_pools || {};
    return {
      first: pools.first || pools.main || [],
      second: pools.second || pools.secondary || [],
      third: pools.third || []
    };
  }
  function renderCards(targetId, rows, tier) {
    var target = document.getElementById(targetId);
    target.replaceChildren();
    if (!rows.length) {
      var emptyLabel = tier === "first" ? "第一梯队" : tier === "second" ? "第二梯队" : "第三梯队";
      target.appendChild(node("div", "empty", "今天暂时没有" + emptyLabel + "股票。"));
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
      var customer = node("div", "customer-summary");
      customer.append(
        node("span", "", "主要客户"),
        node("p", "", item.customer_summary || "公司未公开具体客户名称。")
      );
      card.appendChild(customer);
      var tags = node("div", "company-tags");
      if (item.industry) tags.appendChild(node("span", "company-tag industry", "板块 · " + item.industry));
      (Array.isArray(item.concepts) ? item.concepts : []).slice(0, 3).forEach(function (concept) {
        tags.appendChild(node("span", "company-tag", "概念 · " + concept));
      });
      if (tags.childNodes.length) card.appendChild(tags);
      var signalPrice = node("div", "signal-price");
      var signalCell = node("span", "", "见底日收盘");
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
    var current = picks();
    renderCards("first-picks", current.first, "first");
    renderCards("second-picks", current.second, "second");
    renderCards("third-picks", current.third, "third");
    document.getElementById("first-count").textContent = String(current.first.length);
    document.getElementById("second-count").textContent = String(current.second.length);
    document.getElementById("third-count").textContent = String(current.third.length);
    document.getElementById("today-total-value").textContent = String(current.first.length + current.second.length + current.third.length);
    var date = state.live_trade_date || state.close_trade_date || "";
    if (date) {
      var parts = date.split("-");
      document.getElementById("date-day").textContent = parts[2] || "--";
      document.getElementById("date-month").textContent = (parts[0] || "") + " / " + (parts[1] || "");
      document.getElementById("today-date-copy").textContent = date;
    }
    document.getElementById("market-label").textContent = state.market_label || "收盘选股";
    document.getElementById("update-time").textContent = state.generated_at_display || state.generated_at || "";
  }
  function historyDates() {
    var history = state.history || {};
    return Array.isArray(history.dates) ? history.dates : [];
  }
  function updateMetrics() {
    var summary = (state.history || {}).summary || {};
    document.getElementById("history-count").textContent = String(summary.selection_count || 0);
    document.getElementById("success-rate").textContent = summary.success_rate_pct === null || summary.success_rate_pct === undefined ? "—" : number(summary.success_rate_pct) + "%";
    document.getElementById("average-return").textContent = summary.average_return_pct === null || summary.average_return_pct === undefined ? "—" : signed(summary.average_return_pct);
    document.getElementById("success-sample").textContent = "已产生后续行情 " + String(summary.evaluated_count || 0) + " 条";
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
        node("strong", "", restored ? "曾移除，已重新入选" : "已移除"),
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
    var first = day.first || [];
    var second = day.second || [];
    var third = day.third || [];
    var removed = day.removed || [];
    var head = node("div", "detail-date");
    var countCopy = "共 " + (first.length + second.length + third.length) + " 只";
    if (removed.length) countCopy += " · 移除 " + removed.length + " 只";
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
  }
  function renderCalendar() {
    var map = dateMap();
    if (!calendarCursor) calendarCursor = new Date(latestHistoryDate() + "T00:00:00");
    var year = calendarCursor.getFullYear();
    var month = calendarCursor.getMonth();
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
        var first = record.first || [];
        var second = record.second || [];
        var third = record.third || [];
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
      if (!selectedDate) selectedDate = latestHistoryDate();
      calendarCursor = new Date(selectedDate + "T00:00:00");
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
      document.getElementById("market-label").textContent = "使用最近一次数据";
    }
  }
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
        <div><p class="eyebrow">TODAY / <span id="today-date-copy">{html.escape(trade_date)}</span></p><h1>今天，只看三梯队。</h1><p class="intro">第一梯队看龙虎线靠拢，第二梯队看当前价格是否处在黄线下方，第三梯队收纳其余近三个交易日见底信号。</p></div>
        <div class="today-total"><strong id="today-total-value">0</strong><span>今日合计</span></div>
      </header>
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
      <header class="history-head"><p class="eyebrow">HISTORY LEDGER</p><h1>每一天的选择，都留在日历里。</h1><p class="intro">点击有标记的日期查看当日股票、入选价、最新价和至今收益。盘中曾入选但“可能见底”信号后来消失的股票，会保留在当日移除区。</p></header>
      <div class="metric-strip">
        <div class="metric"><span>累计入选记录</span><strong id="history-count">0</strong><small>同一股票不同日期入选，按独立记录计算</small></div>
        <div class="metric"><span>总成功率</span><strong id="success-rate">—</strong><small id="success-sample">已产生后续行情 0 条</small></div>
        <div class="metric"><span>平均至今收益</span><strong id="average-return">—</strong><small>当前价相对当日收盘入选价</small></div>
      </div>
      <div class="calendar-layout">
        <section class="calendar-panel" aria-label="历史选股日历">
          <div class="calendar-toolbar"><strong id="calendar-label"></strong><div class="calendar-actions"><button id="calendar-prev" class="calendar-nav" type="button" aria-label="上一个月">←</button><button id="calendar-next" class="calendar-nav" type="button" aria-label="下一个月">→</button></div></div>
          <div class="calendar-week" aria-hidden="true"><span>日</span><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span></div>
          <div id="calendar-grid" class="calendar-grid"></div>
        </section>
        <section id="history-detail" class="history-detail" aria-live="polite"></section>
      </div>
      <p class="footnote">“可能见底”按通达信公式逐次重算：右侧临时信号出现即入选；后续重绘消失时，股票会从今日梯队移除，并保留在历史日历的当日移除区。新规则自 {html.escape(str(history_payload.get('started_on') or trade_date or '首次发布日'))} 起独立记录，不把旧策略结果混入成功率。今日入选尚无后续行情，暂不计成功或失败；未计交易费用、滑点及涨跌停无法成交。</p>
    </section>
  </main>
  <noscript><p class="shell empty">需要启用 JavaScript 才能切换日历和自动刷新最新行情。</p></noscript>
  <script id="initial-data" type="application/json">{_safe_json(initial)}</script>
  <script>{SCRIPT}</script>
</body>
</html>"""
