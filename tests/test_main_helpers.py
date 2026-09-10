from datetime import date, timedelta
import unittest
from unittest.mock import Mock, patch

from main import refresh_regeneration_selection, regenerate_media_plan
from models import MediaPlanRequest


class RegenerationHelpersTest(unittest.TestCase):
    def make_request(self):
        start = date.today() + timedelta(days=2)
        return MediaPlanRequest.model_validate({
            "brand": "Test",
            "comcats": ["Mobiles"],
            "countries": ["ae"],
            "start_date": start,
            "end_date": start + timedelta(days=3),
            "budget": 5000,
            "currency": "USD",
            "objective": "both",
        })

    def test_regeneration_removes_exclusions_and_adds_fresh_replacements(self):
        request = self.make_request()
        request = request.model_copy(update={
            "selected_slot_keys": ["ae|deleted", "ae|retained"],
            "manual_slot_keys": ["ae|retained"],
            "selected_slot_pricing": {"ae|deleted": "CPM", "ae|retained": "CPD"},
            "foc_slot_keys": ["ae|deleted"],
            "excluded_slot_keys": ["ae|deleted"],
        })

        refresh_regeneration_selection(request, [
            {"slot_key": "ae|deleted", "pricing_model": "CPM"},
            {"slot_key": "ae|replacement", "pricing_model": "CPM"},
        ])

        self.assertEqual(request.selected_slot_keys, ["ae|retained", "ae|replacement"])
        self.assertEqual(request.manual_slot_keys, ["ae|retained"])
        self.assertEqual(request.foc_slot_keys, [])
        self.assertEqual(request.selected_slot_pricing, {"ae|retained": "CPD", "ae|replacement": "CPM"})

    def test_regeneration_saves_a_new_revision_instead_of_overwriting_streamed_rows(self):
        request = self.make_request()
        repo = Mock()
        repo.infer_brand_tag.return_value = "new"
        repo.fetch_historical_performance.return_value = []
        repo.fetch_inventory.return_value = []
        repo.fetch_slot_meta.return_value = {}
        generated_row = Mock(cost=5000)
        with (
            patch("main.suggest_slots", return_value=[]),
            patch("main.plan_media", return_value=([generated_row], {})),
            patch("main.build_response", return_value={"rows": [], "summary": {}, "diagnostics": {}}) as build,
        ):
            regenerate_media_plan("MP-ORIGINAL", request, settings=Mock(), repo=repo)

        self.assertIsNone(build.call_args.kwargs.get("plan_id"))
        self.assertEqual(build.call_args.args[2]["regenerated_from"], "MP-ORIGINAL")


if __name__ == "__main__":
    unittest.main()
