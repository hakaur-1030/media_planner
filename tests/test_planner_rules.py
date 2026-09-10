from datetime import date, timedelta
from types import SimpleNamespace
import unittest

from models import MediaPlanRequest
from planner import (
    Candidate,
    MIN_CPD_BUDGET_USD,
    _date_exposure_weights,
    _objective_diverse_order,
    _placement_kind,
    _slot_values_relevance_for_comcat,
    campaign_duration_days,
    plan_media,
    suggest_slots,
)


def candidate(code: str, page: str, category: str, score: float = 0.7) -> Candidate:
    return Candidate(
        country="ae", slot_code=code, slot_name=code, page=page, category=category,
        zone=code, dimension="", marketplace="supermall" if "supermall" in code else "core",
        publisher=page, pricing_model="CPM", slot_rate=10.0, views=1_000_000,
        clicks=10_000, revenue=50_000, spends=10_000, active_days=30,
        brand_specific=True, reach_score=score, conv_score=score,
        visibility_score=score, ctr_score=score, roas_score=score,
        brand_score=score, comcat_score=score, trend_score=score,
        confidence_score=1.0, final_score=score, cpm=10.0, cpd=None,
        ctr=0.01, roas=5.0,
    )


class PlannerRulesTest(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(
            min_slot_views=1_000,
            default_cpm=10.0,
            default_cpd=1_000.0,
            max_lines_per_phase=6,
            min_total_lines=6,
        )

    def request(self, budget: float = 10_000, objective: str = "roas") -> MediaPlanRequest:
        start = date.today() + timedelta(days=2)
        return MediaPlanRequest.model_validate({
            "brand": "Test Brand", "comcats": ["Mobiles"], "countries": ["ae"],
            "marketplace": "both", "marketplace_core_pct": 60,
            "marketplace_supermall_pct": 40, "start_date": start,
            "end_date": start + timedelta(days=9), "budget": budget, "currency": "USD",
            "objective": objective,
            "phases": [
                {"name": "Launch", "from": start, "to": start + timedelta(days=2)},
                {"name": "Sustain", "from": start + timedelta(days=3), "to": start + timedelta(days=9)},
            ],
            "phase_budget_splits": {"Launch": 30, "Sustain": 70},
        })

    def test_objective_order_keeps_secondary_placement_family(self):
        home = candidate("home_page_hero", "Home Page", "Home Page", 0.8)
        clp = candidate("mobile_clp_banner", "CLP", "Mobiles", 0.8)
        other = candidate("mobile_pdp_banner", "PDP", "Mobiles", 0.8)
        roas_order = _objective_diverse_order([home, clp, other], "roas")
        reach_order = _objective_diverse_order([home, clp, other], "reach")
        self.assertEqual(_placement_kind(roas_order[0]), "clp")
        self.assertEqual(_placement_kind(reach_order[0]), "homepage")
        self.assertEqual({_placement_kind(row) for row in roas_order}, {"homepage", "clp", "other"})

    def test_nine_am_flight_counts_one_day_and_keeps_end_date_views(self):
        start = date(2026, 8, 21)
        end = date(2026, 8, 22)
        self.assertEqual(campaign_duration_days(start, end), 1)
        weights = _date_exposure_weights(start, end)
        self.assertEqual(weights, [15 / 24, 9 / 24])
        self.assertEqual(sum(weights), 1.0)
        self.assertGreater(weights[-1], 0)

    def test_category_matching_allows_homepage_but_rejects_wrong_clp(self):
        self.assertGreater(_slot_values_relevance_for_comcat("Home Page", "Home Page", "hp_hero", "Hero", "Mobiles"), 0)
        self.assertGreater(_slot_values_relevance_for_comcat("Mobiles", "CLP", "mobile_clp", "Mobile CLP", "Mobiles"), 0)
        self.assertEqual(_slot_values_relevance_for_comcat("Cameras", "CLP", "camera_clp", "Camera CLP", "Mobiles"), 0)

    def test_clp_cpd_is_allowed_below_threshold(self):
        req = self.request(MIN_CPD_BUDGET_USD - 1)
        historical = [{
            "country": "ae", "slot_code": "mobile_clp", "views": 100_000,
            "clicks": 1_000, "spends": 1_000, "revenue": 5_000, "active_days": 10,
        }]
        meta = {("ae", "mobile_clp"): {
            "slot_code": "mobile_clp", "slot_name": "Mobile CLP", "page": "CLP",
            "category": "Mobiles", "zone": "top", "pricing_options": ["CPM", "CPD"],
            "cpm_rate": 10, "cpd_rate": 500,
        }}
        inventory = [
            {"dt": req.start_date + timedelta(days=i), "country": "ae", "slot_code": "mobile_clp", "available_views": 100_000}
            for i in range(10)
        ]
        suggestions = suggest_slots(req, historical, inventory, meta, self.settings)
        self.assertTrue(suggestions)
        self.assertIn("CPD", suggestions[0]["pricing_options"])

    def test_homepage_cpd_is_not_suggested_below_threshold(self):
        req = self.request(MIN_CPD_BUDGET_USD - 1)
        historical = [{
            "country": "ae", "slot_code": "home_page_hero", "views": 100_000,
            "clicks": 1_000, "spends": 1_000, "revenue": 5_000, "active_days": 10,
        }]
        meta = {("ae", "home_page_hero"): {
            "slot_code": "home_page_hero", "slot_name": "Homepage Hero", "page": "Home Page",
            "category": "Home Page", "zone": "top", "pricing_options": ["CPM", "CPD"],
            "cpm_rate": 10, "cpd_rate": 500,
        }}
        inventory = [
            {"dt": req.start_date + timedelta(days=i), "country": "ae", "slot_code": "home_page_hero", "available_views": 100_000}
            for i in range(10)
        ]
        suggestions = suggest_slots(req, historical, inventory, meta, self.settings)
        self.assertTrue(suggestions)
        self.assertEqual(suggestions[0]["pricing_options"], ["CPM"])

    def test_manual_slot_can_override_backend_category_rules(self):
        req = self.request(10_000)
        key = "ae|camera_manual_cpd"
        req.selected_slot_keys = [key]
        req.manual_slot_keys = [key]
        req.selected_slot_pricing = {key: "CPD"}
        meta = {("ae", "camera_manual_cpd"): {
            "slot_code": "camera_manual_cpd", "slot_name": "Camera manual CPD",
            "page": "PDP", "category": "Cameras", "zone": "manual",
            "pricing_options": ["CPD"], "cpd_rate": 500,
        }}
        inventory = [
            {"dt": req.start_date + timedelta(days=i), "country": "ae", "slot_code": "camera_manual_cpd", "available_views": 50_000}
            for i in range(10)
        ]
        rows, _diagnostics = plan_media(req, [], inventory, meta, self.settings)
        self.assertTrue(rows)
        self.assertEqual(rows[0].buyType, "CPD")

    def test_manual_homepage_cpd_can_override_budget_threshold(self):
        req = self.request(MIN_CPD_BUDGET_USD - 1)
        key = "ae|home_page_manual_cpd"
        req.selected_slot_keys = [key]
        req.manual_slot_keys = [key]
        req.selected_slot_pricing = {key: "CPD"}
        meta = {("ae", "home_page_manual_cpd"): {
            "slot_code": "home_page_manual_cpd", "slot_name": "Homepage manual CPD",
            "page": "Home Page", "category": "Home Page", "zone": "manual",
            "pricing_options": ["CPD"], "cpd_rate": 500,
        }}
        inventory = [
            {"dt": req.start_date + timedelta(days=i), "country": "ae", "slot_code": "home_page_manual_cpd", "available_views": 50_000}
            for i in range(10)
        ]
        rows, _diagnostics = plan_media(req, [], inventory, meta, self.settings)
        self.assertTrue(rows)
        self.assertEqual(rows[0].buyType, "CPD")

    def test_omitted_slot_reports_inventory_constraint_not_false_budget_error(self):
        req = self.request()
        good_key = "ae|mobile_clp"
        missing_key = "ae|home_page_missing"
        req.selected_slot_keys = [good_key, missing_key]
        req.selected_slot_pricing = {good_key: "CPM", missing_key: "CPM"}
        historical = [{
            "country": "ae", "slot_code": "mobile_clp", "views": 100_000,
            "clicks": 1_000, "spends": 1_000, "revenue": 5_000, "active_days": 10,
        }]
        meta = {
            ("ae", "mobile_clp"): {"slot_code": "mobile_clp", "slot_name": "Mobile CLP", "page": "CLP", "category": "Mobiles", "zone": "top", "pricing_options": ["CPM"], "cpm_rate": 10},
            ("ae", "home_page_missing"): {"slot_code": "home_page_missing", "slot_name": "Missing homepage", "page": "Home Page", "category": "Home Page", "zone": "hero", "pricing_options": ["CPM"], "cpm_rate": 10},
        }
        inventory = [
            {"dt": req.start_date + timedelta(days=i), "country": "ae", "slot_code": "mobile_clp", "available_views": 100_000}
            for i in range(10)
        ]
        rows, diagnostics = plan_media(req, historical, inventory, meta, self.settings)
        self.assertTrue(rows)
        omitted = next(item for item in diagnostics["omitted_selected_slots"] if item["slot_key"] == missing_key)
        self.assertIn("No available forecast views", omitted["reason"])
        self.assertNotIn("needs at least", omitted["reason"])

    def test_plan_uses_budget_and_tracks_requested_splits(self):
        req = self.request()
        definitions = [
            ("home_page_hero", "Home Page", "Home Page"),
            ("mobile_clp", "CLP", "Mobiles"),
            ("supermall_home_page_hero", "Home Page", "Home Page"),
            ("supermall_mobile_clp", "CLP", "Mobiles"),
        ]
        historical, meta, inventory = [], {}, []
        for code, page, category in definitions:
            historical.append({
                "country": "ae", "slot_code": code, "views": 1_000_000,
                "clicks": 10_000, "spends": 10_000, "revenue": 50_000,
                "active_days": 30, "roas_pagecomcat": 5,
            })
            meta[("ae", code)] = {
                "slot_code": code, "slot_name": code, "page": page, "category": category,
                "zone": code, "pricing_options": ["CPM", "CPD"],
                "cpm_rate": 10, "cpd_rate": 500,
            }
            inventory.extend(
                {"dt": req.start_date + timedelta(days=i), "country": "ae", "slot_code": code, "available_views": 200_000}
                for i in range(10)
            )

        req.selected_slot_keys = [f"ae|{code}" for code, _page, _category in definitions]
        req.selected_slot_pricing = {key: "CPM" for key in req.selected_slot_keys}

        rows, diagnostics = plan_media(req, historical, inventory, meta, self.settings)
        self.assertTrue(rows)
        self.assertTrue(all(row.buyType != "CPD" for row in rows))
        self.assertTrue(any("home" in f"{row.page} {row.category}".lower() for row in rows))
        self.assertTrue(any("clp" in f"{row.page} {row.slot_code}".lower() for row in rows))
        self.assertGreaterEqual(diagnostics["budget_utilization_pct"], 95)
        self.assertLessEqual(abs(diagnostics["actual_phase_budget_split"]["Launch"] - 30), 5)
        self.assertLessEqual(abs(diagnostics["actual_marketplace_budget_split"]["core"] - 60), 5)


if __name__ == "__main__":
    unittest.main()
