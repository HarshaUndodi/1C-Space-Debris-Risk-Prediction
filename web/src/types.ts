// One TypeScript type per SPEC Section 13 schema — mirrors api/schemas.py.

export type Decision = 'MANEUVER' | 'WATCH' | 'HOLD'
export type Source = 'historical' | 'live'
export type Direction = '+along' | '-along' | '+radial' | '-radial'

export interface Health {
  status: string
  model_loaded: boolean
  catalog_age_hours: number | null
  mode: 'mock' | 'real'
}

export interface AlertItem {
  event_id: string
  source: Source
  decision: Decision
  time_to_tca_days: number
  p_high: number | null // null for live screening (no CDM model)
  risk_p10: number
  risk_p50: number
  risk_p90: number
  baseline_risk: number
  miss_distance_m: number
  chaser_type: string
}

export interface CdmPoint {
  time_to_tca: number
  risk: number
  miss_distance_m: number
}

export interface ShapItem {
  feature: string
  label: string
  value: number | null
  shap: number
}

export interface AlertDetail extends AlertItem {
  cdm_history: CdmPoint[]
  available_cutoffs: number[]
  shap_top: ShapItem[]
  briefing: string[]
  briefing_source: 'llm' | 'template'
  true_final_risk: number | null
}

export interface ManeuverOption {
  dv_ms: number
  direction: Direction
  burn_lead_h: number
  post_pc: number
}

export interface RecommendedBurn extends ManeuverOption {
  propellant_g: number
}

export interface ParetoPoint {
  dv_ms: number
  post_pc: number
}

export interface NewConjunction {
  norad: number
  name: string
  miss_km: number
  tca: string
}

export interface SecondaryCheck {
  applicable: boolean
  new_conjunctions: NewConjunction[]
  note?: string | null
}

export interface ManeuverResult {
  event_id: string
  target_pc: number
  target_met: boolean
  pre_burn_pc: number
  recommended: RecommendedBurn
  points: ManeuverOption[]
  pareto: ParetoPoint[]
  secondary_check: SecondaryCheck
  note?: string | null
  assumptions?: Record<string, unknown> | null
}

export interface CatalogObject {
  norad: number
  name: string
  type: string
  lat: number
  lon: number
  alt_km: number
  tag?: string
}

export interface LiveCatalog {
  epoch: string
  objects: CatalogObject[]
}

export interface Conjunction {
  event_id?: string
  primary_at_tca?: CatalogObject
  pc_band?: { half: number; double: number }
  element_age_days?: { primary: number; secondary: number }
  secondary: CatalogObject
  tca: string
  miss_km: number
  rel_speed_kms: number
  pc_est: number
  rtn_km: number[]
}

export interface LiveConjunctions {
  primary: CatalogObject
  conjunctions: Conjunction[]
  compute_seconds: number
}

export interface TrackObject {
  norad: number
  name: string
  type: string
  tag?: string
}

export interface Preset {
  norad: number
  name: string
  fleet?: 'station' | 'isro' | string
  agency?: string
}

export interface LiveTracks {
  start: string
  step_s: number
  n_steps: number
  objects: TrackObject[]
  samples_km: number[][] // per object: flat [x0,y0,z0,x1,…] Earth-fixed km
}

export interface OrbitPoint {
  t: string
  lat: number
  lon: number
  alt_km: number
}

export interface OrbitPath {
  points: OrbitPoint[]
}

export interface LeadTimePoint {
  cutoff_days: number
  model_recall: number
  baseline_recall: number
  model_f2: number
  baseline_f2: number
}

export interface BaselineMetrics {
  kelvins_score: number | null
  mse_hr: number | null
  f2: number
  recall: number
  false_alarm_rate: number
  brier: number
}

export interface ModelMetrics extends BaselineMetrics {
  brier_uncalibrated: number
  band_coverage_p10_p90: number
  threshold: number
}

export interface ScreeningMetrics {
  objects: number
  hours: number
  step_s: number
  seconds: number
}

export interface ReliabilityBin {
  p_mean: number
  frac_pos: number
  n: number
}

export interface Metrics {
  cutoff_days: number
  n_test_events: number
  n_test_high_risk: number
  baseline: BaselineMetrics
  model: ModelMetrics
  lead_time: (LeadTimePoint & { model_far?: number; baseline_far?: number; n_available?: number })[]
  screening: ScreeningMetrics & {
    primary?: string; conjunctions?: number; prefiltered_objects?: number; catalog_load_seconds?: number
    all_vs_all?: { objects: number; hours: number; step_s: number; radius_km: number; seconds: number; pairs_sampled_close: number }
  }
  // extras written by evaluate.py / pc.py (absent in mock mode)
  is_mock?: boolean
  generated_at?: string
  n_train_events?: number
  n_train_high_risk?: number
  baseline_clipped?: { kelvins_score: number | null; mse_hr: number | null; f2: number }
  baseline_at_95_recall_level?: { level_log10: number; recall: number; false_alarm_rate: number; f2: number }
  ranking?: {
    auc_pr_model: number; auc_pr_baseline: number; roc_auc_model: number; roc_auc_baseline: number
    far_at_recall_diagnostic: Record<string, { model: number; baseline: number }>
  }
  reliability?: { model_calibrated: ReliabilityBin[]; model_uncalibrated: ReliabilityBin[]; baseline_logistic: ReliabilityBin[] }
  shap_global?: { feature: string; label: string; mean_abs_shap: number }[]
  pc_validation?: { n_cdms: number; spearman_all: number; spearman_above_floor: number | null; median_abs_log10_diff_above_floor: number | null; within_1_order_of_magnitude: number | null }
  notes?: string[]
}

export interface SpaceWeatherHistoryPoint {
  date: string
  f107: number
  ap: number
}

export interface SpaceWeather {
  date: string
  f107: number
  ap: number
  heuristic_drag_flag: 'normal' | 'elevated'
  noaa_scale?: string
  density_multiplier?: number
  drag_uncertainty_pct?: number
  leo_impact?: string
  history_7d?: SpaceWeatherHistoryPoint[]
}

export interface LiveCdmSample {
  id: string
  title: string
  description: string
  data: {
    event_id: string
    time_to_tca_days: number
    miss_distance_m: number
    rel_speed_kms: number
    risk: number
    chaser_type: string
    target_sigmas_m?: number[]
    chaser_sigmas_m?: number[]
    sma_km?: number
    cutoff?: number
  }
}

export interface LiveCdmPredictionResult extends AlertDetail {
  maneuver: ManeuverResult
}

