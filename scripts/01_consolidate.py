"""
01_consolidate.py

"""

import csv
import re
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from dateutil import parser as dateparser

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C


# --------------------------------------------------------------------------
# filename matching
# --------------------------------------------------------------------------
def _norm(name):
    """depth_measurements_N__1_.csv -> depthmeasurementsn1.csv"""
    return re.sub(r"[_\-\s()]+", "", name).lower()


def find_raw_file(registered_name):
    target = _norm(registered_name)
    matches = [p for p in C.RAW_DIR.rglob("*.csv") if _norm(p.name) == target]
    if not matches:
        available = sorted(p.name for p in C.RAW_DIR.rglob("*.csv"))
        raise FileNotFoundError(
            f"\n  Registered file not found: {registered_name}\n"
            f"  Looked under: {C.RAW_DIR}\n"
            f"  Files actually present:\n    " + "\n    ".join(available) +
            "\n  Fix the key in config.FILES to match, or rename the file."
        )
    if len(matches) > 1:
        print(f"  [warn] {registered_name} matched {len(matches)} files; using {matches[0]}")
    return matches[0]


# --------------------------------------------------------------------------
# parsing helpers
# --------------------------------------------------------------------------
TS_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
    "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%d/%m/%y %H:%M",
]
TS_EMBEDDED = re.compile(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)")
NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$")


def parse_timestamp(raw):
    raw = raw.strip()
    for fmt in TS_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:
        return dateparser.parse(raw, dayfirst=True)
    except (ValueError, OverflowError, TypeError):
        return None


def safe_floats(fields):
    return [float(f) for f in (x.strip() for x in fields) if f and NUM_RE.match(f)]


def split_merged_row(fields):
    """A merged line looks like [ts, v, v, ..., '12.34' + '2025-09-05 00:09', v, ...].
    Find the cell containing a second embedded timestamp and cut there.
    Returns a list of field-lists (1 if nothing to split)."""
    for i, f in enumerate(fields):
        if i == 0:
            continue
        m = TS_EMBEDDED.search(f)
        if m:
            head_val = f[:m.start()]
            first = fields[:i] + ([head_val] if head_val.strip() else [])
            second = [m.group(1)] + [f[m.end():]] if f[m.end():].strip() else [m.group(1)]
            second = second + fields[i + 1:]
            return [first, second]
    return [fields]


# --------------------------------------------------------------------------
# loader
# --------------------------------------------------------------------------
def load_file(path, site, parameter, has_header, has_summary_col, corrupt_header=False):
    rows, anomalies = [], []
    expected = None

    def emit(fields, line_no, status):
        nonlocal expected
        ts_raw, *rest = fields
        ts = parse_timestamp(ts_raw)
        if ts is None:
            anomalies.append((path.name, line_no, "unparseable_timestamp", ",".join(fields)[:120]))
            return
        vals = safe_floats(rest)
        if not vals:
            anomalies.append((path.name, line_no, "no_usable_numeric_readings", ",".join(fields)[:120]))
            return
        # drop the trailing pre-computed summary value (e.g. median_depth)
        if has_summary_col and len(vals) > 1:
            vals = vals[:-1]
        if expected is None:
            expected = len(vals)
        rows.append(dict(
            timestamp=ts, site=site, parameter=parameter,
            value=float(np.median(vals)),
            n_subreadings=len(vals),
            std_subreadings=float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0,
            source_file=path.name, status=status,
        ))

    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for line_no, fields in enumerate(csv.reader(fh), start=1):
            if not fields or all(f.strip() == "" for f in fields):
                continue
            if line_no == 1:
                if corrupt_header:
                    anomalies.append((path.name, 1, "corrupted_header_row_recovered",
                                      ",".join(fields)[:120]))
                    # the "header" is actually a data row with a stray label in
                    # cell 0 - recover it rather than throwing the row away
                    emit(fields[1:], 1, C.STATUS_CORRECTED)
                    continue
                if has_header:
                    continue

            fields = [f for f in fields if f.strip() != ""]
            if not fields:
                continue

            parts = split_merged_row(fields)
            if len(parts) > 1:
                anomalies.append((path.name, line_no, "merged_line_split_and_recovered",
                                  ",".join(fields)[:150]))
                for p in parts:
                    emit(p, line_no, C.STATUS_CORRECTED)
            else:
                emit(fields, line_no, C.STATUS_OBSERVED)

    df = pd.DataFrame(rows)
    if not df.empty:
        dupe = df.duplicated(subset=["timestamp", "value"], keep="first")
        if dupe.sum():
            anomalies.append((path.name, -1, f"{int(dupe.sum())}_exact_duplicate_rows_removed", ""))
        df = df[~dupe].reset_index(drop=True)
    return df, anomalies


def load_vel_K(path):
    """vel_K.csv has its own schema. fd == 67.97 * v to within 0.03%, so fd is
    the raw Doppler frequency shift and carries no independent information;
    only the velocity columns are kept. v_med12 is the representative value."""
    vk = pd.read_csv(path)
    vk["timestamp"] = pd.to_datetime(vk["datetime"], errors="coerce")
    bad = int(vk["timestamp"].isna().sum())
    vk = vk.dropna(subset=["timestamp"])
    out = pd.DataFrame(dict(
        timestamp=vk["timestamp"], site="Kamand", parameter="velocity_UNCONFIRMED",
        value=vk["v_med12"].values,
        n_subreadings=np.nan, std_subreadings=vk[["v_raw", "v_ema", "v_med12"]].std(axis=1).values,
        source_file=path.name, status=C.STATUS_OBSERVED,
    ))
    anom = [(path.name, -1, f"{bad}_unparseable_timestamps", "")] if bad else []
    return out, anom


# --------------------------------------------------------------------------
def main():
    frames, anomalies = [], []
    print(f"Raw dir: {C.RAW_DIR}\n")

    for fname, cfg in C.FILES.items():
        path = find_raw_file(fname)
        df, anom = load_file(
            path, cfg["site"], cfg["parameter"], cfg["has_header"],
            cfg["has_summary_col"], cfg.get("corrupt_header", False))
        print(f"  {fname:32s} -> {len(df):6d} rows  {len(anom):3d} anomalies")
        frames.append(df)
        anomalies.extend(anom)

    vk_path = find_raw_file("vel_K.csv")
    vk, anom = load_vel_K(vk_path)
    print(f"  {'vel_K.csv':32s} -> {len(vk):6d} rows  (quarantined: velocity_UNCONFIRMED)")
    frames.append(vk)
    anomalies.extend(anom)

    master = (pd.concat(frames, ignore_index=True)
                .sort_values(["site", "parameter", "timestamp"])
                .reset_index(drop=True))
    master.to_csv(C.PROCESSED_DIR / "master_dataset.csv", index=False)

    pd.DataFrame(anomalies, columns=["source_file", "line_no", "issue_type", "raw_snippet"]) \
      .to_csv(C.PROCESSED_DIR / "ingestion_anomaly_log.csv", index=False)

    print(f"\n{len(master)} rows -> {C.PROCESSED_DIR/'master_dataset.csv'}")
    print(f"{len(anomalies)} ingestion anomalies logged\n")
    print(master.groupby(["site", "parameter"]).agg(
        n=("value", "size"), start=("timestamp", "min"), end=("timestamp", "max"),
        vmin=("value", "min"), vmax=("value", "max")).to_string())

    expected_streams = {(c["site"], c["parameter"]) for c in C.FILES.values()}
    got = set(map(tuple, master[["site", "parameter"]].drop_duplicates().values))
    if expected_streams - got:
        raise RuntimeError(f"Streams produced no rows: {expected_streams - got}")
    print("\nAll registered streams present.")


if __name__ == "__main__":
    main()