"""
06_figures.py
=============

"""

import sys
from pathlib import Path

import matplotlibgi
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import config as C

plt.rcParams.update({"figure.dpi": 130, "savefig.bbox": "tight",
                     "axes.grid": True, "grid.alpha": .3, "font.size": 9})

OBS, INT = "#1f4e79", "#d1495b"


def add_level(df):
    df = df.copy()
    is_depth = df.parameter == "depth"
    df["level"] = np.nan
    has = is_depth & df.stage_m.notna()
    df.loc[has, "level"] = df.loc[has, "stage_m"]
    df.loc[is_depth & df.stage_m.isna(), "level"] = -df.loc[is_depth & df.stage_m.isna(), "value"]
    df.loc[~is_depth, "level"] = df.loc[~is_depth, "value"]
    return df


def ylab(param, site):
    if param == "depth":
        return ("Stage (m above assumed datum)" if C.DATUM_M.get(site)
                else "Relative level (-range, m)")
    return "Velocity (m/s, assumed)"


def fig_timeseries(clean):
    for (site, param), g in clean.groupby(["site", "parameter"]):
        g = g.sort_values("timestamp")
        fig, ax = plt.subplots(figsize=(11, 3.6))
        # break the line at missing points so gaps stay visible
        y = g.level.where(g.status != C.STATUS_MISSING)
        ax.plot(g.timestamp, y, lw=.7, color=OBS, label="observed")
        imp = g[g.status == C.STATUS_INTERPOLATED]
        if not imp.empty:
            ax.scatter(imp.timestamp, imp.level, s=4, color=INT, zorder=3,
                       label=f"interpolated (n={len(imp)})")
        for _, blk in g[g.trust == "suspect"].groupby(g.regime):
            ax.axvspan(blk.timestamp.min(), blk.timestamp.max(), color="grey",
                       alpha=.18, label="suspect regime")
        ax.set_title(f"{site} - {param}")
        ax.set_ylabel(ylab(param, site))
        h, l = ax.get_legend_handles_labels()
        ax.legend(dict(zip(l, h)).values(), dict(zip(l, h)).keys(), fontsize=7, loc="upper right")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        fig.savefig(C.FIGURES_DIR / f"fig01_{site}_{param}_timeseries.png")
        plt.close(fig)


def fig_availability(clean):
    streams = list(clean.groupby(["site", "parameter"]).groups)
    fig, ax = plt.subplots(figsize=(11, .6 * len(streams) + 1.6))
    for i, key in enumerate(streams):
        g = clean[(clean.site == key[0]) & (clean.parameter == key[1])].sort_values("timestamp")
        ok = g[g.status != C.STATUS_MISSING]
        ax.scatter(ok.timestamp, np.full(len(ok), i), s=1, color=OBS)
    ax.set_yticks(range(len(streams)))
    ax.set_yticklabels([f"{a} {b}" for a, b in streams])
    ax.set_title("Data availability (each mark = one 15-min record present)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    fig.savefig(C.FIGURES_DIR / "fig02_data_availability.png")
    plt.close(fig)


def fig_gaps(gaps):
    if gaps.empty:
        return
    fig, ax = plt.subplots(figsize=(7, 4))
    for cls, col in [("short", "#4c9f70"), ("medium", "#e8a33d"), ("long", "#c1292e")]:
        d = gaps[gaps.gap_class == cls].duration_hours
        if not d.empty:
            ax.hist(d, bins=np.logspace(np.log10(max(d.min(), .01)),
                                        np.log10(d.max() + 1), 25),
                    alpha=.65, label=f"{cls} (n={len(d)})", color=col)
    ax.set_xscale("log")
    ax.set_xlabel("Gap duration (hours, log scale)")
    ax.set_ylabel("Count")
    ax.set_title("Gap duration distribution by class")
    ax.legend(fontsize=8)
    fig.savefig(C.FIGURES_DIR / "fig03_gap_duration_distribution.png")
    plt.close(fig)


def fig_monthly(clean):
    groups = list(clean.groupby(["site", "parameter"]))
    fig, axes = plt.subplots(len(groups), 1, figsize=(10, 2.8 * len(groups)), squeeze=False)
    for ax, ((site, param), g) in zip(axes.ravel(), groups):
        g = g[(g.status != C.STATUS_MISSING) & (g.trust == "ok")]
        if g.empty:
            continue
        months = sorted(g.timestamp.dt.to_period("M").unique())
        ax.boxplot([g.loc[g.timestamp.dt.to_period("M") == m, "level"].dropna() for m in months],
                   showfliers=False)
        ax.set_xticks(range(1, len(months) + 1))
        ax.set_xticklabels([str(m) for m in months])
        ax.set_title(f"{site} - {param}: monthly distribution")
        ax.set_ylabel(ylab(param, site))
        ax.tick_params(axis="x", rotation=45, labelsize=7)
    fig.tight_layout()
    fig.savefig(C.FIGURES_DIR / "fig04_monthly_boxplots.png")
    plt.close(fig)


def fig_events(clean, events):
    if events.empty:
        return
    for (site, param), evs in events.groupby(["site", "parameter"]):
        evs = evs.reset_index(drop=True)
        n = len(evs)
        ncol = 3
        nrow = int(np.ceil(n / ncol))
        fig, axes = plt.subplots(nrow, ncol, figsize=(3.6 * ncol, 2.4 * nrow), squeeze=False)
        g = clean[(clean.site == site) & (clean.parameter == param)].sort_values("timestamp")
        for ax, (_, e) in zip(axes.ravel(), evs.iterrows()):
            pad = pd.Timedelta(hours=max(e.duration_h * .5, 3))
            w = g[g.timestamp.between(e.event_start - pad, e.event_end + pad)]
            ax.plot(w.timestamp, w.level.where(w.status != C.STATUS_MISSING), lw=.9, color=OBS)
            ax.axvspan(e.event_start, e.event_end, color="#f0c808", alpha=.25)
            ax.axvline(e.peak_time, color=INT, lw=.8, ls="--")
            ax.set_title(f"{e.event_start:%d %b %H:%M}  amp={e.amplitude:.2f}", fontsize=7)
            ax.tick_params(labelsize=6)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m\n%H:%M"))
        for ax in axes.ravel()[n:]:
            ax.axis("off")
        fig.suptitle(f"Candidate events - {site} {param} (shaded = event, dashed = peak)",
                     fontsize=9)
        fig.tight_layout()
        fig.savefig(C.FIGURES_DIR / f"fig05_events_{site}_{param}.png")
        plt.close(fig)


def fig_lag(lag):
    if lag.empty:
        return
    pairs = lag.groupby(["series_a", "series_b"])
    fig, ax = plt.subplots(figsize=(8, 4))
    for (a, b), d in pairs:
        d = d.sort_values("lag_hours")
        ax.plot(d.lag_hours, d.r, lw=1, label=f"{a} vs {b}")
    ax.axvline(0, color="k", lw=.6)
    ax.axhline(0, color="k", lw=.6)
    ax.set_xlabel("Lag (hours) - positive means second series lags first")
    ax.set_ylabel("Pearson r")
    ax.set_title("Lagged cross-correlation (co-response timing, not travel time)")
    ax.legend(fontsize=7)
    fig.savefig(C.FIGURES_DIR / "fig06_cross_site_lag.png")
    plt.close(fig)


def fig_exceedance(clean):
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for (site, param), g in clean.groupby(["site", "parameter"]):
        v = g.loc[(g.status != C.STATUS_MISSING) & (g.trust == "ok"), "level"].dropna()
        if len(v) < 20:
            continue
        s = np.sort(v)[::-1]
        ax.plot(100 * np.arange(1, len(s) + 1) / len(s), s, lw=1, label=f"{site} {param}")
    ax.set_xlabel("% of time equalled or exceeded")
    ax.set_ylabel("Level / velocity")
    ax.set_title("Duration curves (mixed units - compare shape, not magnitude)")
    ax.legend(fontsize=7)
    fig.savefig(C.FIGURES_DIR / "fig07_exceedance_curves.png")
    plt.close(fig)


def fig_regimes(clean):
    g = clean[(clean.site == "Kamand") & (clean.parameter == "depth")].sort_values("timestamp")
    if g.empty:
        return
    fig, ax = plt.subplots(figsize=(10, 3.6))
    for regime, d in g.groupby("regime"):
        ax.plot(d.timestamp, d.value.where(d.status != C.STATUS_MISSING), lw=.8,
                label=f"{regime} ({d.trust.iloc[0]})")
    ax.set_ylabel("Raw sensor range (m)")
    ax.set_title("Kamand depth sensor: regime break across the Sep-Nov 2025 outage\n"
                 "(raw range shown, not stage - note the non-overlapping value bands)")
    ax.legend(fontsize=7)
    fig.savefig(C.FIGURES_DIR / "fig08_kamand_depth_regimes.png")
    plt.close(fig)


def main():
    clean = add_level(pd.read_csv(C.PROCESSED_DIR / "clean_dataset.csv", parse_dates=["timestamp"]))
    gaps = pd.read_csv(C.PROCESSED_DIR / "gaps_classified.csv",
                       parse_dates=["gap_start", "gap_end"])
    events = pd.read_csv(C.PROCESSED_DIR / "events.csv",
                         parse_dates=["event_start", "peak_time", "event_end"])
    lag_path = C.PROCESSED_DIR / "cross_site_lag.csv"
    lag = pd.read_csv(lag_path) if lag_path.stat().st_size > 5 else pd.DataFrame()

    fig_timeseries(clean); print("  fig01 timeseries")
    fig_availability(clean); print("  fig02 availability")
    fig_gaps(gaps); print("  fig03 gaps")
    fig_monthly(clean); print("  fig04 monthly")
    fig_events(clean, events); print("  fig05 events")
    fig_lag(lag); print("  fig06 lag")
    fig_exceedance(clean); print("  fig07 exceedance")
    fig_regimes(clean); print("  fig08 regimes")
    print(f"\nFigures written to {C.FIGURES_DIR}")


if __name__ == "__main__":
    main()