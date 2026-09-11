from __future__ import annotations

import csv
import json
import logging
import time
from uuid import uuid4
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.request import urlopen

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from bigquery_repository import BigQueryRepository
from config import Settings, get_settings
from models import MediaPlanRequest, MediaPlanResponse
from planner import plan_media, suggest_slots
from refine import refine_plan_for_roas
from selection_v2 import plan_media_v2, to_editable_rows


app = FastAPI(title="Noon Media Planner API")
BRAND_CODES_PATH = Path(__file__).with_name("brand_codes.csv")
FALLBACK_FX_RATES = {"AED": 3.6725, "SAR": 3.75, "EGP": 50.0}
FX_CACHE: dict[str, object] = {"expires_at": 0.0, "rates": FALLBACK_FX_RATES.copy()}
logger = logging.getLogger("media_planner")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def is_bigquery_error(exc: Exception) -> bool:
    exc_module = type(exc).__module__
    exc_text = str(exc) or type(exc).__name__
    return (
        exc_module.startswith(("google.api_core", "google.cloud.bigquery", "google.auth"))
        or "bigquery" in exc_module.lower()
        or "bigquery" in exc_text.lower()
        or "noonbiadmon." in exc_text.lower()
    )


def support_error_response(
    status_code: int,
    source: str,
    message: str,
    contact: str,
    reference: str,
    technical_detail: str = "",
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": {
                "message": message,
                "source": source,
                "contact": contact,
                "reference": reference,
                "technical_detail": technical_detail[:2000],
            }
        },
    )


@app.exception_handler(RequestValidationError)
def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    reference = uuid4().hex[:10].upper()
    logger.warning("Invalid media planner request [%s] path=%s errors=%s", reference, request.url.path, exc.errors())
    return support_error_response(
        422,
        "input",
        "Some campaign inputs are missing or invalid.",
        "Media Planning support POC",
        reference,
        "; ".join(
            f"{'.'.join(str(part) for part in error.get('loc', []))}: {error.get('msg', 'invalid value')}"
            for error in exc.errors()
        ),
    )


@app.exception_handler(Exception)
def unhandled_exception_handler(request: Request, exc: Exception):
    reference = uuid4().hex[:10].upper()
    logger.error(
        "Unhandled media planner error [%s] path=%s",
        reference,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    if is_bigquery_error(exc):
        return support_error_response(
            503,
            "bigquery",
            "BigQuery is not responding or the application cannot access the required BigQuery data.",
            "Data/BI POC",
            reference,
            f"{type(exc).__name__}: {str(exc) or 'No additional detail'}",
        )
    return support_error_response(
        500,
        "application",
        "The Media Planner encountered an unexpected application error.",
        "Engineering POC",
        reference,
        f"{type(exc).__name__}: {str(exc) or 'No additional detail'}",
    )


def get_repo(settings: Settings = Depends(get_settings)) -> BigQueryRepository:
    return BigQueryRepository(settings)


def gross_budget_from_net(net_amount: float, discount_pct: float) -> float:
    discount_factor = max(1 - (float(discount_pct or 0) / 100), 0.0001)
    return round(float(net_amount or 0) / discount_factor, 2)


def plan_failure_message(diagnostics: dict, fallback: str = "No plan rows generated.") -> str:
    omitted = diagnostics.get("omitted_selected_slots") or []
    if omitted:
        details = "; ".join(
            f"{item.get('slot_name') or item.get('slot_key')}: {item.get('reason') or 'could not be placed'}"
            for item in omitted
        )
        return f"No selected slot could be placed. {details}"
    return diagnostics.get("reason") or fallback


def strict_split_violations(diagnostics: dict, tolerance_pct: float = 1.0) -> list[str]:
    violations = []
    dimensions = (
        ("phase", diagnostics.get("phase_budget_split") or {}, diagnostics.get("actual_phase_budget_split") or {}),
        ("marketplace", diagnostics.get("marketplace_budget_split") or {}, diagnostics.get("actual_marketplace_budget_split") or {}),
        ("objective", diagnostics.get("objective_budget_split") or {}, diagnostics.get("actual_objective_budget_split") or {}),
    )
    for dimension, requested, actual in dimensions:
        for name, target in requested.items():
            actual_value = float(actual.get(name, 0) or 0)
            target_value = float(target or 0)
            if abs(actual_value - target_value) > tolerance_pct:
                violations.append(f"{dimension} '{name}' requested {target_value:.1f}% but received {actual_value:.1f}%")
    return violations


@lru_cache(maxsize=1)
def load_static_brand_codes() -> tuple[str, ...]:
    if not BRAND_CODES_PATH.exists():
        return tuple()
    with BRAND_CODES_PATH.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        values = {
            str(row.get("brand_code") or "").strip()
            for row in reader
            if str(row.get("brand_code") or "").strip()
        }
    return tuple(sorted(values, key=str.lower))


def search_static_brand_codes(query: str, limit: int = 30) -> list[str]:
    q = str(query or "").strip().lower()
    if len(q) < 2:
        return []
    starts_with = []
    contains = []
    for code in load_static_brand_codes():
        lowered = code.lower()
        if lowered.startswith(q):
            starts_with.append(code)
        elif q in lowered:
            contains.append(code)
        if len(starts_with) >= limit:
            break
    remaining = max(limit - len(starts_with), 0)
    return starts_with + contains[:remaining]


def build_response(req: MediaPlanRequest, rows, diagnostics, repo, plan_id=None):
    allocated = round(sum(row.cost for row in rows), 2)
    offdeck_allocated = round(sum(row.cost for row in rows if str(row.buyType or "").upper() == "OFF-DECK"), 2)
    on_deck_allocated = round(allocated - offdeck_allocated, 2)
    net_budget = float((req.budget or 0) + (req.offdeck_budget or 0))
    gross_budget = float(req.total_budget or gross_budget_from_net(net_budget, req.discount_pct))
    on_deck_rows = [row for row in rows if str(row.buyType or "").upper() != "OFF-DECK"]
    views = sum(row.views or 0 for row in on_deck_rows)
    weighted_ctr_den = sum(max(row.views or 0, 0) for row in on_deck_rows)
    weighted_roas_den = sum(max(float(row.cost or row.net_amount or 0), 0.0) for row in on_deck_rows)
    expected_ctr = (
        sum((row.historical_ctr or 0.0) * max(row.views or 0, 0) for row in on_deck_rows) / weighted_ctr_den
        if weighted_ctr_den > 0 else 0.0
    )
    expected_roas = (
        sum((row.historical_roas or 0.0) * max(float(row.cost or row.net_amount or 0), 0.0) for row in on_deck_rows) / weighted_roas_den
        if weighted_roas_den > 0 else 0.0
    )
    confidence_values = [float(item.get("confidence_score") or 0.0) for item in diagnostics.get("suggested_slots", []) if isinstance(item, dict)]
    if not confidence_values:
        confidence_values = [min(max(float(getattr(row, "score", 0.0) or 0.0), 0.0), 1.0) for row in rows if getattr(row, "score", None) is not None]
    overall_confidence = round((sum(confidence_values) / len(confidence_values)) * 100, 1) if confidence_values else 0.0
    summary = {
        "brand": req.brand,
        "comcats": req.comcats,
        "countries": req.countries,
        "budget": req.budget,
        "total_budget": gross_budget,
        "net_budget": net_budget,
        "on_deck_budget": req.budget,
        "offdeck_budget": req.offdeck_budget,
        "discount_pct": req.discount_pct,
        "allocated": allocated,
        "on_deck_allocated": on_deck_allocated,
        "offdeck_allocated": offdeck_allocated,
        "remaining": round(net_budget - allocated, 2),
        "estimated_views": views,
        "line_count": len(rows),
        "expected_ctr": round(expected_ctr, 4),
        "expected_roas": round(expected_roas, 4),
        "expected_reach": views,
        "overall_confidence": overall_confidence,
    }

    sheet_plan_code, sheet_plan_link = repo.save_plan(
        req,
        rows,
        summary,
        diagnostics,
        plan_code=plan_id,
    )
    summary["sheet_plan_code"] = sheet_plan_code
    summary["sheet_plan_link"] = sheet_plan_link
    summary["plan_id"] = sheet_plan_code
    return {"rows": rows, "summary": summary, "diagnostics": diagnostics}


def build_available_slots(req: MediaPlanRequest, inventory_rows, slot_meta, include_zero: bool = False):
    meta_by_normalized_key = {
        (country, str(slot_code or "").strip().lower()): meta
        for (country, slot_code), meta in slot_meta.items()
    }
    available_by_slot = {}
    for row in inventory_rows:
        available = max(int(row.get("available_views") or 0), 0)
        if available <= 0:
            continue
        country = row.get("country") or ""
        slot_code = row.get("slot_code") or ""
        meta = meta_by_normalized_key.get((country, str(slot_code).strip().lower()))
        if not country or not slot_code or not meta:
            continue
        key = (country, meta.get("slot_code") or slot_code)
        available_by_slot[key] = available_by_slot.get(key, 0) + available

    catalog_keys = set(available_by_slot)
    if include_zero:
        selected_countries = {str(country or "").lower() for country in req.countries}
        catalog_keys.update(
            (country, meta.get("slot_code") or slot_code)
            for (country, slot_code), meta in slot_meta.items()
            if not selected_countries or str(country or "").lower() in selected_countries
        )

    available_slots = []
    for key in catalog_keys:
        available = available_by_slot.get(key, 0)
        meta = meta_by_normalized_key.get((key[0], str(key[1]).strip().lower()), {})
        cpm_rate = float(meta.get("cpm_rate") or 0) or 0.0
        cpd_rate = float(meta.get("cpd_rate") or 0) or 0.0
        slot_name = str(meta.get("slot_name") or key[1]).strip()
        available_slots.append(
            {
                "country": key[0],
                "slot_code": key[1],
                "slot_name": slot_name,
                "page": str(meta.get("page") or meta.get("publisher") or "").strip(),
                "category": str(meta.get("category") or meta.get("page") or "").strip(),
                "zone": str(meta.get("zone") or "").strip(),
                "dimension": str(meta.get("dimension") or "").strip(),
                "publisher": str(meta.get("publisher") or "").strip(),
                "marketplace": str(meta.get("marketplace") or "").strip().lower(),
                "type": str(meta.get("type") or meta.get("pricing_model") or "CPM").strip(),
                "pricing_model": str(meta.get("pricing_model") or "CPM").strip(),
                "pricing_options": list(meta.get("pricing_options") or [str(meta.get("pricing_model") or "CPM").strip()]),
                "rate": float(meta.get("rate") or 0) or 0.0,
                "cpm_rate": cpm_rate,
                "cpd_rate": cpd_rate,
                "available_views": available,
            }
        )
    available_slots.sort(key=lambda slot: (slot["country"], -slot["available_views"], slot["slot_name"].lower()))
    return available_slots


def merge_manual_slot_inputs(req: MediaPlanRequest, repo: BigQueryRepository, inventory_rows, slot_meta):
    manual_keys = {str(value or "").strip().lower() for value in req.manual_slot_keys if str(value or "").strip()}
    if not manual_keys:
        return inventory_rows, slot_meta
    unrestricted_meta = repo.fetch_slot_meta(req, enforce_eligibility=False)
    unrestricted_inventory = repo.fetch_inventory(req, enforce_eligibility=False)
    merged_meta = dict(slot_meta)
    for (country, slot_code), meta in unrestricted_meta.items():
        if f"{country}|{slot_code}".lower() in manual_keys:
            merged_meta[(country, slot_code)] = meta
    existing_inventory_keys = {
        (row.get("dt"), str(row.get("country") or "").lower(), str(row.get("slot_code") or "").lower())
        for row in inventory_rows
    }
    merged_inventory = list(inventory_rows)
    for row in unrestricted_inventory:
        manual_key = f"{row.get('country') or ''}|{row.get('slot_code') or ''}".lower()
        inventory_key = (row.get("dt"), str(row.get("country") or "").lower(), str(row.get("slot_code") or "").lower())
        if manual_key in manual_keys and inventory_key not in existing_inventory_keys:
            merged_inventory.append(row)
            existing_inventory_keys.add(inventory_key)
    return merged_inventory, merged_meta


def refresh_regeneration_selection(req: MediaPlanRequest, suggestions: list[dict]) -> None:
    excluded = {str(key or "").strip() for key in req.excluded_slot_keys if str(key or "").strip()}
    retained = [key for key in req.selected_slot_keys if key and key not in excluded]
    retained_set = set(retained)
    req.manual_slot_keys = [key for key in req.manual_slot_keys if key in retained_set]
    req.foc_slot_keys = [key for key in req.foc_slot_keys if key in retained_set]
    req.selected_slot_pricing = {
        key: value
        for key, value in req.selected_slot_pricing.items()
        if key in retained_set
    }
    for slot in suggestions:
        key = str(slot.get("slot_key") or "").strip()
        if not key or key in excluded or key in retained_set:
            continue
        retained.append(key)
        retained_set.add(key)
        req.selected_slot_pricing[key] = str(slot.get("pricing_model") or "CPM")
    req.selected_slot_keys = retained


@app.get("/")
def index():
    return FileResponse("noon_media_planner.html", headers={"Cache-Control": "no-store"})


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/options")
def list_options(repo: BigQueryRepository = Depends(get_repo)):
    return {
        "countries": ["ae", "sa", "eg"],
        "comcats": repo.list_comcats(),
        "slots": repo.fetch_slot_catalog(),
    }


@app.get("/api/fx-rates")
def fx_rates():
    now = time.time()
    if float(FX_CACHE.get("expires_at") or 0) > now:
        return {"base": "USD", "rates": FX_CACHE["rates"], "source": "cache"}
    try:
        with urlopen("https://open.er-api.com/v6/latest/USD", timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8"))
        source_rates = payload.get("rates") or {}
        rates = {
            currency: float(source_rates.get(currency) or FALLBACK_FX_RATES[currency])
            for currency in FALLBACK_FX_RATES
        }
        FX_CACHE.update({"expires_at": now + 3600, "rates": rates})
        return {"base": "USD", "rates": rates, "source": "open.er-api.com"}
    except Exception:
        FX_CACHE.update({"expires_at": now + 600, "rates": FALLBACK_FX_RATES.copy()})
        return {"base": "USD", "rates": FALLBACK_FX_RATES.copy(), "source": "fallback"}


@app.get("/api/brand-codes/search")
def search_brand_codes(q: str = "", limit: int = 30):
    return {
        "brand_codes": search_static_brand_codes(q, max(1, min(int(limit or 30), 50))),
    }


@app.post("/api/slot-preselection")
def slot_preselection(req: MediaPlanRequest, settings: Settings = Depends(get_settings), repo: BigQueryRepository = Depends(get_repo)):
    req.brand_tag = req.brand_tag or repo.infer_brand_tag(req)
    historical_rows = repo.fetch_historical_performance(req)
    inventory_rows = repo.fetch_inventory(req)
    slot_meta = repo.fetch_slot_meta(req)
    minimum_slot_count = max(len(req.countries), 1) * (6 if req.budget <= 10000 else 10)
    suggestion_pool = suggest_slots(req, historical_rows, inventory_rows, slot_meta, settings, limit=None)
    available_slots = build_available_slots(req, inventory_rows, slot_meta)
    manual_inventory_rows = repo.fetch_inventory(req, enforce_eligibility=False)
    manual_slot_meta = repo.fetch_slot_meta(req, enforce_eligibility=False)
    manual_available_slots = build_available_slots(req, manual_inventory_rows, manual_slot_meta, include_zero=True)
    offdeck_slots = repo.fetch_offdeck_slots(req, enforce_eligibility=False)
    preview_rows = []
    preview_diagnostics = {}
    suggestion_count = min(minimum_slot_count, len(suggestion_pool))
    suggestions = suggestion_pool[:suggestion_count]
    while suggestions:
        preview_req = req.model_copy(deep=True)
        preview_req.selected_slot_keys = [slot["slot_key"] for slot in suggestions]
        preview_req.manual_slot_keys = []
        preview_req.selected_slot_pricing = {
            slot["slot_key"]: slot.get("pricing_model") or "CPM"
            for slot in suggestions
        }
        preview_rows, preview_diagnostics = plan_media(preview_req, historical_rows, inventory_rows, slot_meta, settings)
        if (
            float(preview_diagnostics.get("budget_utilization_pct") or 0) >= 95.0
            or len(suggestions) >= len(suggestion_pool)
        ):
            break
        suggestion_count = min(len(suggestions) + max(len(req.countries), 1), len(suggestion_pool))
        suggestions = suggestion_pool[:suggestion_count]
    preview_spend_by_slot: dict[str, float] = {}
    for row in preview_rows:
        key = f"{row.country}|{row.slot_code}"
        preview_spend_by_slot[key] = preview_spend_by_slot.get(key, 0.0) + float(row.cost or 0)
    for slot in suggestions:
        slot["preview_spend"] = round(preview_spend_by_slot.get(slot["slot_key"], 0.0), 2)
    return {
        "suggestions": suggestions,
        "available_slots": available_slots,
        "manual_available_slots": manual_available_slots,
        "offdeck_slots": offdeck_slots,
        "budget_preview": {
            "allocated": round(sum(float(row.cost or 0) for row in preview_rows), 2),
            "budget": req.budget,
            "utilization_pct": preview_diagnostics.get("budget_utilization_pct", 0.0),
        },
        "diagnostics": {
            "historical_rows": len(historical_rows),
            "inventory_rows": len(inventory_rows),
            "selected_countries": req.countries,
            "selected_comcats": req.comcats,
            "brand_tag": req.brand_tag,
            "recommended_slot_count": len(suggestions),
            "eligible_suggestion_pool_count": len(suggestion_pool),
        },
    }


@app.post("/api/media-plan", response_model=MediaPlanResponse)
def create_media_plan(req: MediaPlanRequest, engine: str = "v1", settings: Settings = Depends(get_settings), repo: BigQueryRepository = Depends(get_repo)):
    if req.end_date < req.start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    if req.start_date < date.today():
        raise HTTPException(status_code=400, detail="start_date must be today or later")
    if req.budget <= 0:
        raise HTTPException(status_code=400, detail="on-deck budget must be positive")
    req.total_budget = gross_budget_from_net(req.budget + req.offdeck_budget, req.discount_pct)
    if not req.comcats:
        raise HTTPException(status_code=400, detail="select at least one comcat")
    if not req.countries:
        raise HTTPException(status_code=400, detail="select at least one country")
    if any(c.lower() not in {"ae", "sa", "eg"} for c in req.countries):
        raise HTTPException(status_code=400, detail="countries must be selected from ae, sa, eg")

    req.brand_tag = req.brand_tag or repo.infer_brand_tag(req)
    historical_rows = repo.fetch_historical_performance(req)
    inventory_rows = repo.fetch_inventory(req)
    slot_meta = repo.fetch_slot_meta(req)
    inventory_rows, slot_meta = merge_manual_slot_inputs(req, repo, inventory_rows, slot_meta)

    if str(engine).lower() == "v2":
        v2_rows, diagnostics = plan_media_v2(req, historical_rows, inventory_rows, slot_meta, settings)
        rows = to_editable_rows(v2_rows, req)
        diagnostics.update({"selected_comcats": req.comcats, "selected_countries": req.countries, "brand_tag": req.brand_tag, "engine": "v2"})
        if not rows:
            raise HTTPException(status_code=422, detail={"message": plan_failure_message(diagnostics, "No plan rows generated for the selected inputs."), "diagnostics": diagnostics})
        return build_response(req, rows, diagnostics, repo)

    rows, diagnostics = plan_media(req, historical_rows, inventory_rows, slot_meta, settings)
    diagnostics.update({"selected_comcats": req.comcats, "selected_countries": req.countries, "brand_tag": req.brand_tag, "engine": "v1"})
    if not rows:
        raise HTTPException(status_code=422, detail={"message": plan_failure_message(diagnostics), "diagnostics": diagnostics})
    split_violations = strict_split_violations(diagnostics)
    if split_violations:
        raise HTTPException(status_code=422, detail={
            "message": "The strict budget split could not be satisfied with the eligible inventory and selected slots: " + "; ".join(split_violations),
            "diagnostics": diagnostics,
        })
    diagnostics["roas_refine"] = {
        "applied": False,
        "reason": "skipped to preserve the requested budget, phase, marketplace, comcat, and selected-slot allocation",
    }
    return build_response(req, rows, diagnostics, repo)


@app.post("/api/media-plan/{plan_id}/regenerate", response_model=MediaPlanResponse)
def regenerate_media_plan(plan_id: str, req: MediaPlanRequest, engine: str = "v1", settings: Settings = Depends(get_settings), repo: BigQueryRepository = Depends(get_repo)):
    if req.budget <= 0:
        raise HTTPException(status_code=400, detail="on-deck budget must be positive")
    req.total_budget = gross_budget_from_net(req.budget + req.offdeck_budget, req.discount_pct)
    req.brand_tag = req.brand_tag or repo.infer_brand_tag(req)
    historical_rows = repo.fetch_historical_performance(req)
    inventory_rows = repo.fetch_inventory(req)
    slot_meta = repo.fetch_slot_meta(req)
    replacement_req = req.model_copy(deep=True)
    replacement_req.selected_slot_keys = []
    replacement_req.manual_slot_keys = []
    replacement_req.selected_slot_pricing = {}
    replacement_req.foc_slot_keys = []
    replacement_suggestions = suggest_slots(
        replacement_req,
        historical_rows,
        inventory_rows,
        slot_meta,
        settings,
        limit=max(len(req.countries), 1) * (6 if req.budget <= 10000 else 10),
    )
    refresh_regeneration_selection(req, replacement_suggestions)
    inventory_rows, slot_meta = merge_manual_slot_inputs(req, repo, inventory_rows, slot_meta)

    if str(engine).lower() == "v2":
        v2_rows, diagnostics = plan_media_v2(req, historical_rows, inventory_rows, slot_meta, settings)
        rows = to_editable_rows(v2_rows, req)
        diagnostics.update({"selected_comcats": req.comcats, "selected_countries": req.countries, "brand_tag": req.brand_tag, "engine": "v2", "regenerated": True, "regenerated_from": plan_id})
        if not rows:
            raise HTTPException(status_code=422, detail={"message": plan_failure_message(diagnostics, "No plan rows generated for the selected inputs."), "diagnostics": diagnostics})
        # Save regeneration as a new revision. Replacing a plan immediately after
        # streaming it can make BigQuery reject DELETE against its streaming buffer.
        return build_response(req, rows, diagnostics, repo)

    rows, diagnostics = plan_media(req, historical_rows, inventory_rows, slot_meta, settings)
    diagnostics.update({"selected_comcats": req.comcats, "selected_countries": req.countries, "brand_tag": req.brand_tag, "engine": "v1", "regenerated": True, "regenerated_from": plan_id})
    if not rows:
        raise HTTPException(status_code=422, detail={"message": plan_failure_message(diagnostics), "diagnostics": diagnostics})
    split_violations = strict_split_violations(diagnostics)
    if split_violations:
        raise HTTPException(status_code=422, detail={
            "message": "The strict budget split could not be satisfied with the eligible inventory and selected slots: " + "; ".join(split_violations),
            "diagnostics": diagnostics,
        })
    return build_response(req, rows, diagnostics, repo)


@app.get("/api/media-plan/{plan_id}")
def get_media_plan(plan_id: str, repo: BigQueryRepository = Depends(get_repo)):
    plan = repo.get_saved_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="plan not found")
    return plan


app.mount("/static", StaticFiles(directory="."), name="static")
