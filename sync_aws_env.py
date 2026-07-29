"""Copy AWS/Bedrock keys from scoring/.env into ingestion + spec_agent .env (no overwrite of existing keys)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "scoring" / "scoring" / ".env"
TARGETS = [ROOT / "ingestion" / ".env", ROOT / "spec_agent" / ".env"]
KEYS = (
    "AWS_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "BEDROCK_MODEL_ARN",
)


def parse_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        data[k.strip()] = v.strip()
    return data


def upsert(path: Path, updates: dict[str, str]) -> list[str]:
    changed: list[str] = []
    existing = parse_env(path) if path.is_file() else {}
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    keys_present = set()
    out: list[str] = []
    for line in lines:
        raw = line.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k = raw.split("=", 1)[0].strip()
            keys_present.add(k)
            if k in updates and (
                not existing.get(k)
                or existing.get(k, "").startswith("your-")
                or "your-account" in existing.get(k, "")
                or existing.get(k) in ("", "your-password", "your-postgres-host")
            ):
                out.append(f"{k}={updates[k]}")
                changed.append(k)
                continue
        out.append(line)
    for k, v in updates.items():
        if k not in keys_present and v:
            out.append(f"{k}={v}")
            changed.append(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return changed


def main() -> None:
    src = parse_env(SRC)
    updates = {k: src[k] for k in KEYS if src.get(k)}
    if not updates:
        print("No AWS/Bedrock keys found in scoring/scoring/.env — skip sync")
        return
    for target in TARGETS:
        if not target.is_file():
            print(f"skip missing {target}")
            continue
        changed = upsert(target, updates)
        print(f"{target.name}: synced {len(changed)} key(s)")


if __name__ == "__main__":
    main()
