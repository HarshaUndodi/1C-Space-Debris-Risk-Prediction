"""Pydantic models = the SPEC Section 13 API contract. Frontend types in web/src/types.ts mirror these."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

Decision = Literal["MANEUVER", "WATCH", "HOLD"]
Source = Literal["historical", "live"]
Direction = Literal["+along", "-along", "+radial", "-radial"]


class Health(BaseModel):
    status: str
    model_loaded: bool
    catalog_age_hours: Optional[float] = None
    mode: Literal["mock", "real"] = "mock"


class AlertItem(BaseModel):
    event_id: str
    source: Source
    decision: Decision
    time_to_tca_days: float
    p_high: Optional[float]   # calibrated P(high risk); null for live screening (no CDM model)
    risk_p10: float
    risk_p50: float
    risk_p90: float
    baseline_risk: float
    miss_distance_m: float
    chaser_type: str


class CdmPoint(BaseModel):
    time_to_tca: float
    risk: float
    miss_distance_m: float


class ShapItem(BaseModel):
    feature: str
    label: str
    value: Optional[float] = None
    shap: float


class AlertDetail(AlertItem):
    cdm_history: list[CdmPoint]
    available_cutoffs: list[int]
    shap_top: list[ShapItem]
    briefing: list[str]
    briefing_source: Literal["llm", "template"]
    true_final_risk: Optional[float] = None


class ManeuverOption(BaseModel):
    dv_ms: float
    direction: Direction
    burn_lead_h: float
    post_pc: float


class RecommendedBurn(ManeuverOption):
    propellant_g: float


class ParetoPoint(BaseModel):
    dv_ms: float
    post_pc: float


class NewConjunction(BaseModel):
    norad: int
    name: str
    miss_km: float
    tca: str


class SecondaryCheck(BaseModel):
    applicable: bool
    new_conjunctions: list[NewConjunction]
    note: Optional[str] = None


class ManeuverResult(BaseModel):
    event_id: str
    target_pc: float
    target_met: bool
    pre_burn_pc: float
    recommended: RecommendedBurn
    points: list[ManeuverOption]
    pareto: list[ParetoPoint]
    secondary_check: SecondaryCheck
    note: Optional[str] = None
    assumptions: Optional[dict] = None


class CatalogObject(BaseModel):
    norad: int
    name: str
    type: str  # PAYLOAD | DEBRIS | ROCKET BODY | UNKNOWN
    lat: float
    lon: float
    alt_km: float


class LiveCatalog(BaseModel):
    epoch: str
    objects: list[CatalogObject]


class Conjunction(BaseModel):
    model_config = {"extra": "allow"}   # event_id, primary_at_tca, pc_band, hours_to_tca, element_age_days …

    secondary: CatalogObject
    tca: str
    miss_km: float
    rel_speed_kms: float
    pc_est: float
    rtn_km: list[float]


class LiveConjunctions(BaseModel):
    model_config = {"extra": "allow"}   # start_utc, stats

    primary: CatalogObject
    conjunctions: list[Conjunction]
    compute_seconds: float


class OrbitPoint(BaseModel):
    t: str
    lat: float
    lon: float
    alt_km: float


class OrbitPath(BaseModel):
    points: list[OrbitPoint]


class LeadTimePoint(BaseModel):
    model_config = {"extra": "allow"}   # model_far, baseline_far, n_available, …

    cutoff_days: float
    model_recall: float
    baseline_recall: float
    model_f2: float
    baseline_f2: float


class BaselineMetrics(BaseModel):
    model_config = {"extra": "allow"}

    # Optional: a score is null when undefined (e.g. Kelvins score with F2 = 0 is infinite).
    kelvins_score: Optional[float]
    mse_hr: Optional[float]
    f2: float
    recall: float
    false_alarm_rate: float
    brier: float


class ModelMetrics(BaselineMetrics):
    brier_uncalibrated: float
    band_coverage_p10_p90: float
    threshold: float


class ScreeningMetrics(BaseModel):
    model_config = {"extra": "allow"}

    objects: int
    hours: float
    step_s: float
    seconds: float


class Metrics(BaseModel):
    """metrics.json; extra keys (reliability bins, Spearman, …) are allowed and passed through."""
    model_config = {"extra": "allow"}

    cutoff_days: float
    n_test_events: int
    n_test_high_risk: int
    baseline: BaselineMetrics
    model: ModelMetrics
    lead_time: list[LeadTimePoint]
    screening: ScreeningMetrics


class SpaceWeather(BaseModel):
    date: str
    f107: float
    ap: float
    heuristic_drag_flag: Literal["normal", "elevated"]
