"""
config.py
=========
Every assumption, threshold and tunable parameter for the ClimMaTech pipeline
lives here. Nothing scientific is hard-coded anywhere else.

Each block says (a) what the value does, (b) why the default was chosen and
(c) what to change it to once ClimMaTech confirms the real sensor metadata.

Anything marked "ASSUMPTION" is a defensible default, NOT a confirmed fact.
It must be listed in the report as an assumption.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# 1. PATHS   <-- the only thing you MUST edit
# ---------------------------------------------------------------------------
PROJECT_DIR = Path("/Users/ADMIN/Desktop/Climatech - Data")

RAW_DIR       = PROJECT_DIR / "raw_data"
PROCESSED_DIR = PROJECT_DIR / "processed"
FIGURES_DIR   = PROJECT_DIR / "figures"
REPORTS_DIR   = PROJECT_DIR / "reports"

for _d in (PROCESSED_DIR, FIGURES_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 2. RAW FILE REGISTRY
# ---------------------------------------------------------------------------
# Files are matched case-insensitively and ignoring the difference between
# single/double/triple underscores, because these names came from browser
# downloads where "(1)" gets mangled inconsistently. If a registered file is
# not found the pipeline now STOPS instead of silently skipping it.
#
# has_summary_col=True means the LAST column of the row is a pre-computed
# summary (e.g. median_depth) and must NOT be counted as a sub-reading.

FILES = {
    "depth_measurements_K.csv":   dict(site="Kamand", parameter="depth",
                                       has_header=True, has_summary_col=True),
    "depth_K.csv":                dict(site="Kamand", parameter="depth_stage_burst",
                                       has_header=True, has_summary_col=False),
    # Like the Kamand depth file, the last of the 16 numeric columns is a
    # pre-computed median of the other 15 (confirmed: matches median(first15)
    # in 96.9% of rows - the remainder is float rounding). Originally
    # registered has_summary_col=False, which double-counted this column as a
    # 16th sub-reading in every North depth row. Fixed after inspecting the
    # actual raw file.
    "depth_measurements_N__1_.csv": dict(site="North", parameter="depth",
                                       has_header=False, has_summary_col=True),
    "velocity_K.csv":             dict(site="Kamand", parameter="velocity",
                                       has_header=True, has_summary_col=False,
                                       corrupt_header=True),
    "velocity_K__1_.csv":         dict(site="Kamand", parameter="velocity_burst",
                                       has_header=True, has_summary_col=False),
    "velocity_N.csv":             dict(site="North", parameter="velocity",
                                       has_header=True, has_summary_col=False),
}

# Confirmed byte-identical duplicates / subsets. Documented, not deleted.
EXCLUDED = {
    "depth_measurements_K_1_.csv":  "byte-identical to depth_measurements_K__2_.csv; subset of depth_measurements_K.csv",
    "depth_measurements_K__2_.csv": "byte-identical duplicate export",
    "depth_measurements_N.csv":     "byte-identical to depth_measurements_N__3_.csv; subset of N__1_",
    "depth_measurements_N__3_.csv": "byte-identical duplicate export",
}

# Streams kept out of the main analysis until ClimMaTech confirms their meaning.
QUARANTINED_PARAMETERS = {
    "depth_stage_burst",     # depth_K.csv    - 30 Aug 2025, ~0.3-1.5, likely already-converted stage
    "velocity_burst",        # velocity_K__1_.csv - 30 Aug 2025 burst
    "depth_burst_30aug",     # legacy name from the first pipeline version
    "velocity_burst_30aug",  # legacy name from the first pipeline version
    "velocity_UNCONFIRMED",  # vel_K.csv      - Jan 2026, Doppler, separate deployment
}


# ---------------------------------------------------------------------------
# 3. DEPTH INTERPRETATION   *** THE CENTRAL ASSUMPTION OF THIS PROJECT ***
# ---------------------------------------------------------------------------
# ASSUMPTION: the "depth_measurements_*" sensors are downward-looking range
# finders reporting the DISTANCE FROM THE SENSOR TO THE WATER SURFACE in
# metres, not water depth. Evidence (see reports/assumptions.md):
#   - the seasonal signal is inverted (driest month gives the largest value)
#   - 9.6-13.6 m of water is implausible at a river monitoring section
#   - applying a constant offset reconciles it with depth_K.csv
#
# Therefore:  stage = DATUM - range
#
# DATUM_M is the height of the sensor above the local stage zero, in metres.
# Kamand's value is ESTIMATED from the single overlapping day (30 Aug 2025)
# where depth_measurements_K.csv read ~12.50 and depth_K.csv read ~0.86.
# It is accurate to maybe +/- 0.3 m and is the largest single uncertainty in
# the project.
#
# REPLACE these with surveyed values as soon as ClimMaTech provides them.

DEPTH_IS_RANGE_NOT_STAGE = True

DATUM_M = {
    "Kamand": 13.36,   # ASSUMPTION - estimated, not surveyed
    "North":  None,    # UNKNOWN - no overlapping reference measurement exists
}
# When a site's datum is None the stage column is left NaN and only the raw
# range is analysed. Relative changes (rises, falls, correlations, lags) are
# still valid without a datum; absolute water depth is not.


# ---------------------------------------------------------------------------
# 4. SENSOR REGIME BREAKS
# ---------------------------------------------------------------------------
# A "regime" is a period over which one stream's logging behaviour is
# internally consistent. Kamand depth demonstrably changes character after a
# 7-week outage: value range, timestamp precision, decimal places and sampling
# interval all shift at once. Statistics must never be pooled across a break.
#
# Format: (site, parameter) -> list of (label, start, end, trust)
# trust = "ok" | "suspect". Suspect regimes stay in the processed dataset with
# a flag, but are excluded from event detection and cross-site analysis.

REGIME_BREAKS = {
    ("Kamand", "depth"): [
        ("K_depth_A", "2025-07-27", "2025-09-13", "ok"),
        # ASSUMPTION: regime B is suspect. 931 readings span only 0.17 m over
        # three weeks and never overlap regime A's value range. Consistent with
        # a re-mounted sensor OR with a sensor pinned at its maximum range
        # (i.e. no water in the beam). Needs a human call - see assumptions.md.
        ("K_depth_B", "2025-11-01", "2025-12-31", "suspect"),
    ],
    ("North", "depth"): [
        ("N_depth_main", "2025-01-01", "2026-05-04", "ok"),
        # ASSUMPTION: suspect. 14 readings on the afternoon of 4 May 2026, the
        # very last day in the file, sit at 0.79-0.80 m - roughly a 9m drop
        # from the surrounding record and in the same range as the Kamand
        # depth_K.csv calibration burst. Reads as a short test/replacement-
        # sensor burst at North, not a real river reading. Needs confirmation.
        ("N_depth_burst_04may26", "2026-05-04", "2026-05-05", "suspect"),
    ],
}

EXCLUDE_SUSPECT_REGIMES_FROM_ANALYSIS = True


# ---------------------------------------------------------------------------
# 5. PLAUSIBILITY BOUNDS
# ---------------------------------------------------------------------------
# NOT physical limits from a datasheet - these are wide sanity bounds chosen to
# catch obvious nonsense (negative ranges, impossible velocities) while letting
# genuine extremes through. Values outside are flagged, never deleted.
#
# Velocity: 8 m/s is already extreme for a Himalayan river section. Kamand's
# raw maximum of 15.98 m/s is almost certainly spike contamination, but it is
# flagged for review rather than removed.

PLAUSIBLE_BOUNDS = {
    "depth":    (0.0, 20.0),   # metres of range from sensor
    "velocity": (0.0,  8.0),   # m/s  - ASSUMPTION about units
}


# ---------------------------------------------------------------------------
# 6. GAP CLASSIFICATION
# ---------------------------------------------------------------------------
# A gap is any interval longer than GAP_MULTIPLIER x the stream's own median
# sampling interval. Classification drives what (if anything) may be imputed.
#
#   short  : interpolation is defensible - the river cannot change much
#   medium : interpolation is possible but must be reviewed
#   long   : left missing. Do not invent a day of river behaviour.

GAP_MULTIPLIER = 3

GAP_SHORT_MAX_HOURS  = 2.0    # ASSUMPTION
GAP_MEDIUM_MAX_HOURS = 24.0   # ASSUMPTION

# Never interpolate across a gap that touches a detected event, regardless of
# duration - that is exactly where interpolation would fabricate a hydrograph.
PROTECT_EVENT_GAPS = True


# ---------------------------------------------------------------------------
# 7. IMPUTATION POLICY
# ---------------------------------------------------------------------------
# Only 'short' gaps are filled automatically, and only by linear interpolation.
# Every filled point carries status='interpolated' and an imputation_method.
# Nothing is ever written back over an observed value.

IMPUTE_SHORT_GAPS  = True
IMPUTE_MEDIUM_GAPS = False   # set True only after reviewing gaps_classified.csv
INTERPOLATION_METHOD = "linear"

# Target grid for the regularised series. 15 min matches both sites' native
# logging interval closely enough not to distort the signal.
RESAMPLE_FREQ = "15min"


# ---------------------------------------------------------------------------
# 8. QUALITY-AUDIT THRESHOLDS
# ---------------------------------------------------------------------------
FROZEN_RUN_THRESHOLD = 5    # identical consecutive values => stuck sensor?
IQR_MULTIPLIER       = 3.0  # statistical outlier fence
JUMP_MULTIPLIER      = 5.0  # step > 5x median step => flagged as a jump

# NOTE: a flagged jump or outlier is a CANDIDATE, not an error. In a flashy
# Himalayan catchment the genuine events look exactly like this.


# ---------------------------------------------------------------------------
# 9. EVENT DETECTION
# ---------------------------------------------------------------------------
# With no rating curve and no confirmed datum, absolute discharge thresholds
# are impossible. Events are therefore defined RELATIVE to each stream's own
# distribution - this is standard practice for ungauged/uncalibrated records
# and is honest about what the data can support.
#
# An event = a period where stage rises faster than RISE_PERCENTILE of all
# observed rise rates, peaks above PEAK_PERCENTILE of the stage distribution,
# and lasts at least MIN_EVENT_DURATION_H.

RISE_RATE_PERCENTILE = 95    # ASSUMPTION
PEAK_PERCENTILE      = 90    # ASSUMPTION
MIN_EVENT_DURATION_H = 1.0
EVENT_MERGE_GAP_H    = 6.0   # events closer than this are merged into one
RECESSION_FRACTION   = 0.5   # event ends when stage falls back this far toward baseline

# Additional exceedance thresholds reported in the threshold analysis chapter.
EXCEEDANCE_PERCENTILES = [50, 75, 90, 95, 99]


# ---------------------------------------------------------------------------
# 10. CROSS-SITE ANALYSIS
# ---------------------------------------------------------------------------
# Khad (North) and Uhl (Kamand) are separate rivers. Any correlation between
# them reflects SHARED RAINFALL over the Mandi region, not flow routing from
# one to the other. Lag results must be described as co-response timing, never
# as travel time, unless ClimMaTech confirms a hydraulic connection.

CROSS_SITE_RESAMPLE   = "1h"
MAX_LAG_HOURS         = 48
MIN_OVERLAP_POINTS    = 200   # below this, correlation is not reported
ROLLING_CORR_WINDOW_D = 7


# ---------------------------------------------------------------------------
# 11. STATUS VOCABULARY  (used in the processed dataset)
# ---------------------------------------------------------------------------
STATUS_OBSERVED     = "observed"       # straight from the raw file
STATUS_CORRECTED    = "corrected"      # recovered from a malformed raw row
STATUS_INTERPOLATED = "interpolated"   # filled across a short gap
STATUS_ESTIMATED    = "estimated"      # filled by a model/regression
STATUS_MISSING      = "missing"        # known gap, deliberately left empty
STATUS_SUSPECT      = "suspect"        # observed but quality-flagged