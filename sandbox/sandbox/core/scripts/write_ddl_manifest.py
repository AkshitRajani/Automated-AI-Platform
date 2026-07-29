"""
Write/refresh manifest.json for the postgres/ddl category.
Run after parquet_to_ddl.py regenerates the .sql files.
"""

import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN_DIR = ROOT / "profiles" / "F" / "attachments" / "postgres" / "ddl" / "generated"
MANIFEST = ROOT / "profiles" / "F" / "attachments" / "postgres" / "ddl" / "manifest.json"

SOURCE_MAP = {
    "LN_INTRM_TM_SERS_DATA_PREP_SPST.sql": "<source>/data/inputs/all_loans.parquet",
    "LN_TM_SERS_MBS4PLUS.sql": "<source>/data/expected/LN_TM_SERS_MBS4PLUS.parquet",
}

ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

manifest = {}
for sql_file in sorted(GEN_DIR.glob("*.sql")):
    data = sql_file.read_bytes()
    manifest[sql_file.name] = {
        "active_source": "generated",
        "generated_at": ts,
        "generated_by": "scripts/parquet_to_ddl.py",
        "source_artifact": SOURCE_MAP.get(sql_file.name, "unknown"),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "delivered_at": None,
        "delivered_sha256": None,
        "replace_when": "the tenant ships canonical CREATE TABLE DDL (drop into ../delivered/)",
    }

MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
print(f"wrote manifest for {len(manifest)} DDL files")
