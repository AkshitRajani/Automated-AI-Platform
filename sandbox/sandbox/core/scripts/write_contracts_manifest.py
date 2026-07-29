"""Write/refresh manifest.json for the contracts category."""

import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN_DIR = ROOT / "profiles" / "F" / "attachments" / "contracts" / "generated"
MANIFEST = ROOT / "profiles" / "F" / "attachments" / "contracts" / "manifest.json"

EVIDENCE = {
    "dbm.openapi.yaml": {
        "evidence_artifact": "2025/bdd-test-agent/kb/gitlab/yaml/ccfa_tv_load_yml_metadata_ingest.json (dataBackbone references) + mb4.yml (${X.s3_bucket} substitutions)",
        "guess_level": "low — response shape directly observed; request shape conventional",
        "replace_when": "ask_f P0.2 ships real DBM OpenAPI 3.x",
    },
    "cal.openapi.yaml": {
        "evidence_artifact": "<source>/payload.txt (Step Function CAL submission payloads)",
        "guess_level": "medium — request fields observed; URL paths and async semantics conventional",
        "replace_when": "ask_f P0.3 ships real CAL OpenAPI 3.x",
    },
    "dbm.dispatcher.js": {
        "evidence_artifact": "Microcks SCRIPT dispatcher pattern; catalog from ccfa_tv_load + mb4.yml table refs",
        "guess_level": "n/a — dispatcher is mock behavior we own (the tenant won't ship dispatchers)",
        "replace_when": "Never (permanent stub). Update if delivered/dbm.openapi.yaml adds new examples.",
    },
    "cal.dispatcher.js": {
        "evidence_artifact": "Microcks kvStore TTL pattern + payload.txt async submission/polling structure",
        "guess_level": "n/a — dispatcher is mock behavior we own (the tenant won't ship dispatchers)",
        "replace_when": "Never (permanent stub). Update if delivered/cal.openapi.yaml adds new states/examples.",
    },
}

ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
manifest = {}

for fp in sorted(list(GEN_DIR.glob("*.yaml")) + list(GEN_DIR.glob("*.js"))):
    data = fp.read_bytes()
    info = EVIDENCE.get(fp.name, {})
    manifest[fp.name] = {
        "active_source": "generated",
        "generated_at": ts,
        "generated_by": "human, hand-written from real evidence (see source_artifact)",
        "source_artifact": info.get("evidence_artifact", "unknown"),
        "guess_level": info.get("guess_level", "unknown"),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "delivered_at": None,
        "delivered_sha256": None,
        "replace_when": info.get("replace_when", "the tenant ships canonical OpenAPI"),
    }

MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
print(f"wrote manifest for {len(manifest)} contract files")
