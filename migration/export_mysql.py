#!/usr/bin/env python3
"""Export one peekbank release from the hosted MariaDB to parquet.

Adapted from langcog/childes-db redivis/export_mysql.py. Streams each table
with keyset pagination on its primary key (peekbank PKs are `<table>_id`)
and writes zstd parquet part files, so an interrupted run resumes at the
last completed part. `aoi_timepoints_rle` has no PK and is streamed in one
ordered pass (small; restart-on-failure). Django bookkeeping and the
rebuildable `aoi_timepoints_indexed` intermediate are excluded.

Usage: python3 migration/export_mysql.py --version 2021.1
Credentials are the public read-only account (published in the peekbank
README); override with PEEKBANK_MYSQL_HOST/USER/PASSWORD/PORT env vars.
"""

import argparse
import datetime
import fcntl
import json
import os
import sys
import time
from pathlib import Path

import pymysql
import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parent.parent
CA_PATH = REPO_ROOT / "repos" / "peekbankr" / "inst" / "certs" / "peekbank-ca.pem"
EXCLUDE_TABLES = {"django_migrations", "admin", "aoi_timepoints_indexed"}
CHUNK_ROWS = 250_000   # rows per SELECT
PART_ROWS = 500_000    # rows per parquet part file

MYSQL_TO_ARROW = {
    "bigint": pa.int64(), "int": pa.int64(), "smallint": pa.int64(),
    "tinyint": pa.int64(), "mediumint": pa.int64(),
    "varchar": pa.string(), "char": pa.string(), "text": pa.string(),
    "longtext": pa.string(), "mediumtext": pa.string(), "enum": pa.string(),
    "json": pa.string(),
    "date": pa.date32(), "datetime": pa.timestamp("s"), "timestamp": pa.timestamp("s"),
    "double": pa.float64(), "float": pa.float64(), "decimal": pa.float64(),
}


def connect(version):
    return pymysql.connect(
        host=os.environ.get("PEEKBANK_MYSQL_HOST", "34.210.173.143"),
        port=int(os.environ.get("PEEKBANK_MYSQL_PORT", "3307")),
        user=os.environ.get("PEEKBANK_MYSQL_USER", "reader"),
        password=os.environ.get("PEEKBANK_MYSQL_PASSWORD", "gazeofraccoons"),
        database=version,
        charset="utf8mb4", connect_timeout=30, read_timeout=600,
        ssl={"ca": str(CA_PATH)},
    )


def table_schema(cur, version, table):
    cur.execute(
        """SELECT column_name, data_type FROM information_schema.columns
           WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position""",
        (version, table),
    )
    fields = []
    for name, dtype in cur.fetchall():
        if dtype not in MYSQL_TO_ARROW:
            sys.exit(f"unmapped MySQL type {dtype} in {table}.{name}")
        fields.append(pa.field(name, MYSQL_TO_ARROW[dtype]))
    return pa.schema(fields)


def primary_key(cur, version, table):
    cur.execute(
        """SELECT column_name FROM information_schema.key_column_usage
           WHERE table_schema=%s AND table_name=%s AND constraint_name='PRIMARY'
           ORDER BY ordinal_position""",
        (version, table),
    )
    cols = [c for (c,) in cur.fetchall()]
    return cols[0] if len(cols) == 1 else None


def coerce(value, typ):
    if value is None:
        return None
    if pa.types.is_date(typ) or pa.types.is_timestamp(typ):
        if not isinstance(value, (datetime.date, datetime.datetime)):
            return None
    return value


def rows_to_table(rows, schema):
    cols = []
    for i, field in enumerate(schema):
        cols.append(pa.array([coerce(r[i], field.type) for r in rows], type=field.type))
    return pa.Table.from_arrays(cols, schema=schema)


def export_table(con, version, table, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    done_marker = out_dir / ".done"
    progress_file = out_dir / ".progress.json"
    if done_marker.exists():
        print(f"  {table}: already done, skipping")
        return
    lock_file = open(out_dir / ".lock", "w")
    fcntl.flock(lock_file, fcntl.LOCK_EX)
    if done_marker.exists():
        print(f"  {table}: done by concurrent process, skipping")
        lock_file.close()
        return

    cur = con.cursor()
    schema = table_schema(cur, version, table)
    colnames = ", ".join(f"`{f.name}`" for f in schema)
    pk = primary_key(cur, version, table)

    # peekbank ids start at 0, so the keyset sentinel must sit below 0
    last_id, part_num, total = -1, 0, 0
    if pk is not None and progress_file.exists():
        p = json.loads(progress_file.read_text())
        last_id, part_num, total = p["last_id"], p["part_num"], p["total"]
        print(f"  {table}: resuming after {pk} {last_id} (part {part_num}, {total:,} rows)")

    buffer = []
    t0 = time.time()

    def flush_part():
        nonlocal buffer, part_num
        if not buffer:
            return
        part_path = out_dir / f"part-{part_num:05d}.parquet"
        tmp_path = out_dir / f".tmp-{part_num:05d}.parquet"
        pq.write_table(rows_to_table(buffer, schema), tmp_path, compression="zstd")
        tmp_path.rename(part_path)
        part_num += 1
        buffer = []
        if pk is not None:
            progress_file.write_text(json.dumps(
                {"last_id": last_id, "part_num": part_num, "total": total}))

    if pk is not None:
        while True:
            cur.execute(
                f"SELECT {colnames} FROM `{table}` WHERE `{pk}` > %s "
                f"ORDER BY `{pk}` LIMIT %s",
                (last_id, CHUNK_ROWS),
            )
            rows = cur.fetchall()
            if not rows:
                break
            id_idx = [f.name for f in schema].index(pk)
            last_id = rows[-1][id_idx]
            total += len(rows)
            buffer.extend(rows)
            if len(buffer) >= PART_ROWS:
                flush_part()
                rate = total / (time.time() - t0)
                print(f"  {table}: {total:,} rows ({rate:,.0f} rows/s)", flush=True)
    else:
        # no single-column PK (aoi_timepoints_rle): one ordered streaming pass
        # with an unbuffered cursor; interrupt restarts the whole table
        for f in out_dir.glob("part-*.parquet"):
            f.unlink()
        scur = con.cursor(pymysql.cursors.SSCursor)
        scur.execute(
            f"SELECT {colnames} FROM `{table}` "
            f"ORDER BY administration_id, trial_id, t_norm")
        while True:
            rows = scur.fetchmany(CHUNK_ROWS)
            if not rows:
                break
            total += len(rows)
            buffer.extend(rows)
            if len(buffer) >= PART_ROWS:
                flush_part()
                print(f"  {table}: {total:,} rows", flush=True)
        scur.close()

    flush_part()
    if total == 0:
        # explicit empty-schema part: with zero uploads, Redivis's "replace"
        # strategy would silently keep the previous version's rows
        part_path = out_dir / "part-00000.parquet"
        pq.write_table(rows_to_table([], schema), part_path, compression="zstd")
        part_num = 1
    done_marker.write_text(json.dumps({"rows": total, "parts": part_num}))
    progress_file.unlink(missing_ok=True)
    fcntl.flock(lock_file, fcntl.LOCK_UN)
    lock_file.close()
    print(f"  {table}: DONE, {total:,} rows in {part_num} parts "
          f"({time.time() - t0:,.0f}s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--staging-root", default=str(REPO_ROOT / "migration" / "staging"))
    ap.add_argument("--tables", nargs="*", default=None)
    args = ap.parse_args()

    con = connect(args.version)
    cur = con.cursor()
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema=%s AND table_type='BASE TABLE'", (args.version,))
    tables = sorted(t for (t,) in cur.fetchall() if t not in EXCLUDE_TABLES)
    if args.tables:
        tables = [t for t in tables if t in set(args.tables)]

    out_root = Path(args.staging_root) / args.version
    print(f"exporting {args.version}: {tables} -> {out_root}")

    def size_key(t):
        cur.execute(
            "SELECT COALESCE(data_length,0) FROM information_schema.tables "
            "WHERE table_schema=%s AND table_name=%s", (args.version, t))
        return cur.fetchone()[0]
    for table in sorted(tables, key=size_key):
        export_table(con, args.version, table, out_root / table)
    con.close()
    print(f"export of {args.version} complete")


if __name__ == "__main__":
    main()
