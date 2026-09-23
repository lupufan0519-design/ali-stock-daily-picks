import json
import re
import shutil
import subprocess
import unittest

from simple_report_ui import SCRIPT, render_report


class SimpleReportUiTests(unittest.TestCase):
    def test_static_initial_payload_preserves_blocked_live_state(self):
        live = {"selection_status": "blocked", "selection_note": "策略计算数据过期",
                "signal_base_date": "2026-09-09", "close_trade_date": "2026-09-09",
                "live_trade_date": "2026-09-22", "quote_timestamp": "2026-09-22 15:00:00",
                "live_pools": {"available": False, "first": [{"code": "002132"}]}}
        page = render_report([], {}, 0, [], trade_date_override="2026-09-22", live_state=live)
        initial = json.loads(re.search(r'<script id="initial-data" type="application/json">(.*?)</script>', page).group(1))
        self.assertEqual(initial["signal_base_date"], "2026-09-09")
        self.assertEqual(initial["selection_status"], "blocked")
        self.assertFalse(initial["live_pools"]["available"])
        self.assertEqual(initial["live_pools"]["first"], [])

    def test_primary_view_switch_stays_visible_while_scrolling(self):
        page = render_report([], {"line_gap_max_abs": 0.5}, 0, [])
        self.assertIn('class="view-dock"', page)
        self.assertIn(".view-dock {\n  position: sticky;", page)
        self.assertIn("top: var(--topbar-height);", page)
        self.assertIn("z-index: 30;", page)
        self.assertIn("--safe-top: env(safe-area-inset-top, 0px);", page)
        self.assertIn("min-height: 48px;", page)
        self.assertIn('aria-current="page"', page)
        self.assertIn('button.setAttribute("aria-current", "page")', page)

    def test_history_calendar_has_a_removed_section_for_repainted_signals(self):
        history = {
            "schema_version": 1,
            "strategy_version": "three_tier_confirmed_bottom4_v6",
            "started_on": "2026-08-07",
            "updated_at": "2026-08-07T10:05:00+08:00",
            "dates": [
                {
                    "trade_date": "2026-08-07",
                    "first": [],
                    "second": [],
                    "third": [],
                    "removed": [
                        {
                            "code": "600001",
                            "name": "示例股票",
                            "selected_tier": "second",
                            "removed_at": "2026-08-07T10:05:00+08:00",
                            "removal_reason": "可能见底信号消失",
                        }
                    ],
                }
            ],
            "summary": {"selection_count": 1},
        }
        page = render_report([], {"line_gap_max_abs": 0.5}, 0, [], history=history)
        self.assertIn("history-group removed", page)
        self.assertIn("盘中移除", page)
        self.assertIn("可能见底信号消失", page)
        self.assertIn('"removed":[', page)
        self.assertIn("function uniqueRemovedRows(rows)", page)
        self.assertIn("var allRemoved = uniqueRemovedRows(day.removed || []);", page)
        self.assertIn("历史纠错", page)
        self.assertIn("至少一个后续交易日", page)
        self.assertIn("文字标记已经出现后", page)
        self.assertNotIn("一辰波段", page)

    def test_page_has_only_today_and_history_primary_views(self):
        page = render_report([], {"line_gap_max_abs": 0.5}, 0, [])
        self.assertEqual(page.count('class="view-button"'), 2)
        self.assertIn("今日选股", page)
        self.assertIn("历史日历", page)
        self.assertNotIn("历史滚动验证", page)
        self.assertNotIn("观察区", page)
        self.assertNotIn("主选区", page)

    def test_page_states_the_exact_first_tier_window(self):
        page = render_report([], {"line_gap_max_abs": 0.5}, 0, [])
        self.assertIn("此前连续 3 个交易日", page)
        self.assertIn("每一天都不大于 0.5", page)
        self.assertIn("当前价不高于黄线", page)
        self.assertIn("近 4 个交易日出现可能见底，且没有进入第一梯队或第二梯队", page)
        self.assertNotIn("当前价不高于龙线、虎线和黄线", page)

    def test_page_has_three_mutually_exclusive_tier_sections(self):
        page = render_report([], {"line_gap_max_abs": 0.5}, 0, [])
        self.assertIn("今天，只看三梯队", page)
        self.assertIn('id="first-picks"', page)
        self.assertIn('id="second-picks"', page)
        self.assertIn('id="third-picks"', page)
        self.assertIn('id="third-count"', page)

    def test_page_is_mobile_ready_and_has_the_three_line_visual(self):
        page = render_report([], {"line_gap_max_abs": 0.5}, 0, [])
        self.assertIn('name="viewport"', page)
        self.assertIn("@media (max-width: 520px)", page)
        self.assertIn("prefers-reduced-motion", page)
        self.assertIn("line-rail", page)
        self.assertIn("累计入选记录", page)
        self.assertIn("当月胜率", page)
        self.assertNotIn("总成功率", page)
        self.assertIn("function monthlySummary(year, month)", page)
        self.assertIn("updateMetrics(year, month);", page)
        self.assertIn("function defaultCalendarDate()", page)
        self.assertIn("state.live_trade_date ||", page)
        self.assertIn("(summary.current_month || {}).month", page)
        self.assertIn("latestHistoryDateInMonth(defaultDate.slice(0, 7))", page)
        self.assertIn("按入选日归入日历当前显示的月份", page)
        self.assertIn("当月入选平均至今收益", page)
        self.assertIn('id="return-sample"', page)
        self.assertIn("收益按该月入选记录等权计算至今", page)
        self.assertIn("入选当日尚无后续行情的记录不计胜负或平均收益", page)
        self.assertNotIn("summary.average_return_pct", page)
        self.assertIn("company-tags", page)
        self.assertIn("板块 · ", page)
        self.assertIn("公司主营业务资料正在自动补全", page)

    def test_pick_payload_contains_company_intro_sector_and_concepts(self):
        page = render_report(
            [
                {
                    "code": "600001",
                    "name": "示例公司",
                    "market": 1,
                    "date": "2026-08-06",
                    "close": 10.0,
                    "bottom_price": 9.6,
                    "bottom_ok": True,
                    "prior_three_gap_abs": [0.2, 0.3, 0.4],
                    "dragon_value": 9.8,
                    "tiger_value": 9.7,
                    "yellow_line_value": 10.2,
                    "eligible": True,
                    "company_intro": "主营高端测试设备。",
                    "industry": "专用设备",
                    "concepts": ["机器人", "工业互联"],
                    "financials": {
                        "report_label": "2026年中报",
                        "revenue_yoy_pct": 0,
                        "parent_profit_yoy_pct": 12.34,
                        "adjusted_profit_yoy_pct": -4.56,
                        "operating_cash_to_parent_profit": 1.2,
                        "cash_ratio_status": "ok",
                    },
                }
            ],
            {"line_gap_max_abs": 0.5},
            1,
            [],
        )
        self.assertIn("主营高端测试设备", page)
        self.assertIn("专用设备", page)
        self.assertIn("机器人", page)
        self.assertIn("2026年中报", page)
        self.assertIn('"revenue_yoy_pct":0', page)
        self.assertIn("总营收同比", page)
        self.assertIn("归母净利润同比", page)
        self.assertIn("扣非净利润同比", page)
        self.assertIn("经营现金流 / 归母净利", page)
        self.assertNotIn("主要客户", page)
        self.assertNotIn("customer-summary", page)
        self.assertNotIn("近两日出现可能见底 ·", page)


    def test_cards_show_signal_price_today_price_and_absolute_gap(self):
        page = render_report(
            [
                {
                    "code": "600001",
                    "name": "Example",
                    "market": 1,
                    "date": "2026-08-06",
                    "close": 10.0,
                    "bottom_price": 9.6,
                    "bottom_ok": True,
                    "prior_three_gap_abs": [0.2, 0.3, 0.4],
                    "dragon_value": 9.8,
                    "tiger_value": 9.7,
                    "yellow_line_value": 10.2,
                    "eligible": True,
                }
            ],
            {"line_gap_max_abs": 0.5},
            1,
            [],
        )
        self.assertIn("见底日收盘", page)
        self.assertIn("今日价", page)
        self.assertIn("绝对差额", page)
        self.assertIn("财务指标", page)
        self.assertNotIn("公司未公开具体客户名称", page)


@unittest.skipUnless(shutil.which("node"), "Node.js is required to exercise monthly returns")
class MonthlyReturnBehaviorTests(unittest.TestCase):
    HARNESS = r"""
const {script, initial, actions} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
class Element {
  constructor(tag) { this.tag = tag; this.childNodes = []; this.attributes = {}; this.dataset = {}; this.events = {}; this._text = ''; }
  set textContent(value) { this._text = String(value); this.childNodes = []; }
  get textContent() { return this._text + this.childNodes.map(child => child.textContent).join(''); }
  appendChild(child) { this.childNodes.push(child); return child; }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  replaceChildren(...children) { this._text = ''; this.childNodes = children; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, handler) { this.events[name] = handler; }
  click() { if (this.events.click) this.events.click(); }
}
const elements = new Map();
const views = ['today', 'history'].map(view => { const el = new Element('button'); el.dataset.view = view; return el; });
global.document = {
  createElement: tag => new Element(tag),
  getElementById: id => {
    if (!elements.has(id)) elements.set(id, new Element('div'));
    return elements.get(id);
  },
  querySelectorAll: selector => selector === '.view-button' ? views : []
};
document.getElementById('initial-data').textContent = JSON.stringify(initial);
let interval, nextLive;
global.window = {setInterval(callback) { interval = callback; }};
global.fetch = async () => nextLive ? {ok: true, json: async () => nextLive} : {ok: false, status: 503};
const readMetrics = () => ({...Object.fromEntries(['history-count', 'success-rate', 'average-return', 'success-sample', 'return-sample', 'calendar-label', 'history-detail', 'first-picks', 'selection-note', 'selection-notice-title', 'quote-time', 'signal-base-time', 'today-total-value', 'market-label', 'first-count', 'second-count', 'third-count'].map(id => [id, document.getElementById(id).textContent])), marketDotClass: document.getElementById('market-dot').className});
(async () => {
  eval(script);
  await new Promise(resolve => setImmediate(resolve));
  const snapshots = [readMetrics()];
  for (const action of actions) {
    if (action.type === 'view') views.find(view => view.dataset.view === action.view).click();
    if (action.type === 'month') document.getElementById(action.direction === 'next' ? 'calendar-next' : 'calendar-prev').click();
    if (action.type === 'refresh') { nextLive = action.live; await interval(); }
    snapshots.push(readMetrics());
  }
  process.stdout.write(JSON.stringify(snapshots));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""

    @staticmethod
    def record(trade_date, return_pct, **overrides):
        record = {
            "code": "600001", "name": "示例公司", "trade_date": trade_date,
            "current_date": "2026-09-20", "selected_price": 10,
            "current_price": 12, "return_pct": return_pct,
        }
        record.update(overrides)
        return record

    def monthly_state(self, august_returns=(20, -10, 0)):
        return {
            "live_trade_date": "2026-09-20", "close_trade_date": "2026-09-18",
            "live_pools": {"first": [], "second": [], "third": []},
            "history": {
                "summary": {"selection_count": 99, "average_return_pct": 999},
                "dates": [
                    {"trade_date": "2026-07-10", "first": [self.record("2026-07-10", 100)]},
                    {"trade_date": "2026-08-01", "first": [self.record("2026-08-01", august_returns[0])]},
                    {"trade_date": "2026-08-02", "second": [self.record("2026-08-02", august_returns[1])]},
                    {"trade_date": "2026-08-03", "third": [self.record("2026-08-03", august_returns[2])],
                     "removed": [self.record("2026-08-03", 1000)]},
                    {"trade_date": "2026-09-01", "first": [self.record("2026-09-01", 50)]},
                ],
            },
        }

    def run_monthly_view(self, initial, actions=()):
        result = subprocess.run(
            [shutil.which("node"), "-e", self.HARNESS],
            input=json.dumps({"script": SCRIPT, "initial": initial, "actions": actions}, ensure_ascii=False),
            capture_output=True, text=True, encoding="utf-8", timeout=10, check=True,
        )
        return json.loads(result.stdout)

    def test_month_navigation_averages_only_that_months_entry_records_to_today(self):
        snapshots = self.run_monthly_view(self.monthly_state(), [
            {"type": "view", "view": "history"},
            {"type": "month", "direction": "prev"},
            {"type": "month", "direction": "prev"},
            {"type": "month", "direction": "prev"},
        ])
        self.assertEqual(snapshots[0]["average-return"], "+50.00%")
        august = snapshots[2]
        self.assertEqual(august["calendar-label"], "2026 / 08")
        self.assertEqual(august["average-return"], "+3.33%")
        self.assertEqual(august["success-rate"], "33.33%")
        self.assertEqual(august["return-sample"], "2026年8月入选 · 收益至今 · 有效样本 3 条")
        self.assertEqual(snapshots[3]["average-return"], "+100.00%")
        self.assertEqual(snapshots[4]["average-return"], "—")
        self.assertEqual(snapshots[4]["success-rate"], "—")
        self.assertTrue(all(snapshot["history-count"] == "99" for snapshot in snapshots))

    def test_invalid_values_and_entry_day_records_do_not_dilute_month_average(self):
        state = self.monthly_state()
        records = [
            self.record("2026-09-01", 20),
            self.record("2026-09-01", "-10", selected_price="10", current_price="9"),
            self.record("2026-09-01", 0),
            self.record("2026-09-01", 1000, current_date="2026-09-01"),
            self.record("2026-09-01", 1000, current_date="2026-08-31"),
        ]
        for invalid in (None, "", " ", False, True, "NaN", "Infinity", "-Infinity"):
            records.append(self.record("2026-09-01", invalid))
            records.append(self.record("2026-09-01", 1000, selected_price=invalid))
            records.append(self.record("2026-09-01", 1000, current_price=invalid))
        records.extend([
            self.record("2026-09-01", 1000, selected_price=0),
            self.record("2026-09-01", 1000, current_price=-1),
        ])
        state["history"]["dates"] = [{"trade_date": "2026-09-01", "first": records}]
        snapshot = self.run_monthly_view(state)[0]
        self.assertEqual(snapshot["average-return"], "+3.33%")
        self.assertEqual(snapshot["return-sample"], "2026年9月入选 · 收益至今 · 有效样本 3 条")

    def test_zero_return_is_valid_but_missing_return_displays_unavailable(self):
        for value, expected, count in ((0, "0.00%", 1), (None, "—", 0)):
            with self.subTest(value=value):
                state = self.monthly_state()
                state["history"]["dates"] = [{
                    "trade_date": "2026-09-01", "first": [self.record("2026-09-01", value)]
                }]
                snapshot = self.run_monthly_view(state)[0]
                self.assertEqual(snapshot["average-return"], expected)
                self.assertIn("有效样本 " + str(count) + " 条", snapshot["return-sample"])

    def test_corrections_are_excluded_from_monthly_success_and_returns(self):
        state = self.monthly_state()
        state["history"]["dates"] = [{"trade_date": "2026-09-01", "first": [
            self.record("2026-09-01", 20),
            self.record("2026-09-01", -90, invalid_signal=True),
            self.record("2026-09-01", 100, performance_eligible=False),
            self.record("2026-09-01", None),
        ]}]
        snapshot = self.run_monthly_view(state)[0]
        self.assertEqual(snapshot["average-return"], "+20.00%")
        self.assertEqual(snapshot["success-rate"], "100.00%")
        self.assertIn("后续行情 1 条", snapshot["success-sample"])

    def test_blocked_selection_does_not_look_like_zero_matches(self):
        state = self.monthly_state()
        state.update(selection_status="blocked", selection_note="策略基准已过期", signal_base_date="2026-09-09", quote_timestamp="2026-09-22 15:00:00")
        state["live_pools"] = {"available": False, "first": [{"code": "002132", "name": "不应显示的旧股"}]}
        snapshot = self.run_monthly_view(state)[0]
        self.assertEqual(snapshot["today-total-value"], "—")
        self.assertIn("暂停", snapshot["first-picks"])
        self.assertNotIn("不应显示的旧股", snapshot["first-picks"])
        self.assertNotIn("没有第一梯队", snapshot["first-picks"])
        self.assertIn("9-09", snapshot["signal-base-time"])
        self.assertIn("9-22", snapshot["quote-time"])
        self.assertIn("暂停", snapshot["market-label"])
        self.assertEqual(snapshot["marketDotClass"], "market-dot paused")
        for tier in ("first", "second", "third"):
            self.assertEqual(snapshot[tier + "-count"], "—")

    def test_ready_empty_tiers_are_real_zero_and_have_normal_market_light(self):
        snapshot = self.run_monthly_view(self.monthly_state())[0]
        for tier in ("first", "second", "third"):
            self.assertEqual(snapshot[tier + "-count"], "0")
        self.assertEqual(snapshot["marketDotClass"], "market-dot")

    def test_partial_scan_keeps_valid_cards_with_explicit_note(self):
        state = self.monthly_state()
        state.update(selection_status="partial", selection_note="2只行情待补齐")
        state["live_pools"]["first"] = [{"code": "600001", "name": "可信股票", "price": 10}]
        snapshot = self.run_monthly_view(state)[0]
        self.assertIn("可信股票", snapshot["first-picks"])
        self.assertEqual(snapshot["today-total-value"], "1")
        self.assertEqual(snapshot["selection-note"], "2只行情待补齐")

    def test_correction_and_repaint_are_shown_in_separate_groups(self):
        state = self.monthly_state()
        state["history"]["dates"] = [{"trade_date": "2026-09-01", "first": [], "removed": [
            {"code": "600001", "name": "真实移除", "removal_reason": "可能见底信号消失"},
            {"code": "600001", "name": "同股历史纠错", "invalid_signal": True, "removal_reason": "日期超出窗口"},
        ]}]
        snapshot = self.run_monthly_view(state, [{"type": "view", "view": "history"}])[-1]
        for text in ("盘中移除", "历史纠错", "真实移除", "同股历史纠错", "不计绩效"):
            self.assertIn(text, snapshot["history-detail"])

    def test_missing_history_return_is_shown_as_unknown_not_zero(self):
        state = self.monthly_state()
        state["history"]["dates"] = [{"trade_date": "2026-09-01", "first": [self.record("2026-09-01", None)]}]
        snapshot = self.run_monthly_view(state, [{"type": "view", "view": "history"}])[-1]
        self.assertIn("—", snapshot["history-detail"])
        self.assertNotIn("0.00%", snapshot["history-detail"])

    def test_live_refresh_and_view_switch_preserve_selected_month(self):
        live = self.monthly_state((60, -30, 0))
        live["live_trade_date"] = "2026-10-01"
        next_live = self.monthly_state((-30, 0, 0))
        next_live["live_trade_date"] = "2026-10-02"
        snapshots = self.run_monthly_view(self.monthly_state(), [
            {"type": "view", "view": "history"},
            {"type": "month", "direction": "prev"},
            {"type": "refresh", "live": live},
            {"type": "view", "view": "today"},
            {"type": "refresh", "live": next_live},
            {"type": "view", "view": "history"},
        ])
        self.assertEqual(snapshots[3]["average-return"], "+10.00%")
        self.assertEqual(snapshots[5]["average-return"], "-10.00%")
        self.assertEqual(snapshots[6]["average-return"], "-10.00%")
        for index in (3, 5, 6):
            self.assertEqual(snapshots[index]["calendar-label"], "2026 / 08")
            self.assertTrue(snapshots[index]["return-sample"].startswith("2026年8月入选"))
            self.assertEqual(snapshots[index]["history-count"], "99")


@unittest.skipUnless(shutil.which("node"), "Node.js is required to exercise the card renderer")
class FinancialCardBehaviorTests(unittest.TestCase):
    """Run the shipped JavaScript with a small DOM double, without network access."""

    HARNESS = r"""
const {script, rows} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
class Element {
  constructor(tag) { this.tag = tag; this.className = ''; this.childNodes = []; this.attributes = {}; this.dataset = {}; this._text = ''; }
  set textContent(value) { this._text = String(value); this.childNodes = []; }
  get textContent() { return this._text + this.childNodes.map(child => child.textContent).join(''); }
  appendChild(child) { this.childNodes.push(child); return child; }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  replaceChildren(...children) { this._text = ''; this.childNodes = children; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener() {}
  toJSON() { return {tag: this.tag, className: this.className, text: this.textContent, attributes: this.attributes, href: this.href, target: this.target, rel: this.rel, children: this.childNodes}; }
}
const elements = new Map();
global.document = {
  createElement: tag => new Element(tag),
  getElementById: id => {
    if (!elements.has(id)) elements.set(id, new Element('div'));
    return elements.get(id);
  },
  querySelectorAll: () => []
};
document.getElementById('initial-data').textContent = JSON.stringify({live_trade_date: '2026-09-18', live_pools: {first: rows}});
global.window = {setInterval() {}};
global.fetch = async () => ({ok: false, status: 503});
eval(script);
process.stdout.write(JSON.stringify(document.getElementById('first-picks').childNodes));
"""

    def render_card(self, financials=None):
        row = {
            "code": "600001",
            "name": "示例公司",
            "market": 1,
            "close": 10,
            "company_intro": "主营高端测试设备。",
            "industry": "专用设备",
            "concepts": ["机器人"],
            "customer_summary": "不应展示的旧客户数据",
        }
        if financials is not None:
            row["financials"] = financials
        result = subprocess.run(
            [shutil.which("node"), "-e", self.HARNESS],
            input=json.dumps({"script": SCRIPT, "rows": [row]}, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=True,
        )
        return json.loads(result.stdout)[0]

    def nodes_with_class(self, root, class_name):
        found = [root] if class_name in root["className"].split() else []
        for child in root["children"]:
            found.extend(self.nodes_with_class(child, class_name))
        return found

    def test_financial_grid_replaces_customer_display_after_company_intro(self):
        card = self.render_card({
            "report_label": "2026年中报",
            "revenue_yoy_pct": 0,
            "parent_profit_yoy_pct": 12.34,
            "adjusted_profit_yoy_pct": -4.56,
            "operating_cash_to_parent_profit": 1.2,
            "cash_ratio_status": "ok",
        })
        classes = [child["className"] for child in card["children"]]
        self.assertEqual(classes[classes.index("reason") + 1], "financial-summary")
        self.assertEqual(len(self.nodes_with_class(card, "financial-cell")), 4)
        values = self.nodes_with_class(card, "financial-value")
        self.assertEqual([value["text"] for value in values], ["0.00%", "+12.34%", "-4.56%", "1.20 倍"])
        self.assertIn("neutral", values[0]["className"])
        self.assertIn("positive", values[1]["className"])
        self.assertIn("negative", values[2]["className"])
        self.assertNotIn("positive", values[3]["className"])
        self.assertNotIn("negative", values[3]["className"])
        self.assertNotIn("主要客户", card["text"])
        self.assertNotIn("不应展示的旧客户数据", card["text"])
        self.assertIn("板块 · 专用设备", card["text"])
        self.assertIn("见底日收盘", card["text"])

    def test_absent_financials_and_null_values_never_become_zero(self):
        for data in [None, {}, {"revenue_yoy_pct": None, "parent_profit_yoy_pct": "", "adjusted_profit_yoy_pct": False}]:
            with self.subTest(data=data):
                values = self.nodes_with_class(self.render_card(data), "financial-value")
                self.assertEqual([value["text"] for value in values], ["暂无"] * 4)

    def test_malformed_growth_values_are_unavailable(self):
        card = self.render_card({"revenue_yoy_pct": "12.3", "parent_profit_yoy_pct": [], "adjusted_profit_yoy_pct": {}})
        values = self.nodes_with_class(card, "financial-value")
        self.assertEqual([value["text"] for value in values[:3]], ["暂无"] * 3)

    def test_cash_ratio_distinguishes_nonpositive_profit_from_missing(self):
        for status, value, expected in [
            ("nonpositive_profit", -1.5, "不适用"),
            ("nonpositive_profit", None, "不适用"),
            ("missing", 1.5, "暂无"),
            ("ok", None, "暂无"),
            ("ok", 0, "0.00 倍"),
            ("ok", -0.25, "-0.25 倍"),
        ]:
            with self.subTest(status=status, value=value):
                card = self.render_card({"cash_ratio_status": status, "operating_cash_to_parent_profit": value})
                ratio = self.nodes_with_class(card, "cash-ratio")[0]
                self.assertEqual(ratio["text"], expected)
                self.assertNotIn("positive", ratio["className"])
                self.assertNotIn("negative", ratio["className"])

    def test_period_source_and_touch_accessible_explanation(self):
        source_url = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index?type=web&code=SH600001"
        card = self.render_card({"report_label": "2026年中报", "notice_date": "2026-08-20", "source_url": source_url, "stale": True})
        self.assertIn("2026年中报 · 年初至报告期末 · 待更新", card["text"])
        source = self.nodes_with_class(card, "financial-source")[0]
        self.assertEqual(source["href"], source_url)
        self.assertEqual(source["rel"], "noopener noreferrer")
        self.assertEqual(source["target"], "_blank")
        self.assertIn("新窗口", source["attributes"]["aria-label"])
        note = self.nodes_with_class(card, "financial-note")[0]
        self.assertEqual(note["tag"], "details")
        self.assertEqual(note["children"][0]["tag"], "summary")
        self.assertIn("上年同期", note["text"])
        self.assertIn("经营活动产生的现金流量净额 ÷ 归属于母公司股东的净利润", note["text"])
        self.assertIn("并非越高越好", note["text"])
        self.assertIn("公告日期：2026-08-20", note["text"])
        self.assertIn("最近一次缓存", note["text"])

    def test_source_link_rejects_untrusted_urls(self):
        for value in [
            "javascript:alert(1)",
            "http://emweb.securities.eastmoney.com/",
            "https://eastmoney.com.evil.example/",
            "https://fakeeastmoney.com/",
            "https://eastmoney.com@evil.example/",
            "https://user:password@emweb.securities.eastmoney.com/",
            "https://emweb.securities.eastmoney.com:8443/",
            "//emweb.securities.eastmoney.com/",
            {},
        ]:
            with self.subTest(value=value):
                card = self.render_card({"source_url": value})
                self.assertEqual(self.nodes_with_class(card, "financial-source"), [])

    def test_report_date_fallback_and_untrusted_text_remain_text(self):
        card = self.render_card({"report_date": "2026-06-30", "notice_date": "<img src=x onerror=alert(1)>"})
        self.assertIn("2026-06-30", self.nodes_with_class(card, "financial-period")[0]["text"])
        note = self.nodes_with_class(card, "financial-note")[0]
        self.assertEqual(note["children"][-1]["tag"], "p")
        self.assertEqual(note["children"][-1]["children"], [])
        self.assertIn("<img src=x onerror=alert(1)>", note["children"][-1]["text"])


if __name__ == "__main__":
    unittest.main()
