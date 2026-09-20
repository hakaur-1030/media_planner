from datetime import date, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from bigquery_repository import BigQueryRepository, rate_available_for_window
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
    def test_q4_daily_rate_requires_every_service_date(self):
        rate_meta = {
            "cpm_rate": 6,
            "cpm_rate_schedule": {"2026-10-06": 6},
            "cpm_daily_rate_window": {"start": "2026-10-01", "end": "2026-12-31"},
        }
        self.assertTrue(rate_available_for_window(rate_meta, "CPM", date(2026, 10, 6), date(2026, 10, 6)))
        self.assertFalse(rate_available_for_window(rate_meta, "CPM", date(2026, 10, 6), date(2026, 10, 7)))

    def test_automatic_q4_catalog_excludes_missing_rate_but_manual_catalog_can_fallback(self):
        repo = object.__new__(BigQueryRepository)
        repo.settings = SimpleNamespace(slot_data_table="project.dataset.slots")
        repo._query_records = Mock(return_value=[
            {"country": "eg", "slot_code": "noon_eg_upper_mid_page_2", "slot_name": "Upper Mid", "type": "CPM"},
        ])
        repo._fetch_booked_cpd_slot_keys = Mock(return_value=set())
        repo._fetch_recent_booked_views = Mock(return_value={
            ("eg", "noon_eg_upper_mid_page_2"): 100,
        })
        calls = []

        def rate_map(_start, _end, *, allow_q4_legacy_fallback=False):
            calls.append(allow_q4_legacy_fallback)
            if not allow_q4_legacy_fallback:
                return {}, {}
            return {
                ("eg", "noon_eg_upper_mid_page_2"): {
                    "cpm_rate": 5,
                    "pricing_options": ["CPM"],
                    "cpm_rate_schedule": {},
                    "cpd_rate_schedule": {},
                }
            }, {}

        repo._fetch_rate_card_map = rate_map
        req = MediaPlanRequest.model_validate({
            "brand": "Test", "comcats": ["Mobiles"], "countries": ["eg"],
            "start_date": date(2026, 10, 6), "end_date": date(2026, 10, 7),
            "budget": 5_000, "currency": "USD", "objective": "reach",
        })

        self.assertEqual(repo.fetch_slot_catalog(req, enforce_eligibility=True), [])
        manual_catalog = repo.fetch_slot_catalog(req, enforce_eligibility=False)
        self.assertEqual(len(manual_catalog), 1)
        self.assertTrue(manual_catalog[0]["rate_available"])
        self.assertEqual(manual_catalog[0]["cpm_rate"], 5)
        self.assertEqual(calls, [False, True])

    def test_q3_conflicting_constant_rates_are_not_blended(self):
        repo = object.__new__(BigQueryRepository)
        repo.settings = SimpleNamespace(
            slot_rate_card_table="project.dataset.rate_card_q3",
            slot_rate_card_q4_2026_table="",
        )
        repo._query_records = Mock(return_value=[
            {"slot_code": "home_hero", "country": "ae", "cpm_rate": 10},
            {"slot_code": "home_hero", "country": "ae", "cpm_rate": 20},
        ])

        by_country_slot, _by_slot = repo._fetch_rate_card_map(date(2026, 9, 1), date(2026, 9, 2))

        # A missing price is safer than pricing the placement at the invented
        # average of two conflicting official records.
        self.assertEqual(by_country_slot[("ae", "home_hero")]["cpm_rate"], 0.0)
        self.assertEqual(by_country_slot[("ae", "home_hero")]["pricing_options"], [])

    def test_uses_new_q4_schema_and_keeps_max_duplicate_rate_per_day(self):
        repo = object.__new__(BigQueryRepository)
        repo.settings = SimpleNamespace(
            slot_rate_card_table="project.dataset.rate_card_legacy",
            slot_rate_card_q4_2026_table="project.dataset.rate_card_q4_2026",
        )

        legacy_rows = [
            {"slot_code": "home_hero", "date": "2026-09-30", "country": "ae", "cpm_rate": 10},
        ]
        q4_rows = [
            {"slot": "home_hero", "date": "2026-10-01", "country": "ae", "marketplace": "noon", "type": "cpm", "rate": 15},
            {"slot": "home_hero", "date": "2026-10-01", "country": "ae", "marketplace": "noon", "type": "cpm", "rate": 19},
            {"slot": "home_hero", "date": "2026-10-02", "country": "ae", "marketplace": "noon", "type": "cpd", "rate": 500},
        ]

        repo._query_records = Mock(return_value=legacy_rows)
        repo._table_records_for_window = Mock(return_value=q4_rows)

        by_country_slot, by_slot = repo._fetch_rate_card_map(date(2026, 9, 30), date(2026, 10, 2))

        self.assertEqual(
            repo._table_records_for_window.call_args.args[:3],
            ("project.dataset.rate_card_q4_2026", date(2026, 10, 1), date(2026, 10, 2)),
        )
        self.assertIn("project.dataset.rate_card_legacy", repo._query_records.call_args.args[0])
        rates = by_country_slot[("ae", "home_hero")]
        # Q3 is a constant card; only Q4 contributes per-date schedules.
        self.assertEqual(rates["cpm_rate"], 10.0)
        self.assertEqual(rates["cpm_rate_schedule"], {"2026-10-01": 19.0})
        self.assertEqual(rates["cpd_rate_schedule"], {"2026-10-02": 500.0})
        self.assertEqual(rates["pricing_options"], ["CPM", "CPD"])
        self.assertEqual(by_slot["home_hero"]["cpm_rate_schedule"]["2026-10-01"], 19.0)

    def test_maps_egypt_country_alias_and_country_prefixed_slot_code(self):
        repo = object.__new__(BigQueryRepository)
        repo.settings = SimpleNamespace(
            slot_rate_card_table="project.dataset.rate_card_legacy",
            slot_rate_card_q4_2026_table="",
        )
        repo._table_records_for_window = Mock(return_value=[
            {"slot_code": "eg_mobile_clp", "date": "2026-09-30", "country_code": "Egypt", "cpm_rate": 12},
        ])
        repo._query_records = Mock(return_value=[
            {"slot_code": "eg_mobile_clp", "date": "2026-09-30", "country_code": "Egypt", "cpm_rate": 12},
        ])

        by_country_slot, _by_slot = repo._fetch_rate_card_map(date(2026, 9, 30), date(2026, 9, 30))

        self.assertEqual(by_country_slot[("eg", "mobile_clp")]["cpm_rate"], 12.0)


if __name__ == "__main__":
    unittest.main()
