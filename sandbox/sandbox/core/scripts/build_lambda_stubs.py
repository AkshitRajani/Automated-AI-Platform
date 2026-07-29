"""
Generate stub Lambda zips for every Lambda named in profiles/default/spec.yaml.

Each zip contains a smart-stub `handler.py` plus (when present) per-lambda
fixtures bundled at the root of the zip:

    handler.py           — fidelity-aware stub (loads fidelity.json at boot)
    fidelity.json        — {"tier": "L1|L2|L3", "source": "...", "input_schema": {...}}
    input_example.json   — canonical request payload (for L2/L3 only)
    output_example.json  — canonical response payload (for L2/L3 only)

Fixtures live under `profiles/default/lambdas/<lambda_name>/`. If a lambda has no
fixture dir, it ships at L1 (echo) with the same handler template — the
handler simply detects that fidelity.json is missing and falls back to L1.

When the tenant ships real handler code: drop the real .zip into
`profiles/default/attachments/lambdas/delivered/<name>.zip`. The seeder picks
delivered over generated.

Usage:
    python3 scripts/build_lambda_stubs.py
"""

import datetime
import hashlib
import io
import json
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "profiles" / "F" / "spec.yaml"
FIXTURES_DIR = ROOT / "profiles" / "F" / "lambdas"
DST_DIR = ROOT / "profiles" / "F" / "attachments" / "lambdas" / "generated"
MANIFEST_PATH = ROOT / "profiles" / "F" / "attachments" / "lambdas" / "manifest.json"
HANDLER_TEMPLATE_PATH = ROOT / "scripts" / "smart_stub_handler.py"


def _load_handler_template() -> str:
    """The smart-stub handler. Lives in scripts/smart_stub_handler.py so it
    can be unit-tested independently. We embed it verbatim into every zip."""
    if HANDLER_TEMPLATE_PATH.exists():
        return HANDLER_TEMPLATE_PATH.read_text()
    # Fallback minimal echo handler if the template is missing.
    return (
        "def lambda_handler(event, context):\n"
        "    return {}\n"
    )


def _collect_fixtures(lambda_name: str) -> dict:
    """Return {filename: bytes} of fixture files to bundle into the zip.

    Reads from profiles/default/lambdas/<name>/. Returns {} if no dir exists,
    which makes the handler default to L1 echo behavior at runtime.
    """
    fdir = FIXTURES_DIR / lambda_name
    if not fdir.exists():
        return {}
    out = {}
    for fname in ("fidelity.json", "input_example.json", "output_example.json"):
        p = fdir / fname
        if p.exists():
            out[fname] = p.read_bytes()
    return out


def main() -> None:
    DST_DIR.mkdir(parents=True, exist_ok=True)

    with open(SPEC_PATH) as f:
        spec = yaml.safe_load(f)

    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    handler_src = _load_handler_template()
    manifest = {}

    for lam in spec.get("lambdas", []):
        name = lam["lambda_name"]
        zip_path = DST_DIR / f"{name}.zip"
        fixtures = _collect_fixtures(name)
        # Determine effective tier from fixtures, default L1.
        tier = "L1"
        if "fidelity.json" in fixtures:
            try:
                tier = json.loads(fixtures["fidelity.json"]).get("tier", "L1")
            except Exception:
                tier = "L1"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("handler.py", handler_src)
            # Always write a fidelity.json so the handler has a deterministic
            # marker. If the lambda has no fixture dir, we synthesize a
            # default-L1 fidelity.json so the handler doesn't have to guess.
            if "fidelity.json" not in fixtures:
                fixtures["fidelity.json"] = json.dumps({
                    "tier": "L1",
                    "source": "default",
                    "lambda_name": name,
                    "tier_kind": lam.get("tier", "core"),
                    "source_suite": lam.get("source_suite"),
                    "notes": "no per-lambda fixture dir; defaulting to L1 echo",
                }, indent=2).encode()
            else:
                # Splice lambda_name into fidelity.json so the handler logs it
                # without needing a separate config.
                try:
                    fid = json.loads(fixtures["fidelity.json"])
                    fid.setdefault("lambda_name", name)
                    fid.setdefault("tier_kind", lam.get("tier", "core"))
                    fid.setdefault("source_suite", lam.get("source_suite"))
                    fixtures["fidelity.json"] = json.dumps(fid, indent=2).encode()
                except Exception:
                    pass
            for fname, fbytes in fixtures.items():
                z.writestr(fname, fbytes)

        data = buf.getvalue()
        zip_path.write_bytes(data)

        manifest[f"{name}.zip"] = {
            "active_source": "generated",
            "generated_at": ts,
            "generated_by": "scripts/build_lambda_stubs.py",
            "tier": tier,
            "tier_kind": lam.get("tier", "core"),
            "source_suite": lam.get("source_suite"),
            "fixtures_bundled": sorted(fixtures.keys()),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "delivered_at": None,
            "delivered_sha256": None,
            "replace_when": "the tenant ships real handler.zip (ask_f new item)",
        }

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(manifest)} stub zips to {DST_DIR}")
    by_tier = {}
    for entry in manifest.values():
        by_tier[entry["tier"]] = by_tier.get(entry["tier"], 0) + 1
    print(f"  by tier: {by_tier}")
    print(f"wrote manifest to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
