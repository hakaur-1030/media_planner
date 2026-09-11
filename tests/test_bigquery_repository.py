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
        self.assertIn("`country` IS NOT NULL", sql)
        self.assertIn("TRIM(CAST(`country` AS STRING)) != ''", sql)


if __name__ == "__main__":
    unittest.main()
