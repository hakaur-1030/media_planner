from datetime import date, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from bigquery_repository import BigQueryRepository
from models import MediaPlanRequest


class RecentBookingEligibilityTest(unittest.TestCase):
    def test_reads_dt_and_excludes_null_countries(self):
        repo = object.__new__(BigQueryRepository)
        repo.settings = SimpleNamespace(
            adgroup_booked_delivered_table="project.dataset.adgroup_booked_delivered",
        )
        repo._recent_booking_cache = {}
        fields = {
            "dt": "dt",
            "slot_code": "slot_code",
            "booked_views": "booked_views",
            "country": "country",
        }
        repo._field_name = Mock(side_effect=lambda _table, *aliases: next((fields[name] for name in aliases if name in fields), None))
        repo._query_records = Mock(return_value=[
            {"country": None, "slot_code": "test_offsite_asset", "booked_views": 10_000},
            {"country": "sa", "slot_code": "supermall_sa_sfu_1", "booked_views": 765_776},
        ])
        start = date.today() + timedelta(days=2)
        request = MediaPlanRequest.model_validate({
            "brand": "Test",
            "comcats": ["Mobiles"],
            "countries": ["sa"],
            "start_date": start,
            "end_date": start + timedelta(days=3),
            "budget": 5_000,
            "currency": "USD",
            "objective": "reach",
        })

        result = repo._fetch_recent_booked_views(request)

        self.assertEqual(result, {("sa", "supermall_sa_sfu_1"): 765_776})
        sql = repo._query_records.call_args.args[0]
        self.assertIn("DATE(`dt`)", sql)
        self.assertIn("INTERVAL 12 MONTH", sql)
        self.assertIn("`country` IS NOT NULL", sql)
        self.assertIn("TRIM(CAST(`country` AS STRING)) != ''", sql)


class RateCardTest(unittest.TestCase):
    def test_uses_q4_daily_cost_rows_and_legacy_rates_outside_q4(self):
        repo = object.__new__(BigQueryRepository)
        repo.settings = SimpleNamespace(
            slot_rate_card_table="project.dataset.rate_card_legacy",
            slot_rate_card_q4_table="project.dataset.rate_card_q4",
        )

        legacy_rows = [
            {"slot_code": "home_hero", "date": "2026-09-30", "country": "ae", "cpm_rate": 10},
        ]
        q4_rows = [
            {"slot_code": "home_hero", "date": "2026-10-01", "country": "ae", "type": "CPM", "cost": 15},
            {"slot_code": "home_hero", "date": "2026-10-02", "country": "ae", "type": "CPD", "cost": 500},
        ]

        repo._table_records_for_window = Mock(
            side_effect=lambda table_id, *_args: legacy_rows if table_id.endswith("legacy") else q4_rows
        )

        by_country_slot, by_slot = repo._fetch_rate_card_map(date(2026, 9, 30), date(2026, 10, 2))

        self.assertEqual(
            repo._table_records_for_window.call_args_list[0].args[:3],
            ("project.dataset.rate_card_legacy", date(2026, 9, 30), date(2026, 9, 30)),
        )
        self.assertEqual(
            repo._table_records_for_window.call_args_list[1].args[:3],
            ("project.dataset.rate_card_q4", date(2026, 10, 1), date(2026, 10, 2)),
        )
        rates = by_country_slot[("ae", "home_hero")]
        self.assertEqual(rates["cpm_rate_schedule"], {"2026-09-30": 10.0, "2026-10-01": 15.0})
        self.assertEqual(rates["cpd_rate_schedule"], {"2026-10-02": 500.0})
        self.assertEqual(rates["pricing_options"], ["CPM", "CPD"])
        self.assertEqual(by_slot["home_hero"]["cpm_rate_schedule"]["2026-10-01"], 15.0)


if __name__ == "__main__":
    unittest.main()
