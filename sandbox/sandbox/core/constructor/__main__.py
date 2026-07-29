"""Entry point for the constructor.

Usage:
    python3 -m constructor up <profile_dir> [--emit-only]

Phase 0 supports --emit-only: writes docker-compose.yml + seeder.sh + manifest,
prints the sandbox_id, does NOT run Docker. Operator inspects then runs manually.
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

from .build_compose import build_compose
from .build_seeder import build_seeder
from .sandbox_id import compute_sandbox_id


def cmd_up(profile_dir: Path, emit_only: bool) -> int:
    if not (profile_dir / "spec.yaml").exists():
        print(f"error: {profile_dir}/spec.yaml not found", file=sys.stderr)
        return 2

    spec = yaml.safe_load((profile_dir / "spec.yaml").read_text())

    # Profile relpath from repo root (assumes run from s_v4/).
    repo_root = Path.cwd()
    profile_rel = profile_dir.resolve().relative_to(repo_root.resolve()).as_posix()

    compose_yml = build_compose(spec, profile_rel)
    seeder_sh = build_seeder(spec, profile_rel)

    (profile_dir / "docker-compose.yml").write_text(compose_yml)
    seeder_path = profile_dir / "seeder.sh"
    seeder_path.write_text(seeder_sh)
    seeder_path.chmod(0o755)

    sandbox_id = compute_sandbox_id(profile_dir)

    # Per-lambda fidelity roster: read fidelity.json next to each lambda's
    # fixture dir, fall back to L1 if no fixture dir exists yet.
    lambdas_dir = profile_dir / "lambdas"
    lambda_roster = []
    for lam in spec.get("lambdas") or []:
        name = lam["lambda_name"]
        fid_path = lambdas_dir / name / "fidelity.json"
        if fid_path.exists():
            try:
                fid = json.loads(fid_path.read_text())
            except Exception:
                fid = {"tier": "L1", "source": "default", "notes": f"fidelity.json unparseable at {fid_path}"}
        else:
            fid = {"tier": "L1", "source": "default", "notes": "no fixture dir; defaulting to L1 echo"}
        lambda_roster.append({
            "name": name,
            "tier": fid.get("tier", "L1"),
            "source": fid.get("source", "default"),
            "tier_kind": lam.get("tier", "core"),  # core | reference
            "source_suite": lam.get("source_suite"),
            "fixture_dir": str((lambdas_dir / name).resolve()) if fid_path.exists() else None,
        })

    manifest = {
        "sandbox_id": sandbox_id,
        "profile_dir": str(profile_dir.resolve()),
        "tenant": spec.get("tenant", {}).get("name", "unknown"),
        "snapshot_date": spec.get("tenant", {}).get("snapshot_date"),
        "spec_version": spec.get("spec_version"),
        "endpoints": {
            "localstack": "http://localhost:4566",
            "microcks": "http://localhost:8080",
            "postgres": "postgresql://postgres:postgres@127.0.0.1:5433/aap_sandbox",
        },
        "counts": {
            "lambdas": len(spec.get("lambdas") or []),
            "lambdas_core": sum(1 for l in (spec.get("lambdas") or []) if l.get("tier", "core") == "core"),
            "lambdas_reference": sum(1 for l in (spec.get("lambdas") or []) if l.get("tier") == "reference"),
            "step_functions": len(spec.get("step_functions") or []),
            "dynamodb_tables": len(spec.get("dynamodb") or []),
            "s3_buckets": len(spec.get("s3_buckets") or []),
            "glue_jobs": len(spec.get("glue_jobs") or []),
            "behavioral_contracts": len(spec.get("behavioral_contracts") or []),
            "business_rules": len(spec.get("business_rules") or []),
            "tickets": len(spec.get("tickets") or []),
        },
        "lambda_roster": lambda_roster,
        "fidelity_summary": {
            "L3": sum(1 for r in lambda_roster if r["tier"] == "L3"),
            "L2": sum(1 for r in lambda_roster if r["tier"] == "L2"),
            "L1": sum(1 for r in lambda_roster if r["tier"] == "L1"),
        },
    }
    (profile_dir / "sandbox.manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )

    print("==================== CONSTRUCTOR (emit-only) ====================")
    print(f"profile:      {profile_dir}")
    print(f"sandbox_id:   {sandbox_id}")
    print(f"tenant:       {manifest['tenant']}")
    print(f"snapshot:     {manifest['snapshot_date']}")
    print()
    print("Wrote:")
    print(f"  {profile_dir/'docker-compose.yml'}")
    print(f"  {profile_dir/'seeder.sh'}")
    print(f"  {profile_dir/'sandbox.manifest.json'}")
    print()
    print("Counts:")
    for k, v in manifest["counts"].items():
        print(f"  {k:24s} {v}")
    print()
    if emit_only:
        print("Emit-only mode. To bring the sandbox up:")
        print(f"  cd {profile_dir.parent.parent}")
        print(f"  docker compose -f {profile_dir/'docker-compose.yml'} up -d --wait")
        print(f"  bash {profile_dir/'seeder.sh'}")
    else:
        print("Non-emit mode not yet implemented (--emit-only required for now)")
        return 1
    print("=================================================================")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="constructor")
    sub = p.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up", help="Bring sandbox up")
    up.add_argument("profile_dir", type=Path)
    up.add_argument("--emit-only", action="store_true", help="Write files; don't run Docker")
    args = p.parse_args(argv)

    if args.cmd == "up":
        return cmd_up(args.profile_dir, args.emit_only)
    return 1


if __name__ == "__main__":
    sys.exit(main())
