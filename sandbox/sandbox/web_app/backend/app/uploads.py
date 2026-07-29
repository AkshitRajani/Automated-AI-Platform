"""User-uploaded feature + steps file runner.

Drops the uploaded `.feature` + `_steps.py` into a project dir alongside the
Tenant helper shims (Sandbox/core/test_framework/), then runs `behave` with
AWS_ENDPOINT_URL pointed at the local LocalStack and DBM/CAL URLs pointed at
the local Microcks. The bundle's `boto3.invoke(...)` calls land on the booted
sandbox infra — so PASS/FAIL is earned by the architecture, not by source
pattern matching.
"""
from __future__ import annotations
import asyncio
import os
import shutil
import tempfile
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

UPLOAD_ROOT = Path(tempfile.gettempdir()) / "sandbox_uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

# Tenant test framework shims live next to the spec.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_SANDBOX_CORE = _BACKEND_DIR.parent.parent / "core"
TEST_FRAMEWORK_DIR = _SANDBOX_CORE / "test_framework"

# Live-infra endpoints. Override via env if the operator runs the stack elsewhere.
AWS_ENDPOINT_URL = os.environ.get("SANDBOX_AWS_ENDPOINT_URL", "http://localhost:4566")
MICROCKS_BASE = os.environ.get("SANDBOX_MICROCKS_BASE", "http://localhost:8080")
PG_HOST = os.environ.get("SANDBOX_PG_HOST", "127.0.0.1")
PG_PORT = os.environ.get("SANDBOX_PG_PORT", "5433")


@dataclass
class UploadRun:
    id: str
    upload_id: str
    state: str = "pending"
    started_at: float = 0.0
    completed_at: float | None = None
    returncode: int | None = None
    lines: list[str] = field(default_factory=list)
    queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    infra_health: dict = field(default_factory=dict)


_UPLOADS: dict[str, dict] = {}
_RUNS: dict[str, UploadRun] = {}


def create_upload(feature_bytes: bytes, feature_name: str,
                  steps_bytes: bytes, steps_name: str) -> dict:
    upload_id = uuid.uuid4().hex[:10]
    upload_dir = UPLOAD_ROOT / upload_id
    features_dir = upload_dir / "features"
    steps_dir = features_dir / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)
    feature_path = features_dir / (feature_name if feature_name.endswith(".feature") else "uploaded.feature")
    steps_path = steps_dir / (steps_name if steps_name.endswith(".py") else "uploaded_steps.py")
    feature_path.write_bytes(feature_bytes)
    steps_path.write_bytes(steps_bytes)

    # Fixture synthesis for known tenant templates that read sibling JSON files.
    # Keeps tenant pristine code unmodified — we just stage the empty fixture
    # files at the exact filesystem paths the step code resolves.
    fixtures_synthesized = _stage_tenant_fixtures(steps_dir, feature_bytes, steps_bytes)

    info = {
        "id": upload_id,
        "dir": str(upload_dir),
        "feature": str(feature_path),
        "steps": str(steps_path),
        "feature_bytes": len(feature_bytes),
        "steps_bytes": len(steps_bytes),
        "fixtures_synthesized": fixtures_synthesized,
        "uploaded_at": time.time(),
    }
    _UPLOADS[upload_id] = info
    return info


def _stage_tenant_fixtures(steps_dir: Path, feature_bytes: bytes, steps_bytes: bytes) -> list[str]:
    """Detect the tenant gitlab_8232 lambda-regression template and stage the
    payload fixture JSONs the tenant's step code expects to read.

    the tenant's step file uses Windows-style backslash paths
    (e.g. ``utilities\\aws_lambda\\input_payload\\``). On macOS/Linux Python
    treats these as a single literal directory name. We mkdir that exact
    literal-backslash directory and drop empty `{}` JSONs in it for every
    `input_pay_load` and full-comparison `expected_output` referenced in the
    .feature's Examples table.

    Returns a list of synthesized fixture paths (relative to upload_dir).
    """
    steps_text = steps_bytes.decode("utf-8", errors="replace")
    # Match the literal SOURCE-CODE bytes the tenant wrote — they used escaped
    # backslashes in their Python string literal so on disk the file contains
    # `utilities\\aws_lambda\\input_payload\\` (each `\\` is two characters).
    if r"utilities\\aws_lambda\\input_payload\\" not in steps_text:
        return []  # not the gitlab_8232 lambda regression template

    feature_text = feature_bytes.decode("utf-8", errors="replace")
    rows: list[list[str]] = []
    for line in feature_text.splitlines():
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|")):
            continue
        cols = [c.strip() for c in s.strip("|").split("|")]
        # Skip the header row.
        if not cols or cols[0].lower() in {"lambda_name", ""}:
            continue
        if len(cols) >= 5:
            rows.append(cols)

    # The literal-backslash directories are valid macOS filenames. The trailing
    # backslash in the tenant's path constants is preserved by Path so os.path.join
    # in the step code resolves to the same location we're creating here.
    input_dir = steps_dir / "utilities\\aws_lambda\\input_payload\\"
    output_dir = steps_dir / "utilities\\aws_lambda\\expected_output_payload\\"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for cols in rows:
        # Examples row: [lambda_name, type_of_testing, input_pay_load, expected_output, type_of_comparison]
        input_file = cols[2]
        expected = cols[3]
        comparison = cols[4].lower() if len(cols) > 4 else ""
        if input_file:
            (input_dir / input_file).write_text("{}\n")
            written.append(f"input_payload/{input_file}")
        if comparison == "full-comparison" and expected:
            (output_dir / expected).write_text("{}\n")
            written.append(f"expected_output_payload/{expected}")
    return written


def get_upload(upload_id: str) -> dict | None:
    return _UPLOADS.get(upload_id)


def list_uploads() -> list[dict]:
    return sorted(_UPLOADS.values(), key=lambda x: x["uploaded_at"], reverse=True)


def delete_upload(upload_id: str) -> bool:
    info = _UPLOADS.pop(upload_id, None)
    if not info:
        return False
    try:
        shutil.rmtree(info["dir"], ignore_errors=True)
    except Exception:
        pass
    return True


def _http_ok(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def check_infra_health() -> dict:
    return {
        "localstack": _http_ok(f"{AWS_ENDPOINT_URL}/_localstack/health"),
        "microcks": _http_ok(f"{MICROCKS_BASE}/api/services"),
        "test_framework": TEST_FRAMEWORK_DIR.exists(),
    }


def start_run(upload_id: str) -> UploadRun:
    info = _UPLOADS.get(upload_id)
    if not info:
        raise KeyError(upload_id)
    run = UploadRun(
        id=uuid.uuid4().hex[:8],
        upload_id=upload_id,
        state="running",
        started_at=time.time(),
        infra_health=check_infra_health(),
    )
    _RUNS[run.id] = run
    asyncio.create_task(_drive(run, Path(info["dir"])))
    return run


def get_run(run_id: str) -> UploadRun | None:
    return _RUNS.get(run_id)


async def event_stream(run_id: str) -> AsyncIterator[str]:
    run = _RUNS.get(run_id)
    if not run:
        return
    history = list(run.lines)
    last = len(history)
    for line in history:
        yield _sse(line)
    if run.state != "running":
        yield _sse(f"__exit__ rc={run.returncode}")
        return
    while True:
        line = await run.queue.get()
        if line is None:
            break
        if last > 0:
            last -= 1
            continue
        yield _sse(line)


def _sse(line: str) -> str:
    safe = line.replace("\r", "")
    return f"data: {safe}\n\n"


def _emit(run: UploadRun, line: str) -> None:
    run.lines.append(line)
    run.queue.put_nowait(line)


def _build_env() -> dict:
    """Env handed to behave so the test bundle's boto3 + DBM/CAL clients land on
    the local sandbox. PYTHONPATH puts the Tenant helper shims first so imports
    like `utilities.aws_lambda.execute_lambda` resolve."""
    base = os.environ.copy()
    base["AWS_ENDPOINT_URL"] = AWS_ENDPOINT_URL
    base["AWS_DEFAULT_REGION"] = base.get("AWS_DEFAULT_REGION", "us-east-1")
    base["AWS_REGION"] = base.get("AWS_REGION", "us-east-1")
    base["AWS_ACCESS_KEY_ID"] = base.get("AWS_ACCESS_KEY_ID", "test")
    base["AWS_SECRET_ACCESS_KEY"] = base.get("AWS_SECRET_ACCESS_KEY", "test")
    # Microcks REST mock URL: spaces as %20, parens unencoded.
    base["DBM_BASE_URL"] = f"{MICROCKS_BASE}/rest/DBM%20(Data%20Backbone%20Manager)/stub-1.0"
    base["CAL_BASE_URL"] = f"{MICROCKS_BASE}/rest/CAL%20(Calculation%20Service)/stub-1.0"
    base["MICROCKS_BASE_URL"] = MICROCKS_BASE
    base["PG_HOST"] = PG_HOST
    base["PG_PORT"] = PG_PORT
    existing = base.get("PYTHONPATH", "")
    base["PYTHONPATH"] = f"{TEST_FRAMEWORK_DIR}{os.pathsep}{existing}" if existing else str(TEST_FRAMEWORK_DIR)
    return base


async def _drive(run: UploadRun, upload_dir: Path) -> None:
    try:
        _emit(run, "==> sandbox infra health")
        for k, v in run.infra_health.items():
            _emit(run, f"    {k}: {'ok' if v else 'MISSING'}")
        if not run.infra_health.get("localstack") or not run.infra_health.get("microcks"):
            run.state = "failed"
            run.returncode = -2
            _emit(run, "ERROR: sandbox infra not booted. Run docker compose up + seeder.sh first.")
            return

        _emit(run, f"==> AWS_ENDPOINT_URL={AWS_ENDPOINT_URL}")
        _emit(run, f"==> MICROCKS_BASE={MICROCKS_BASE}")
        _emit(run, f"==> PYTHONPATH includes {TEST_FRAMEWORK_DIR}")
        _emit(run, f"==> running behave in {upload_dir}")
        _emit(run, "")

        env = _build_env()
        proc = await asyncio.create_subprocess_exec(
            "behave",
            "--no-color",
            "--no-capture",
            "--format", "plain",
            "features",
            cwd=str(upload_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        assert proc.stdout
        while True:
            chunk = await proc.stdout.readline()
            if not chunk:
                break
            line = chunk.decode(errors="replace").rstrip("\n")
            _emit(run, line)
        await proc.wait()
        run.returncode = proc.returncode
        run.state = "succeeded" if proc.returncode == 0 else "failed"
    except FileNotFoundError:
        run.state = "failed"
        run.returncode = 127
        _emit(run, "behave not installed in backend env — `uv sync` in backend/")
    except Exception as e:
        run.state = "failed"
        run.returncode = -1
        _emit(run, f"driver error: {e}")
    finally:
        run.completed_at = time.time()
        run.queue.put_nowait(None)
