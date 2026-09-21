"""
05_cross_site.py
================

"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import config as C

sys.path.insert(0, str(Path(__file__).parent))


def add_level(df):
    df = df.copy()
    is_depth = df.parameter == "depth"
    df["level"] = np.nan
    has = is_depth & df.stage_m.notna()
    df.loc[has, "level"] = df.loc[has, "stage_m"]
    df.loc[is_depth & df.stage_m.isna(), "level"] = -df.loc[is_depth & df.stage_m.isna(), "value"]
    df.loc[~is_depth, "level"] = df.loc[~is_depth, "value"]
    return df


def series_for(clean, site, param):
    g = clean[(clean.site == site) & (clean.parameter == param)]
    if C.EXCLUDE_SUSPECT_REGIMES_FROM_ANALYSIS:
        g = g[g.trust == "ok"]
    g = g[g.status != C.STATUS_MISSING]
    if g.empty:
        return None
    s = (g.set_index("timestamp").level
          .resample(C.CROSS_SITE_RESAMPLE).mean())
    return s


def lagged_corr(a, b, max_lag_h):
    """Positive lag = b lags a (a leads b)."""
    step = pd.Timedelta(C.CROSS_SITE_RESAMPLE)
    max_steps = int(pd.Timedelta(hours=max_lag_h) / step)
    out = []
    for k in range(-max_steps, max_steps + 1):
        bb = b.shift(k)
        pair = pd.concat([a, bb], axis=1, sort=True).dropna()
        if len(pair) < C.MIN_OVERLAP_POINTS:
            continue
        r = pair.iloc[:, 0].corr(pair.iloc[:, 1])
        out.append(dict(lag_hours=k * step / pd.Timedelta(hours=1),
                        r=round(r, 4), n=len(pair)))
    return pd.DataFrame(out)


def main():
    clean = add_level(pd.read_csv(C.PROCESSED_DIR / "clean_dataset.csv",
                                  parse_dates=["timestamp"]))

    streams = {}
    for site in ["Kamand", "North"]:
        for param in ["depth", "velocity"]:
            s = series_for(clean, site, param)
            if s is not None and s.notna().sum() >= C.MIN_OVERLAP_POINTS:
                streams[(site, param)] = s

    print("Streams available for cross-site analysis:")
    for k, v in streams.items():
        print(f"  {k[0]:7s} {k[1]:9s}  {v.notna().sum():6d} hourly points  "
              f"{v.dropna().index.min()} -> {v.dropna().index.max()}")

    keys = list(streams)
    corr_rows, lag_rows, roll_rows = [], [], []

    for i, k1 in enumerate(keys):
        for k2 in keys[i + 1:]:
            if k1[0] == k2[0]:
                kind = "within_site"
            else:
                kind = "cross_site"
            a, b = streams[k1], streams[k2]
            pair = pd.concat([a.rename("a"), b.rename("b")], axis=1, sort=True).dropna()
            if len(pair) < C.MIN_OVERLAP_POINTS:
                print(f"  [skip] {k1} vs {k2}: only {len(pair)} overlapping hours")
                continue

            da, db = pair.a.diff(), pair.b.diff()
            corr_rows.append(dict(
                series_a=f"{k1[0]}_{k1[1]}", series_b=f"{k2[0]}_{k2[1]}", kind=kind,
                n_overlap_hours=len(pair),
                overlap_start=pair.index.min(), overlap_end=pair.index.max(),
                pearson_level=round(pair.a.corr(pair.b), 4),
                spearman_level=round(pair.a.corr(pair.b, method="spearman"), 4),
                pearson_firstdiff=round(da.corr(db), 4),
                spearman_firstdiff=round(da.corr(db, method="spearman"), 4),
            ))

            lc = lagged_corr(pair.a, pair.b, C.MAX_LAG_HOURS)
            if not lc.empty:
                lc["series_a"] = f"{k1[0]}_{k1[1]}"
                lc["series_b"] = f"{k2[0]}_{k2[1]}"
                lag_rows.append(lc)
                best = lc.loc[lc.r.abs().idxmax()]
                print(f"  {k1[0]}_{k1[1]} vs {k2[0]}_{k2[1]}: "
                      f"r={pair.a.corr(pair.b):+.3f} (levels), "
                      f"peak |r|={best.r:+.3f} at lag {best.lag_hours:+.0f} h, "
                      f"n={len(pair)}")

            w = f"{C.ROLLING_CORR_WINDOW_D}D"
            rc = pair.a.rolling(w).corr(pair.b).dropna()
            if not rc.empty:
                roll_rows.append(pd.DataFrame(dict(
                    timestamp=rc.index, r=rc.values.round(4),
                    series_a=f"{k1[0]}_{k1[1]}", series_b=f"{k2[0]}_{k2[1]}")))

    pd.DataFrame(corr_rows).to_csv(C.PROCESSED_DIR / "cross_site_correlation.csv", index=False)
    (pd.concat(lag_rows) if lag_rows else pd.DataFrame()).to_csv(
        C.PROCESSED_DIR / "cross_site_lag.csv", index=False)
    (pd.concat(roll_rows) if roll_rows else pd.DataFrame()).to_csv(
        C.PROCESSED_DIR / "rolling_correlation.csv", index=False)

    if corr_rows:
        print("\n=== Correlation summary ===")
        print(pd.DataFrame(corr_rows).to_string(index=False))
    print("\nReminder: peak-correlation lag = co-response timing to shared rainfall,")
    print("NOT travel time between two different rivers.")


if __name__ == "__main__":
    main()