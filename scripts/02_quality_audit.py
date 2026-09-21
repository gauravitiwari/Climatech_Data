"""
02_quality_audit.py
===================

"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import config as C


def tag_regimes(master):
    master = master.copy()
    master["regime"] = master["site"] + "_" + master["parameter"]
    master["trust"] = "ok"
    for (site, param), blocks in C.REGIME_BREAKS.items():
        sel = (master.site == site) & (master.parameter == param)
        for label, start, end, trust in blocks:
            m = sel & master.timestamp.between(pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1))
            master.loc[m, "regime"] = label
            master.loc[m, "trust"] = trust
    return master


def audit(df, site, parameter, regime, trust):
    df = df.sort_values("timestamp").reset_index(drop=True)
    s = dict(site=site, parameter=parameter, regime=regime, trust=trust,
             n_rows=len(df), start=df.timestamp.min(), end=df.timestamp.max())
    gaps, anoms = [], []

    dup = df.duplicated(subset="timestamp", keep=False)
    s["n_duplicate_timestamps"] = int(dup.sum())
    for _, r in df[dup].iterrows():
        anoms.append((site, parameter, regime, r.timestamp, r.value, r.source_file,
                      "duplicate_timestamp"))

    u = df.drop_duplicates(subset="timestamp", keep="first").reset_index(drop=True)
    if len(u) < 3:
        s.update(dict(typical_interval_min=None, completeness_pct=None, n_gaps=0,
                      total_gap_hours=0, n_frozen_runs=0, n_outliers_iqr=0,
                      n_jumps=0, n_out_of_bounds=0))
        return s, gaps, anoms

    deltas = u.timestamp.diff().dt.total_seconds().dropna() / 60
    interval = float(deltas.median())
    s["typical_interval_min"] = round(interval, 2)

    span = (u.timestamp.max() - u.timestamp.min()).total_seconds() / 60
    expected = span / interval if interval > 0 else np.nan
    s["completeness_pct"] = round(min(100 * len(u) / expected, 100), 2) if expected else None

    thr = interval * C.GAP_MULTIPLIER
    for idx in deltas[deltas > thr].index:
        a, b = u.loc[idx - 1, "timestamp"], u.loc[idx, "timestamp"]
        gaps.append((site, parameter, regime, a, b, round((b - a).total_seconds() / 3600, 3)))
    s["n_gaps"] = len(gaps)
    s["total_gap_hours"] = round(sum(g[5] for g in gaps), 1)

    # plausibility
    lo_p, hi_p = C.PLAUSIBLE_BOUNDS.get(parameter.split("_")[0], (-np.inf, np.inf))
    oob = u[(u.value < lo_p) | (u.value > hi_p)]
    s["n_out_of_bounds"] = len(oob)
    for _, r in oob.iterrows():
        anoms.append((site, parameter, regime, r.timestamp, r.value, r.source_file,
                      "outside_plausible_bounds"))

    # frozen runs
    v = u.value.values
    frozen, start_i = 0, 0
    for i in range(1, len(v) + 1):
        if i == len(v) or v[i] != v[i - 1]:
            if i - start_i >= C.FROZEN_RUN_THRESHOLD:
                frozen += 1
                anoms.append((site, parameter, regime, u.loc[start_i, "timestamp"],
                              v[start_i], u.loc[start_i, "source_file"],
                              f"frozen_run_len_{i-start_i}_until_{u.loc[i-1,'timestamp']}"))
            start_i = i
    s["n_frozen_runs"] = frozen

    q1, q3 = u.value.quantile([0.25, 0.75])
    iqr = q3 - q1
    lo, hi = q1 - C.IQR_MULTIPLIER * iqr, q3 + C.IQR_MULTIPLIER * iqr
    out = u[(u.value < lo) | (u.value > hi)]
    s["n_outliers_iqr"] = len(out)
    for _, r in out.iterrows():
        anoms.append((site, parameter, regime, r.timestamp, r.value, r.source_file,
                      "statistical_outlier_iqr"))

    step = u.value.diff().abs()
    med = step.median()
    jthr = med * C.JUMP_MULTIPLIER if med and med > 0 else step.quantile(0.99)
    jumps = u[step > jthr]
    s["n_jumps"] = len(jumps)
    for _, r in jumps.iterrows():
        anoms.append((site, parameter, regime, r.timestamp, r.value, r.source_file,
                      "sudden_jump"))

    return s, gaps, anoms


def main():
    master = pd.read_csv(C.PROCESSED_DIR / "master_dataset.csv", parse_dates=["timestamp"])
    master = tag_regimes(master)
    master.to_csv(C.PROCESSED_DIR / "master_tagged.csv", index=False)

    S, G, A = [], [], []
    for (site, param, regime), g in master.groupby(["site", "parameter", "regime"]):
        s, gg, aa = audit(g, site, param, regime, g.trust.iloc[0])
        S.append(s); G.extend(gg); A.extend(aa)

    pd.DataFrame(S).to_csv(C.PROCESSED_DIR / "quality_summary.csv", index=False)
    pd.DataFrame(G, columns=["site", "parameter", "regime", "gap_start", "gap_end",
                             "duration_hours"]).to_csv(C.PROCESSED_DIR / "gaps_log.csv", index=False)
    pd.DataFrame(A, columns=["site", "parameter", "regime", "timestamp", "value",
                             "source_file", "issue_type"]).to_csv(
        C.PROCESSED_DIR / "value_anomalies.csv", index=False)

    print(pd.DataFrame(S).to_string(index=False))
    print(f"\n{len(G)} gaps, {len(A)} flagged values")


if __name__ == "__main__":
    main()