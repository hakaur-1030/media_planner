from datetime import date, timedelta
from types import SimpleNamespace
import unittest

from models import EditablePlanLine, MediaPlanRequest, Phase
from planner import (
    Candidate,
    MAX_SLOT_BUDGET_SHARE,
    MIN_CPD_BUDGET_USD,
    _date_exposure_weights,
    _cpd_day_weights,
    _campaign_diverse_order,
    _objective_diverse_order,
    maximum_slot_budget,
    marketplace_from_slot,
    _placement_kind,
    _repair_daily_continuity,
    split_rows_at_rate_changes,
    _slot_values_relevance_for_comcat,
    campaign_duration_days,
    plan_media,
    service_window_dates,
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

    def test_supermall_slots_are_exempt_from_the_core_per_slot_budget_cap(self):
        req = self.request(budget=10_000)

        self.assertEqual(maximum_slot_budget(req, "core"), 10_000 * MAX_SLOT_BUDGET_SHARE)
        self.assertEqual(maximum_slot_budget(req, "supermall"), 10_000)

    def test_campaign_diversity_prefers_unused_generated_slots_but_not_manual_slots(self):
        used = candidate("used_home", "Home Page", "Home Page", 0.9)
        unused = candidate("unused_clp", "CLP", "Mobiles", 0.8)
        manual = candidate("manual_home", "Home Page", "Home Page", 0.7)
        ordered = _campaign_diverse_order(
            [used, unused, manual],
            {"ae|used_home", "ae|manual_home"},
            {"ae|manual_home"},
        )
        self.assertEqual([row.slot_code for row in ordered], ["unused_clp", "manual_home", "used_home"])

    def test_rate_change_splits_a_cpm_plan_line_without_changing_totals(self):
        row = EditablePlanLine.model_validate({
            "id": 7, "from": date(2026, 10, 1), "to": date(2026, 10, 3),
            "country": "ae", "page": "Home", "asset": "Home hero", "slot_name": "Home hero",
            "days": 2, "buyType": "CPM", "rate": 15, "gross_cpm": 15, "net_cpm": 15,
            "views": 4_000, "cost": 53.75, "gross_amount": 53.75, "net_amount": 53.75,
            "phase": "Launch", "brand": "Test", "stype": "reach", "slot_code": "home_hero",
        })
        meta = {
            ("ae", "home_hero"): {
                "slot_code": "home_hero", "cpm_rate": 15,
                "cpm_rate_schedule": {"2026-10-01": 10, "2026-10-02": 15, "2026-10-03": 15},
            }
        }

        split = split_rows_at_rate_changes([row], meta, discount_pct=0)

        self.assertEqual(len(split), 2)
        self.assertEqual([(item.from_date, item.to_date, item.gross_cpm) for item in split], [
            (date(2026, 10, 1), date(2026, 10, 2), 10),
            (date(2026, 10, 2), date(2026, 10, 3), 15),
        ])
        self.assertEqual(sum(item.views or 0 for item in split), 4_000)
        self.assertEqual(sum(item.cost for item in split), 53.75)
        self.assertEqual(sum(item.gross_amount for item in split), 53.75)

    def test_rate_change_splits_a_cpd_plan_line_without_changing_totals(self):
        row = EditablePlanLine.model_validate({
            "id": 8, "from": date(2026, 10, 1), "to": date(2026, 10, 3),
            "country": "ae", "page": "Home", "asset": "Home hero", "slot_name": "Home hero",
            "days": 2, "buyType": "CPD", "rate": 200, "views": 1_000,
            "cost": 300, "gross_amount": 300, "net_amount": 300,
            "phase": "Launch", "brand": "Test", "stype": "reach", "slot_code": "home_hero",
        })
        meta = {
            ("ae", "home_hero"): {
                "slot_code": "home_hero", "cpd_rate": 200,
                "cpd_rate_schedule": {"2026-10-01": 100, "2026-10-02": 200},
            }
        }

        split = split_rows_at_rate_changes([row], meta, discount_pct=0)

        self.assertEqual([(item.from_date, item.to_date, item.rate) for item in split], [
            (date(2026, 10, 1), date(2026, 10, 2), 100),
            (date(2026, 10, 2), date(2026, 10, 3), 200),
        ])
        self.assertEqual(sum(item.cost for item in split), 300)
        self.assertEqual(sum(item.gross_amount for item in split), 300)

    def test_supermall_slot_code_overrides_legacy_core_metadata(self):
        self.assertEqual(marketplace_from_slot("supermall_ae_sfu_1", "SFU 1", "core"), "supermall")
        self.assertEqual(marketplace_from_slot("sa_noon_supermall_onsite_toggle", "Toggle", None), "supermall")
        self.assertEqual(marketplace_from_slot("footer_promo", "Footer promo", None), "")

    def test_suggestions_are_not_capped_at_the_minimum_slot_count(self):
        req = self.request(5_000)
        historical, meta, inventory = [], {}, []
        for index in range(8):
            code = f"mobile_clp_{index}"
            historical.append({
                "country": "ae", "slot_code": code, "views": 100_000,
                "clicks": 1_000, "spends": 1_000, "revenue": 5_000, "active_days": 10,
            })
            meta[("ae", code)] = {
                "slot_code": code, "slot_name": code, "page": "CLP",
                "category": "Mobiles", "zone": "shared_zone",
                "pricing_options": ["CPM"], "cpm_rate": 10, "marketplace": "core",
            }
            inventory.extend(
                {"dt": req.start_date + timedelta(days=day), "country": "ae", "slot_code": code, "available_views": 100_000}
                for day in range(10)
            )

        suggestions = suggest_slots(req, historical, inventory, meta, self.settings, limit=None)
        self.assertEqual(len(suggestions), 8)
        self.assertTrue(all(slot["rate_available"] for slot in suggestions))

    def test_eligible_supermall_slot_without_delivery_history_is_still_suggested(self):
        req = self.request(5_000)
        historical = [{
            "country": "ae", "slot_code": "mobile_clp_core", "views": 100_000,
            "clicks": 1_000, "spends": 1_000, "revenue": 5_000, "active_days": 10,
        }]
        meta = {
            ("ae", "mobile_clp_core"): {
                "slot_code": "mobile_clp_core", "slot_name": "Core Mobile CLP",
                "page": "CLP", "category": "Mobiles", "zone": "core_hero",
                "pricing_options": ["CPM"], "cpm_rate": 10, "marketplace": "core",
            },
            ("ae", "supermall_ae_mobile_clp"): {
                "slot_code": "supermall_ae_mobile_clp", "slot_name": "Supermall Mobile CLP",
                "page": "CLP", "category": "Mobiles", "zone": "supermall_hero",
                "pricing_options": ["CPM"], "cpm_rate": 10, "marketplace": "supermall",
            },
        }
        inventory = [
            {"dt": req.start_date + timedelta(days=day), "country": "ae", "slot_code": code, "available_views": 100_000}
            for code in ("mobile_clp_core", "supermall_ae_mobile_clp")
            for day in range(10)
        ]

        suggestions = suggest_slots(req, historical, inventory, meta, self.settings, limit=None)

        supermall = [slot for slot in suggestions if slot["marketplace"] == "supermall"]
        self.assertEqual(len(supermall), 1)
        self.assertEqual(supermall[0]["slot_code"], "supermall_ae_mobile_clp")
        self.assertEqual(supermall[0]["confidence_score"], 0.25)

    def test_nine_am_flight_uses_half_open_service_days(self):
        start = date(2026, 8, 21)
        end = date(2026, 8, 22)
        self.assertEqual(campaign_duration_days(start, end), 1)
        self.assertEqual(service_window_dates(start, end), [start])
        weights = _date_exposure_weights(start, end)
        self.assertEqual(weights, [1.0])
        self.assertEqual(sum(weights), 1.0)
        self.assertEqual(_cpd_day_weights(start, end), [1.0])

    def test_phases_may_touch_at_the_same_nine_am_boundary_but_not_overlap(self):
        start = date(2026, 8, 21)
        end = date(2026, 8, 31)
        request = MediaPlanRequest.model_validate({
            "brand": "Test", "comcats": ["Mobiles"], "countries": ["ae"],
            "start_date": start, "end_date": end, "budget": 5_000,
            "currency": "USD", "objective": "reach",
            "phases": [
                {"name": "Launch", "from": start, "to": date(2026, 8, 26)},
                {"name": "Sustain", "from": date(2026, 8, 26), "to": end},
            ],
        })
        self.assertEqual(len(request.phases), 2)

        with self.assertRaises(ValueError):
            MediaPlanRequest.model_validate({
                **request.model_dump(by_alias=True),
                "phases": [{"name": "Empty", "from": start, "to": start}],
            })

        with self.assertRaises(ValueError):
            MediaPlanRequest.model_validate({
                **request.model_dump(by_alias=True),
                "phases": [
                    {"name": "Launch", "from": start, "to": date(2026, 8, 27)},
                    {"name": "Sustain", "from": date(2026, 8, 26), "to": end},
                ],
            })

    def test_continuity_extends_cpm_window_without_changing_spend(self):
        start = date(2026, 9, 21)
        end = date(2026, 9, 26)
        req = MediaPlanRequest.model_validate({
            "brand": "Test", "countries": ["ae"], "start_date": start,
            "end_date": end, "budget": 5_000, "currency": "USD", "objective": "reach",
        })
        row = EditablePlanLine.model_validate({
            "id": 1, "from": start, "to": start + timedelta(days=2),
            "country": "ae", "page": "Home Page", "marketplace": "core",
            "asset": "Hero", "days": 2, "buyType": "CPM", "rate": 10,
            "net_cpm": 10, "views": 100_000, "cost": 1_000,
            "net_amount": 1_000, "phase": "Full flight", "brand": "Test",
            "stype": "reach", "slot_code": "home_hero", "score": 1,
        })
        inventory = [
            {"dt": start + timedelta(days=offset), "country": "ae", "slot_code": "home_hero", "available_views": 100_000}
            for offset in range(6)
        ]

        diagnostics = _repair_daily_continuity(
            req,
            [row],
            [Phase.model_validate({"name": "Full flight", "from": start, "to": end})],
            inventory,
            {("ae", "home_hero"): {"cpm_rate": 10}},
        )

        self.assertEqual(row.to_date, end)
        self.assertEqual(row.cost, 1_000)
        self.assertEqual(diagnostics["continuity_status"], "continuous")

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
            "cpm_rate": 10, "cpd_rate": 500, "marketplace": "core",
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
            "cpm_rate": 10, "cpd_rate": 500, "marketplace": "core",
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
        req = self.request(objective="both")
        req.marketplace_core_pct = 70
        req.marketplace_supermall_pct = 30
        definitions = [
            ("home_page_hero", "Home Page", "Home Page", "core"),
            ("mobile_clp", "CLP", "Mobiles", "core"),
            ("mall_home_page_hero", "Home Page", "Home Page", "supermall"),
            ("mall_mobile_clp", "CLP", "Mobiles", "supermall"),
        ]
        historical, meta, inventory = [], {}, []
        for code, page, category, marketplace in definitions:
            historical.append({
                "country": "ae", "slot_code": code, "views": 1_000_000,
                "clicks": 10_000, "spends": 10_000, "revenue": 50_000,
                "active_days": 30, "roas_pagecomcat": 5,
            })
            meta[("ae", code)] = {
                "slot_code": code, "slot_name": code, "page": page, "category": category,
                "zone": code, "pricing_options": ["CPM", "CPD"],
                "cpm_rate": 10, "cpd_rate": 500, "marketplace": marketplace,
            }
            inventory.extend(
                {"dt": req.start_date + timedelta(days=i), "country": "ae", "slot_code": code, "available_views": 200_000}
                for i in range(10)
            )

        suggestions = suggest_slots(req, historical, inventory, meta, self.settings, limit=4)
        self.assertTrue(any(slot["marketplace"] == "supermall" for slot in suggestions))

        req.selected_slot_keys = [f"ae|{code}" for code, _page, _category, _marketplace in definitions]
        req.selected_slot_pricing = {key: "CPM" for key in req.selected_slot_keys}

        rows, diagnostics = plan_media(req, historical, inventory, meta, self.settings)
        self.assertTrue(rows)
        self.assertTrue(all(row.buyType != "CPD" for row in rows))
        self.assertTrue(any("home" in f"{row.page} {row.category}".lower() for row in rows))
        self.assertTrue(any("clp" in f"{row.page} {row.slot_code}".lower() for row in rows))
        spend_by_slot = {}
        for row in rows:
            key = (row.country, row.slot_code)
            spend_by_slot[key] = spend_by_slot.get(key, 0) + float(row.cost or 0)
        self.assertLessEqual(max(spend_by_slot.values()), req.budget * MAX_SLOT_BUDGET_SHARE + 0.01)
        self.assertGreaterEqual(diagnostics["budget_utilization_pct"], 95)
        self.assertEqual(diagnostics["continuity_budget_margin_usd"], 250)
        self.assertEqual(diagnostics["budget_utilization_target_pct"], 97.5)
        self.assertLessEqual(abs(diagnostics["actual_phase_budget_split"]["Launch"] - 30), 1)
        self.assertLessEqual(abs(diagnostics["actual_marketplace_budget_split"]["core"] - 70), 1)
        self.assertLessEqual(abs(diagnostics["actual_objective_budget_split"]["reach"] - 60), 1)


if __name__ == "__main__":
    unittest.main()
