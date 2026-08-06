import unittest

from simple_report_ui import render_report


class SimpleReportUiTests(unittest.TestCase):
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
        self.assertIn("当前价不高于龙线、虎线和黄线", page)

    def test_page_is_mobile_ready_and_has_the_three_line_visual(self):
        page = render_report([], {"line_gap_max_abs": 0.5}, 0, [])
        self.assertIn('name="viewport"', page)
        self.assertIn("@media (max-width: 520px)", page)
        self.assertIn("prefers-reduced-motion", page)
        self.assertIn("line-rail", page)
        self.assertIn("累计入选记录", page)
        self.assertIn("总成功率", page)


if __name__ == "__main__":
    unittest.main()
