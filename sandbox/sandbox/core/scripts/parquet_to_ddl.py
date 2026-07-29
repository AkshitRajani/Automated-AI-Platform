"""
Generate Postgres DDL from parquet schemas.

Usage:
    python3 parquet_to_ddl.py <parquet_path> <table_name> > out.sql
"""

import sys
import re
import pyarrow as pa
import pyarrow.parquet as pq


def parquet_type_to_pg(pa_type) -> str:
    s = str(pa_type)

    if s == "string":
        return "TEXT"
    if s in ("int8", "int16", "int32"):
        return "INTEGER"
    if s in ("int64",):
        return "BIGINT"
    if s in ("float", "float32"):
        return "REAL"
    if s in ("double", "float64"):
        return "DOUBLE PRECISION"
    if s == "bool":
        return "BOOLEAN"
    if s.startswith("date"):
        return "DATE"
    if s.startswith("timestamp"):
        return "TIMESTAMP"
    if s == "null":
        return "TEXT"  # parquet "null type" = all-null column; default to TEXT

    m = re.match(r"decimal\d+\((\d+),\s*(\d+)\)", s)
    if m:
        precision, scale = m.group(1), m.group(2)
        return f"NUMERIC({precision},{scale})"

    raise ValueError(f"Unsupported parquet type: {s}")


def emit_ddl(parquet_path: str, table_name: str) -> str:
    schema = pq.read_schema(parquet_path)

    lines = [
        f"-- Auto-generated from {parquet_path}",
        f"-- {len(schema)} columns",
        f"-- Source: pyarrow {pa.__version__}",
        "",
        f"DROP TABLE IF EXISTS {table_name};",
        f"CREATE TABLE {table_name} (",
    ]

    col_lines = []
    for field in schema:
        pg_type = parquet_type_to_pg(field.type)
        # Quote column names verbatim — the tenant has mixed casing (bch_obj_id lowercase,
        # LN_DFLT_UPB_AMT uppercase). Without quotes Postgres folds to lowercase.
        col_lines.append(f'  "{field.name}" {pg_type}')

    lines.append(",\n".join(col_lines))
    lines.append(");")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    print(emit_ddl(sys.argv[1], sys.argv[2]))
