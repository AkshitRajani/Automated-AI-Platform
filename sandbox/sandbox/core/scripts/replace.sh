#!/usr/bin/env bash
#
# Drop-in helper: when the tenant ships a real artifact, this moves it into delivered/
# and updates the category manifest. Idempotent. Reversible via --rollback.
#
# Usage:
#   scripts/replace.sh <category> <filename> <source_path>
#   scripts/replace.sh --rollback <category> <filename>
#
# Examples:
#   scripts/replace.sh contracts dbm.openapi.yaml ~/Downloads/tenant-dbm-real.yaml
#   scripts/replace.sh --rollback contracts dbm.openapi.yaml

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ATTACH="$ROOT/profiles/F/attachments"

if [[ "${1:-}" == "--rollback" ]]; then
    category="$2"
    filename="$3"
    target="$ATTACH/$category/delivered/$filename"
    if [[ -f "$target" ]]; then
        rm "$target"
        echo "rolled back: $target removed (generated/ stub will be used)"
    else
        echo "nothing to roll back: $target does not exist"
    fi
    exit 0
fi

category="$1"
filename="$2"
source_path="$3"

if [[ ! -f "$source_path" ]]; then
    echo "error: source file not found: $source_path" >&2
    exit 1
fi

dst_dir="$ATTACH/$category/delivered"
mkdir -p "$dst_dir"
dst="$dst_dir/$filename"

if [[ -f "$dst" ]]; then
    echo "warning: $dst already exists; overwriting"
fi

cp "$source_path" "$dst"
sha256=$(shasum -a 256 "$dst" | awk '{print $1}')
size=$(wc -c < "$dst" | tr -d ' ')

echo "delivered: $dst"
echo "  sha256:  $sha256"
echo "  size:    $size bytes"
echo
echo "If a generated/ stub exists, it remains as fallback. Constructor now picks delivered/."
echo "Diff against stub:"
gen="$ATTACH/$category/generated/$filename"
if [[ -f "$gen" ]]; then
    diff -u "$gen" "$dst" | head -40 || true
else
    echo "  (no generated/ stub for this artifact)"
fi
