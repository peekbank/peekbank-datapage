#!/usr/bin/env python3
"""Verify a staged export: exact MySQL COUNT(*) per table vs the .done
markers and the parquet metadata row counts. Exit nonzero on any mismatch.

Usage: python3 migration/verify_export.py --version 2021.1
"""

import argparse
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_mysql import connect, EXCLUDE_TABLES  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGING = REPO_ROOT / "migration" / "staging"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    args = ap.parse_args()
    version = args.version

    con = connect(version)
    cur = con.cursor()
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema=%s AND table_type='BASE TABLE'", (version,))
    tables = sorted(t for (t,) in cur.fetchall() if t not in EXCLUDE_TABLES)

    ok = True
    print(f"{'table':24s} {'mysql':>12s} {'.done':>12s} {'parquet':>12s}")
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM `{t}`")
        mysql_n = cur.fetchone()[0]
        d = STAGING / version / t
        done = json.loads((d / ".done").read_text()) if (d / ".done").exists() else None
        done_n = done["rows"] if done else -1
        pq_n = sum(pq.read_metadata(f).num_rows for f in sorted(d.glob("part-*.parquet")))
        status = "OK" if mysql_n == done_n == pq_n else "MISMATCH"
        ok = ok and (status == "OK")
        print(f"{t:24s} {mysql_n:12,d} {done_n:12,d} {pq_n:12,d}  {status}")
    con.close()
    if not ok:
        sys.exit(f"{version}: MISMATCH FOUND")
    print(f"{version}: all tables verified")


if __name__ == "__main__":
    main()
