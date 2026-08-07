import unittest

from simple_report_ui import render_report


class SimpleReportUiTests(unittest.TestCase):
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
        self.assertIn("右侧临时信号出现即入选", page)

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
        self.assertIn("总成功率", page)
        self.assertIn("company-tags", page)
        self.assertIn("板块 · ", page)
        self.assertIn("公司业务简介暂缺", page)

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
                }
            ],
            {"line_gap_max_abs": 0.5},
            1,
            [],
        )
        self.assertIn("主营高端测试设备", page)
        self.assertIn("专用设备", page)
        self.assertIn("机器人", page)
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


if __name__ == "__main__":
    unittest.main()
