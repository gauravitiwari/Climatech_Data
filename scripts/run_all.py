"""
run_all.py
==========
Runs the whole pipeline from untouched raw files to figures.

    python scripts/run_all.py

Stops at the first failure and tells you which stage broke. Nothing is ever
written back into raw_data/ - the entire project is reproducible by deleting
processed/ and figures/ and running this again.
"""

import subprocess
import sys
from pathlib import Path

STAGES = [
    ("01_consolidate.py",     "ingest raw files -> master_dataset.csv"),
    ("02_quality_audit.py",   "quality audit -> quality_summary / gaps / anomalies"),
    ("03_gaps_and_impute.py", "classify gaps, impute short ones -> clean_dataset.csv"),
    ("04_site_analysis.py",   "site stats, events, thresholds"),
    ("05_cross_site.py",      "cross-site correlation and lag"),
    ("06_figures.py",         "figures"),
]

here = Path(__file__).parent

for script, desc in STAGES:
    print(f"\n{'='*72}\n{script}  -  {desc}\n{'='*72}")
    r = subprocess.run([sys.executable, str(here / script)])
    if r.returncode != 0:
        print(f"\nFAILED at {script}. Fix the error above and re-run.")
        sys.exit(r.returncode)

print(f"\n{'='*72}")
print("Pipeline complete. All stages ran successfully.")
print(f"Outputs written to: {here.parent / 'processed'}")
print(f"Figures written to: {here.parent / 'figures'}")