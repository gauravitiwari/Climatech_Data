"""
04_site_analysis.py
===================

"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import config as C


def add_level(df):
    df = df.copy()
    is_depth = df.parameter == "depth"
    df["level"] = np.nan
    df.loc[is_depth & df.stage_m.notna(), "level"] = df.loc[is_depth & df.stage_m.notna(), "stage_m"]
    df.loc[is_depth & df.stage_m.isna(), "level"] = -df.loc[is_depth & df.stage_m.isna(), "value"]
    df.loc[~is_depth, "level"] = df.loc[~is_depth, "value"]
    return df


def analysable(df):
    if C.EXCLUDE_SUSPECT_REGIMES_FROM_ANALYSIS:
        df = df[df.trust == "ok"]
    return df[df.status != C.STATUS_MISSING]


def describe(df, site, param, regime):
    v = df.level.dropna()
    if len(v) < 3:
        return None
    obs = (df.status == C.STATUS_OBSERVED).sum()
    return dict(
        site=site, parameter=param, regime=regime,
        n=len(v), n_observed=int(obs), n_interpolated=int((df.status == C.STATUS_INTERPOLATED).sum()),
        pct_observed=round(100 * obs / len(df), 1),
        start=df.timestamp.min(), end=df.timestamp.max(),
        mean=round(v.mean(), 4), std=round(v.std(), 4), min=round(v.min(), 4),
        p05=round(v.quantile(.05), 4), q1=round(v.quantile(.25), 4),
        median=round(v.median(), 4), q3=round(v.quantile(.75), 4),
        p95=round(v.quantile(.95), 4), max=round(v.max(), 4),
        iqr=round(v.quantile(.75) - v.quantile(.25), 4),
        skew=round(v.skew(), 3),
    )


def detect_events(df, site, param, regime):
    """df must be on a regular grid, sorted, with a 'level' column."""
    d = df.sort_values("timestamp").reset_index(drop=True)
    lvl = d.level
    if lvl.notna().sum() < 20:
        return []

    dt_h = d.timestamp.diff().dt.total_seconds() / 3600
    rise = lvl.diff() / dt_h                      # units per hour, + = rising
    pos = rise[rise > 0].dropna()
    if pos.empty:
        return []

    rise_thr = np.percentile(pos, C.RISE_RATE_PERCENTILE)
    peak_thr = lvl.quantile(C.PEAK_PERCENTILE / 100)
    baseline = lvl.median()

    triggers = list(d.index[(rise > rise_thr).fillna(False)])
    events, used = [], set()

    for t in triggers:
        if t in used:
            continue
        # walk back to the start of the rise
        s = t
        while s > 0 and (rise.iloc[s - 1] > 0):
            s -= 1
        # walk forward to the peak
        p = t
        while p + 1 < len(d) and lvl.iloc[p + 1] >= lvl.iloc[p]:
            p += 1
        peak_val = lvl.iloc[p]
        if peak_val < peak_thr:
            continue
        if not (peak_val > lvl.iloc[s]):
            continue   # degenerate: no actual rise once the limb was traced
        # recession: end when level falls back toward baseline
        target = baseline + C.RECESSION_FRACTION * (peak_val - baseline)
        e = p
        while e + 1 < len(d) and lvl.iloc[e + 1] > target:
            e += 1

        dur = (d.timestamp.iloc[e] - d.timestamp.iloc[s]).total_seconds() / 3600
        if dur < C.MIN_EVENT_DURATION_H:
            continue
        used.update(range(s, e + 1))

        seg = d.iloc[s:e + 1]
        rise_h = (d.timestamp.iloc[p] - d.timestamp.iloc[s]).total_seconds() / 3600
        events.append(dict(
            site=site, parameter=param, regime=regime,
            event_start=d.timestamp.iloc[s], peak_time=d.timestamp.iloc[p],
            event_end=d.timestamp.iloc[e],
            duration_h=round(dur, 2), rising_limb_h=round(rise_h, 2),
            recession_h=round(dur - rise_h, 2),
            start_level=round(lvl.iloc[s], 4), peak_level=round(peak_val, 4),
            amplitude=round(peak_val - lvl.iloc[s], 4),
            max_rise_rate_per_h=round(rise.iloc[s:p + 1].max(), 4),
            mean_rise_rate_per_h=round((peak_val - lvl.iloc[s]) / rise_h, 4) if rise_h > 0 else np.nan,
            pct_interpolated=round(100 * (seg.status == C.STATUS_INTERPOLATED).mean(), 1),
            contains_gap=bool((seg.status == C.STATUS_MISSING).any()),
            confirmed_by_human="",     # <- you fill this in
        ))

    events.sort(key=lambda e: e["event_start"])

    # merge events separated by less than EVENT_MERGE_GAP_H
    merged = []
    for ev in events:
        if merged and (ev["event_start"] - merged[-1]["event_end"]).total_seconds() / 3600 < C.EVENT_MERGE_GAP_H:
            prev = merged[-1]
            prev["event_end"] = max(prev["event_end"], ev["event_end"])
            if ev["peak_level"] > prev["peak_level"]:
                prev.update(peak_time=ev["peak_time"], peak_level=ev["peak_level"])
            prev["duration_h"] = round((prev["event_end"] - prev["event_start"]).total_seconds() / 3600, 2)
            prev["amplitude"] = round(prev["peak_level"] - prev["start_level"], 4)
            prev["contains_gap"] = prev["contains_gap"] or ev["contains_gap"]
        else:
            merged.append(ev)
    return merged


def exceedance(df, site, param, regime):
    v = df.level.dropna()
    if len(v) < 10:
        return []
    rows = []
    for p in C.EXCEEDANCE_PERCENTILES:
        thr = v.quantile(p / 100)
        above = v >= thr
        rows.append(dict(site=site, parameter=param, regime=regime,
                         percentile=p, threshold_level=round(thr, 4),
                         n_above=int(above.sum()),
                         pct_time_above=round(100 * above.mean(), 2)))
    return rows


def main():
    clean = pd.read_csv(C.PROCESSED_DIR / "clean_dataset.csv", parse_dates=["timestamp"])
    clean = add_level(clean)

    stats, monthly, events, exc = [], [], [], []
    for (site, param, regime), g in clean.groupby(["site", "parameter", "regime"]):
        a = analysable(g)
        if a.empty:
            continue
        s = describe(a, site, param, regime)
        if s:
            stats.append(s)
        for month, mg in a.groupby(a.timestamp.dt.to_period("M")):
            v = mg.level.dropna()
            if len(v) < 3:
                continue
            monthly.append(dict(site=site, parameter=param, regime=regime,
                                month=str(month), n=len(v),
                                mean=round(v.mean(), 4), median=round(v.median(), 4),
                                min=round(v.min(), 4), max=round(v.max(), 4),
                                std=round(v.std(), 4)))
        events.extend(detect_events(g[g.trust == "ok"], site, param, regime))
        exc.extend(exceedance(a, site, param, regime))

    pd.DataFrame(stats).to_csv(C.PROCESSED_DIR / "site_statistics.csv", index=False)
    pd.DataFrame(monthly).to_csv(C.PROCESSED_DIR / "monthly_statistics.csv", index=False)
    ev = pd.DataFrame(events)
    ev.to_csv(C.PROCESSED_DIR / "events.csv", index=False)
    pd.DataFrame(exc).to_csv(C.PROCESSED_DIR / "threshold_exceedance.csv", index=False)

    print("=== Site statistics ===")
    print(pd.DataFrame(stats).to_string(index=False))
    print(f"\n=== {len(ev)} candidate events ===")
    if not ev.empty:
        print(ev[["site", "parameter", "event_start", "peak_time", "duration_h",
                  "amplitude", "contains_gap"]].to_string(index=False))
        print("\nEvents touching a data gap (treat with caution): "
              f"{int(ev.contains_gap.sum())}/{len(ev)}")
    print("\nWrite your own verdict into the confirmed_by_human column of events.csv.")


if __name__ == "__main__":
    main()