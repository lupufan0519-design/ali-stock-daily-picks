import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from company_metadata import (
    concise_company_intro,
    concise_customer_summary,
    enrich_evaluations,
    enrich_live_pools,
    fetch_company_metadata,
)


class CompanyMetadataTests(unittest.TestCase):
    def test_customer_summary_uses_only_explicit_customer_wording(self):
        profile = (
            "公司主营低功耗芯片设计。"
            "核心客户覆盖手机品牌、专业音频厂商及智能硬件企业。"
        )
        self.assertEqual(
            concise_customer_summary(profile),
            "核心客户覆盖手机品牌、专业音频厂商及智能硬件企业。",
        )
        self.assertEqual(concise_customer_summary("公司主营低功耗芯片设计。"), "")

    def test_intro_prefers_the_actual_main_business(self):
        profile = (
            "凯龙高科技股份有限公司成立于2001年，是集研发、生产、销售为一体的高新技术企业。"
            "公司主营发动机尾气后处理系统，是行业内少数拥有全产业链能力的公司。"
        )
        self.assertEqual(
            concise_company_intro(profile, "汽车零部件"),
            "公司主营发动机尾气后处理系统，是行业内少数拥有全产业链能力的公司。",
        )

    def test_intro_skips_company_history_and_starts_at_products(self):
        profile = (
            "公司参与了大量国家重点项目，1999年整合成立并挂牌上市。"
            "公司始终坚持科技创新，目前产品布局包括大功率激光器件及装备、"
            "高温超导磁体及应用、智能控制部件和背光源。"
        )
        self.assertEqual(
            concise_company_intro(profile, "消费电子"),
            "目前产品布局包括大功率激光器件及装备、高温超导磁体及应用、智能控制部件和背光源。",
        )
        self.assertLessEqual(len(concise_company_intro(profile, "消费电子")), 69)
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

    @patch("company_metadata._get_json")
    def test_fetches_core_concepts_when_quote_concepts_are_empty(self, get_json):
        get_json.side_effect = [
            {"jbzl": [{"ORG_PROFILE": "主营激光与超导装备。"}]},
            {"data": {"f127": "消费电子", "f129": ""}},
            {
                "ssbk": [
                    {"BOARD_RANK": 1, "BOARD_NAME": "电子"},
                    {"BOARD_RANK": 2, "BOARD_NAME": "消费电子"},
                    {"BOARD_RANK": 3, "BOARD_NAME": "零部件"},
                    {"BOARD_RANK": 4, "BOARD_NAME": "江西板块"},
                    {"BOARD_RANK": 5, "BOARD_NAME": "超导概念"},
                    {"BOARD_RANK": 6, "BOARD_NAME": "军工"},
                ]
            },
        ]
        result = fetch_company_metadata("600363", 1)
        self.assertEqual(result["concepts"], ["军工", "超导概念"])

    @patch("company_metadata.fetch_company_metadata")
    def test_enrichment_is_copied_to_live_seed(self, fetch):
        fetch.return_value = {
            "company_intro": "主营测试业务。",
            "industry": "测试板块",
            "concepts": ["概念甲"],
            "customer_summary": "大型制造企业。",
        }
        item = SimpleNamespace(
            code="600001",
            market=1,
            bottom_ok=True,
            eligible=True,
            live_seed={},
        )
        with TemporaryDirectory() as directory:
            cache_path = Path(directory) / "company_metadata.json"
            self.assertEqual(enrich_evaluations([item], 1, cache_path), [])
            self.assertEqual(item.industry, "测试板块")
            self.assertEqual(item.live_seed["concepts"], ["概念甲"])
            self.assertEqual(item.customer_summary, "大型制造企业。")
            self.assertEqual(item.live_seed["customer_summary"], "大型制造企业。")
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(cache["stocks"]["600001"]["company_intro"], "主营测试业务。")

    @patch("company_metadata.fetch_company_metadata")
    def test_fresh_cache_avoids_network_and_fills_duplicate_pool_aliases(self, fetch):
        with TemporaryDirectory() as directory:
            cache_path = Path(directory) / "company_metadata.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "stocks": {
                            "600001": {
                                "company_intro": "主营缓存产品。",
                                "industry": "缓存板块",
                                "concepts": ["缓存概念"],
                                "customer_summary": "政府与大型企业。",
                                "market": 1,
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            first = {"code": "600001", "market": 1}
            main_alias = {"code": "600001", "market": 1}
            pools = {"first": [first], "main": [main_alias], "second": [], "secondary": []}
            self.assertEqual(enrich_live_pools(pools, 1, cache_path), [])
            fetch.assert_not_called()
            self.assertEqual(first["company_intro"], "主营缓存产品。")
            self.assertEqual(main_alias["concepts"], ["缓存概念"])
            self.assertEqual(first["customer_summary"], "政府与大型企业。")
            self.assertEqual(main_alias["customer_summary"], "政府与大型企业。")

    @patch("company_metadata.fetch_company_metadata")
    def test_fresh_legacy_cache_without_customer_field_refreshes_once(self, fetch):
        fetch.return_value = {
            "company_intro": "主营新产品。",
            "industry": "测试板块",
            "concepts": ["测试概念"],
            "customer_summary": "科研院所与制造企业。",
        }
        with TemporaryDirectory() as directory:
            cache_path = Path(directory) / "company_metadata.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "stocks": {
                            "600001": {
                                "company_intro": "主营旧产品。",
                                "industry": "测试板块",
                                "concepts": ["测试概念"],
                                "market": 1,
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            item = SimpleNamespace(
                code="600001",
                market=1,
                bottom_ok=True,
                eligible=True,
                live_seed={},
            )
            self.assertEqual(enrich_evaluations([item], 1, cache_path), [])
            fetch.assert_called_once()
            self.assertEqual(item.customer_summary, "科研院所与制造企业。")
            saved = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], 2)

    @patch("company_metadata.fetch_company_metadata")
    def test_stale_cache_survives_fetch_failure_and_delays_retry(self, fetch):
        fetch.side_effect = TimeoutError("metadata endpoint timed out")
        with TemporaryDirectory() as directory:
            cache_path = Path(directory) / "company_metadata.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "stocks": {
                            "600001": {
                                "company_intro": "主营缓存产品。",
                                "industry": "缓存板块",
                                "concepts": ["缓存概念"],
                                "market": 1,
                                "updated_at": "2020-01-01T00:00:00+00:00",
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            item = SimpleNamespace(
                code="600001",
                market=1,
                bottom_ok=True,
                eligible=True,
                live_seed={},
            )
            errors = enrich_evaluations([item], 1, cache_path)
            self.assertEqual(len(errors), 1)
            self.assertEqual(item.company_intro, "主营缓存产品。")
            saved = json.loads(cache_path.read_text(encoding="utf-8"))["stocks"]["600001"]
            self.assertIn("retry_after", saved)
            self.assertIn("TimeoutError", saved["last_error"])


if __name__ == "__main__":
    unittest.main()
