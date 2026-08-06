import unittest
from types import SimpleNamespace
from unittest.mock import patch

from company_metadata import concise_company_intro, enrich_evaluations, fetch_company_metadata


class CompanyMetadataTests(unittest.TestCase):
    def test_intro_prefers_the_actual_main_business(self):
        profile = (
            "凯龙高科技股份有限公司成立于2001年，是集研发、生产、销售为一体的高新技术企业。"
            "公司主营发动机尾气后处理系统，是行业内少数拥有全产业链能力的公司。"
        )
        self.assertEqual(
            concise_company_intro(profile, "汽车零部件"),
            "公司主营发动机尾气后处理系统，是行业内少数拥有全产业链能力的公司。",
        )

    @patch("company_metadata._get_json")
    def test_fetches_industry_concepts_and_profile(self, get_json):
        get_json.side_effect = [
            {"jbzl": [{"ORG_PROFILE": "公司专注高品质健康饮品。", "EM2016": "食品饮料-饮料-软饮料"}]},
            {"data": {"f127": "饮料乳品", "f129": "新零售,大消费,沪股通,第四项"}},
        ]
        result = fetch_company_metadata("605499", 1)
        self.assertEqual(result["industry"], "饮料乳品")
        self.assertEqual(result["concepts"], ["新零售", "大消费", "沪股通"])
        self.assertEqual(result["company_intro"], "公司专注高品质健康饮品。")

    @patch("company_metadata.fetch_company_metadata")
    def test_enrichment_is_copied_to_live_seed(self, fetch):
        fetch.return_value = {
            "company_intro": "主营测试业务。",
            "industry": "测试板块",
            "concepts": ["概念甲"],
        }
        item = SimpleNamespace(
            code="600001",
            market=1,
            bottom_ok=True,
            eligible=True,
            live_seed={},
        )
        self.assertEqual(enrich_evaluations([item], 1), [])
        self.assertEqual(item.industry, "测试板块")
        self.assertEqual(item.live_seed["concepts"], ["概念甲"])


if __name__ == "__main__":
    unittest.main()
