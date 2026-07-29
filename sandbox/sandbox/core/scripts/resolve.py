"""
Resolver: maps a logical artifact name to a physical path, preferring delivered/ over generated/.

Used by the constructor to look up DDLs, OpenAPI specs, lambda zips, etc. without
caring whether the active version is a stub or a tenant-shipped real file.

Usage:
    python3 scripts/resolve.py <category> <filename>
    e.g.   python3 scripts/resolve.py contracts dbm.openapi.yaml
           python3 scripts/resolve.py lambdas hlx-aap_sandbox-controller-lambda.zip
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ATTACH = ROOT / "profiles" / "F" / "attachments"


def resolve(category: str, filename: str) -> Path:
    delivered = ATTACH / category / "delivered" / filename
    generated = ATTACH / category / "generated" / filename
    if delivered.exists():
        return delivered
    if generated.exists():
        return generated
    raise FileNotFoundError(
        f"{filename} not found in {category}/delivered or {category}/generated"
    )


def is_delivered(category: str, filename: str) -> bool:
    return (ATTACH / category / "delivered" / filename).exists()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    path = resolve(sys.argv[1], sys.argv[2])
    print(path)
    print(f"  source: {'delivered' if is_delivered(sys.argv[1], sys.argv[2]) else 'generated'}", file=sys.stderr)
