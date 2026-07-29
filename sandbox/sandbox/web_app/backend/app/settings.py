from pathlib import Path
import os

BACKEND_DIR = Path(__file__).resolve().parent.parent
CORE_DIR = Path(os.environ.get("SANDBOX_CORE_DIR", BACKEND_DIR.parent.parent / "core")).resolve()
DEFAULT_PROFILE = os.environ.get("SANDBOX_PROFILE", "F")


def profile_dir(profile: str = DEFAULT_PROFILE) -> Path:
    return CORE_DIR / "profiles" / profile
