"""
03_gaps_and_impute.py

"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import config as C


def classify_gaps(gaps):
    def cls(h):
        if h <= C.GAP_SHORT_MAX_HOURS:
            return "short"
        if h <= C.GAP_MEDIUM_MAX_HOURS:
            return "medium"
        return "long"

    gaps = gaps.copy()
    gaps["gap_class"] = gaps.duration_hours.apply(cls)
    gaps["imputation_allowed"] = gaps.gap_class.map(
        {"short": C.IMPUTE_SHORT_GAPS, "medium": C.IMPUTE_MEDIUM_GAPS, "long": False})
    gaps["review_required"] = gaps.gap_class.isin(["medium", "long"])
    return gaps


def regularise(df, freq):
    """Median-aggregate onto a regular grid; keep provenance of real points."""
    df = df.sort_values("timestamp")
    g = (df.set_index("timestamp")
           .resample(freq)
           .agg(value=("value", "median"),
                n_raw=("value", "size"),
                source_file=("source_file", "first")))
    g["status"] = np.where(g.n_raw > 0, C.STATUS_OBSERVED, C.STATUS_MISSING)
    g["imputation_method"] = ""
    return g.reset_index()


def fill_short_gaps(grid, gaps, freq_minutes):
    """Interpolate only inside gaps flagged imputation_allowed."""
    grid = grid.copy()
    log = []
    fillable = gaps[gaps.imputation_allowed]
    mask = pd.Series(False, index=grid.index)
    for _, gp in fillable.iterrows():
        m = grid.timestamp.between(gp.gap_start, gp.gap_end, inclusive="neither")
        mask |= m
    target = mask & (grid.status == C.STATUS_MISSING)
    if target.any():
        interp = grid.value.interpolate(method=C.INTERPOLATION_METHOD, limit_area="inside")
        grid.loc[target, "value"] = interp[target]
        grid.loc[target, "status"] = C.STATUS_INTERPOLATED
        grid.loc[target, "imputation_method"] = C.INTERPOLATION_METHOD
        for ts in grid.loc[target, "timestamp"]:
            log.append(dict(timestamp=ts, method=C.INTERPOLATION_METHOD,
                            reason="short_gap_within_threshold"))
    return grid, log


def main():
    master = pd.read_csv(C.PROCESSED_DIR / "master_tagged.csv", parse_dates=["timestamp"])
    gaps = pd.read_csv(C.PROCESSED_DIR / "gaps_log.csv",
                       parse_dates=["gap_start", "gap_end"])

    gaps = classify_gaps(gaps)
    gaps.to_csv(C.PROCESSED_DIR / "gaps_classified.csv", index=False)
    print("Gap classification:")
    print(gaps.groupby(["site", "parameter", "gap_class"])
              .agg(n=("duration_hours", "size"),
                   hours=("duration_hours", "sum")).round(1).to_string())

    out_frames, imput_log = [], []
    for (site, param, regime), g in master.groupby(["site", "parameter", "regime"]):
        if param in C.QUARANTINED_PARAMETERS:
            continue  # quarantined streams are not regularised or imputed
        sub_gaps = gaps[(gaps.site == site) & (gaps.parameter == param) & (gaps.regime == regime)]
        grid = regularise(g, C.RESAMPLE_FREQ)
        grid, log = fill_short_gaps(grid, sub_gaps, C.RESAMPLE_FREQ)

        grid["site"], grid["parameter"], grid["regime"] = site, param, regime
        grid["trust"] = g.trust.iloc[0]
        for entry in log:
            entry.update(site=site, parameter=param, regime=regime)
        imput_log.extend(log)
        out_frames.append(grid)

    clean = pd.concat(out_frames, ignore_index=True)

    # range -> stage
    clean["stage_m"] = np.nan
    if C.DEPTH_IS_RANGE_NOT_STAGE:
        for site, datum in C.DATUM_M.items():
            if datum is None:
                continue
            m = (clean.site == site) & (clean.parameter == "depth")
            clean.loc[m, "stage_m"] = datum - clean.loc[m, "value"]
    clean["datum_assumed"] = clean.site.map(
        {k: (v is not None) for k, v in C.DATUM_M.items()}).fillna(False)

    cols = ["timestamp", "site", "parameter", "regime", "trust", "value", "stage_m",
            "status", "imputation_method", "n_raw", "source_file", "datum_assumed"]
    clean = clean[cols].sort_values(["site", "parameter", "timestamp"])
    clean.to_csv(C.PROCESSED_DIR / "clean_dataset.csv", index=False)

    pd.DataFrame(imput_log).to_csv(C.PROCESSED_DIR / "imputation_log.csv", index=False)

    print("\nClean dataset status counts:")
    print(clean.groupby(["site", "parameter", "status"]).size().to_string())
    print(f"\n{len(clean)} rows -> clean_dataset.csv")
    print(f"{len(imput_log)} values interpolated -> imputation_log.csv")
    n_review = int(gaps.review_required.sum())
    print(f"\n{n_review} gaps flagged review_required - see gaps_classified.csv")


if __name__ == "__main__":
    main()