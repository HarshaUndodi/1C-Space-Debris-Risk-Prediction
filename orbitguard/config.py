"""Paths, thresholds and constants shared across OrbitGuard."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# --- Paths -------------------------------------------------------------------
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
KELVINS_DIR = RAW_DIR / "kelvins"
CELESTRAK_DIR = RAW_DIR / "celestrak"
SPACE_WEATHER_DIR = RAW_DIR / "spaceweather"

ARTIFACTS_DIR = ROOT / "artifacts"
PLOTS_DIR = ARTIFACTS_DIR / "plots"
CATALOG_SNAPSHOT_DIR = ARTIFACTS_DIR / "catalog_snapshot"
METRICS_PATH = ARTIFACTS_DIR / "metrics.json"
MODEL_CONFIG_PATH = ARTIFACTS_DIR / "model_config.json"
DEMO_EVENTS_PATH = ARTIFACTS_DIR / "demo_events.json"
BRIEFINGS_PATH = ARTIFACTS_DIR / "briefings.json"

# --- Data sources ------------------------------------------------------------
KELVINS_ZENODO_RECORD = "4463683"
KELVINS_ZENODO_API = f"https://zenodo.org/api/records/{KELVINS_ZENODO_RECORD}"
KELVINS_MIRROR_BASE = "https://kelvins.esa.int/media/public/competitions/collision-avoidance-challenge"
KELVINS_MIRROR_FILES = ["train_data.zip", "test_data.csv"]

CELESTRAK_GP_URL = "https://celestrak.org/NORAD/elements/gp.php"  # always .org
CELESTRAK_GROUPS = [
    "stations",
    "active",
    "cosmos-1408-debris",
    "fengyun-1c-debris",
    "iridium-33-debris",
    "cosmos-2251-debris",
]
# CelesTrak updates every 2 h and allows one download per update per group.
CELESTRAK_MIN_AGE_HOURS = 2.0
SPACE_WEATHER_URL = "https://celestrak.org/SpaceData/SW-All.csv"
SPACE_WEATHER_MIN_AGE_HOURS = 24.0  # daily product
HTTP_TIMEOUT_S = 60

# --- Modelling ---------------------------------------------------------------
SEED = 42
DEFAULT_CUTOFF_DAYS = 2.0
# SPEC asks for 2,3,4,5,7 but Kelvins CDMs start < 7 days before TCA (max 6.99 d) → 6 replaces 7.
CUTOFFS_DAYS = [2, 3, 4, 5, 6]
N_FOLDS = 5                     # out-of-fold predictions for calibration + threshold (see calibrate.py)
HIGH_RISK_LOG10 = -6.0          # official Kelvins class boundary (PoC >= 1e-6)
# Reported risk floor. ~40 % of CDMs sit at the -30 "negligible" floor and dominate any L2 fit; only
# accuracy above -6 is scored (MSE_HR, F2), so risk regressions are trained/reported on max(risk, -6.5).
# Risks at the floor are shown as "< 1 in 3.2 million". Chosen on out-of-fold training data only.
RISK_FLOOR_LOG10 = -6.5
MANEUVER_P90_LOG10 = -4.0       # maneuver trigger: P90 risk >= 1e-4 (decision.py)

# --- Physics -----------------------------------------------------------------
MU_EARTH = 3.986004418e14       # m^3/s^2
G0 = 9.80665                    # m/s^2
DEFAULT_SAT_MASS_KG = 500.0
DEFAULT_ISP_S = 220.0           # hydrazine monoprop
TARGET_PC = 1e-6

# --- Live screening ----------------------------------------------------------
DEFAULT_PRIMARY_NORAD = 25544   # ISS (ZARYA)

# --- LLM briefing ------------------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "none").strip().lower()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001").strip()
LLM_TIMEOUT_S = 8.0

# --- API ---------------------------------------------------------------------
API_MODE = os.getenv("API_MODE", "auto").strip().lower()  # "auto" | "mock" | "real"
