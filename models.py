from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


Objective = Literal["visibility", "ctr", "roas", "reach", "both"]
BrandTag = Literal["old", "new"]
Marketplace = Literal["core", "supermall", "both"]


class Phase(BaseModel):
    name: str
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")


class EditablePlanLine(BaseModel):
    id: int
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    country: str
    page: str
    marketplace: str = ""
    category: str = ""
    zone: str = ""
    dimension: str = ""
    asset: str
    slot_name: str = ""
    days: int
    buyType: str
    rate: float
    gross_cpm: float = 0.0
    net_cpm: float = 0.0
    views: Optional[int]
    cost: float
    gross_amount: float = 0.0
    net_amount: float = 0.0
    discount_pct: float = 0.0
    phase: str
    brand: str
    stype: Literal["reach", "conv"]
    slot_code: str
    score: float = 0.0
    available_views: int = 0
    historical_ctr: Optional[float] = None
    historical_roas: Optional[float] = None
    historical_cpm: Optional[float] = None
    note: str = ""
    manual: bool = False
    locked: bool = False


class MediaPlanRequest(BaseModel):
    brand: str
    brands: list[str] = Field(default_factory=list)
    brand_budget_splits: dict[str, float] = Field(default_factory=dict)
    brand_tag: Optional[BrandTag] = None
    comcats: list[str] = Field(default_factory=list)
    comcat_budget_splits: dict[str, float] = Field(default_factory=dict)
    countries: list[str] = Field(default_factory=list)

    marketplace: Marketplace = "both"
    marketplace_core_pct: int = 70
    marketplace_supermall_pct: int = 30
    sub_brands: list[str] = Field(default_factory=list)

    start_date: date
    end_date: date

    # Budget is entered in USD. `budget` is the on-deck optimizer budget.
    total_budget: float = 0.0
    offdeck_budget: float = 0.0
    budget: float
    discount_pct: float = 0.0
    currency: str
    budget_locked: bool = False

    le_code: Optional[str] = None
    notes: Optional[str] = None

    objective: Objective
    reach_weight: int = 60
    roas_weight: int = 40
    phases: list[Phase] = Field(default_factory=list)
    phase_budget_splits: dict[str, float] = Field(default_factory=dict)
    selected_slot_keys: list[str] = Field(default_factory=list)
    manual_slot_keys: list[str] = Field(default_factory=list)
    selected_slot_pricing: dict[str, str] = Field(default_factory=dict)
    foc_slot_keys: list[str] = Field(default_factory=list)
    selected_offdeck_slots: list[dict] = Field(default_factory=list)

    plan_id: Optional[str] = None
    current_rows: list[EditablePlanLine] = Field(default_factory=list)
    excluded_slot_keys: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_phase_windows(self):
        """Validate 09:00-to-09:00 phase windows before querying inventory.

        Windows are half-open: [from, to).  A phase ending on 10 Oct at 09:00
        may therefore be followed by another phase starting on 10 Oct at 09:00.
        """
        ordered = sorted(self.phases, key=lambda phase: (phase.from_date, phase.to_date, phase.name))
        for phase in ordered:
            if phase.to_date <= phase.from_date:
                raise ValueError(
                    f"phase '{phase.name}' must end after it starts; "
                    "09:00 to the same 09:00 is not a service window"
                )
            if phase.from_date < self.start_date or phase.to_date > self.end_date:
                raise ValueError(f"phase '{phase.name}' must fall within the campaign dates")
        for previous, current in zip(ordered, ordered[1:]):
            if current.from_date < previous.to_date:
                raise ValueError(
                    f"phases '{previous.name}' and '{current.name}' overlap; "
                    "the next phase may start on the previous phase's end date, but not before it"
                )
        return self


class MediaPlanResponse(BaseModel):
    rows: list[EditablePlanLine]
    summary: dict
    diagnostics: dict
