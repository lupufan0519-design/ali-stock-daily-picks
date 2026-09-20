import json
import shutil
import subprocess
import unittest

from simple_report_ui import SCRIPT, render_report


class SimpleReportUiTests(unittest.TestCase):
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
        self.assertIn("var removed = uniqueRemovedRows(day.removed || []);", page)
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
        self.assertIn("累计平均至今收益", page)
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
