import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from market_analysis import (
    build_market_analysis,
    market_cap_is_consistent,
    parse_quote_time,
    parse_tencent_fields,
    sniper_bounds,
)


class MarketAnalysisTests(unittest.TestCase):
    def test_sniper_bounds(self):
        self.assertEqual(sniper_bounds("HK$120.09–160.94"), (120.09, 160.94))
        self.assertIsNone(sniper_bounds("—（非狙击区）"))

    def test_above_range_analysis(self):
        stock = {
            "price": 200,
            "fairValue": 150,
            "sniperPrice": "100–130",
            "layer": "L0",
            "step0": {"light": "绿灯"},
            "redline": {"passed": True},
        }
        analysis = build_market_analysis(stock, {"changePct": 2.5, "validationStatus": "dual-source"}, "now")
        self.assertEqual(analysis["signal"], "谨慎追高")
        self.assertEqual(analysis["valuationGapPct"], -25.0)

    def test_market_cap_unit_guard(self):
        self.assertTrue(market_cap_is_consistent(7539, 1199.93, 7539, 1199.93, 1.0, False))
        self.assertFalse(market_cap_is_consistent(7539, 1199.93, 75390000, 1199.93, 1.0, False))

    def test_market_cap_guard_allows_float_to_total_migration(self):
        self.assertTrue(
            market_cap_is_consistent(
                584.2,
                77.74,
                752.81,
                78.87,
                1.0,
                False,
                new_float_cap_local_yi=587.03,
            )
        )

    def test_parse_tencent_a_share_fields(self):
        fields = [""] * 60
        for index, value in {
            3: "1199.90", 4: "1199.93", 5: "1163.00", 30: "20260810093343",
            31: "-0.03", 32: "-0.00", 33: "1213.00", 34: "1162.00",
            38: "0.44", 39: "226.25", 44: "136.19", 45: "2917.05", 56: "2.53",
        }.items():
            fields[index] = value
        quote = parse_tencent_fields(fields)
        self.assertEqual(quote["price"], 1199.9)
        self.assertEqual(quote["floatMarketCapYi"], 136.19)
        self.assertEqual(quote["marketCapYi"], 2917.05)
        self.assertEqual(quote["pb"], 2.53)
        self.assertEqual(quote["currency"], "CNY")

    def test_parse_tencent_hk_preopen_zeros(self):
        fields = [""] * 78
        for index, value in {
            3: "478.800", 4: "478.800", 5: "0", 30: "2026/08/10 09:18:36",
            31: "0", 32: "0", 33: "0", 34: "0", 39: "17.47",
            44: "43488.0714", 45: "43488.0714", 58: "3.46",
        }.items():
            fields[index] = value
        quote = parse_tencent_fields(fields, is_hk=True)
        self.assertIsNone(quote["open"])
        self.assertIsNone(quote["high"])
        self.assertEqual(quote["pe"], 17.47)
        self.assertEqual(quote["pb"], 3.46)
        self.assertEqual(quote["currency"], "HKD")

    def test_parse_quote_time_accepts_both_formats(self):
        from zoneinfo import ZoneInfo

        timezone = ZoneInfo("Asia/Shanghai")
        self.assertEqual(parse_quote_time("20260810093343", timezone).hour, 9)
        self.assertEqual(parse_quote_time("2026/08/10 09:18:36", timezone).minute, 18)
        self.assertIsNone(parse_quote_time("bad", timezone))


if __name__ == "__main__":
    unittest.main()
