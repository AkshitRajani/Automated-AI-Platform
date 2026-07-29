from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, PlainTextResponse, FileResponse
from pydantic import BaseModel
import asyncio
import json

from .settings import CORE_DIR, DEFAULT_PROFILE, profile_dir
from .topology import build_topology, read_spec
from . import coverage as coverage_module
from . import uploads as uploads_module

app = FastAPI(title="Sandbox Web Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"ok": True, "core_dir": str(CORE_DIR), "default_profile": DEFAULT_PROFILE}


@app.get("/api/profiles")
def list_profiles():
    profiles_dir = CORE_DIR / "profiles"
    if not profiles_dir.exists():
        return {"profiles": []}
    return {"profiles": sorted(p.name for p in profiles_dir.iterdir() if p.is_dir())}


@app.get("/api/profile")
def get_profile(name: str = DEFAULT_PROFILE):
    manifest_path = profile_dir(name) / "sandbox.manifest.json"
    if not manifest_path.exists():
        raise HTTPException(404, f"profile '{name}' not found")
    with open(manifest_path) as f:
        return json.load(f)


@app.get("/api/topology")
def get_topology(profile: str = DEFAULT_PROFILE):
    try:
        return build_topology(profile)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@app.get("/api/spec", response_class=PlainTextResponse)
def get_spec(profile: str = DEFAULT_PROFILE):
    spec_path = profile_dir(profile) / "spec.yaml"
    if not spec_path.exists():
        raise HTTPException(404, f"spec for '{profile}' not found")
    return spec_path.read_text()


class SpecBody(BaseModel):
    profile: str = DEFAULT_PROFILE
    text: str


@app.put("/api/spec")
def put_spec(body: SpecBody):
    import yaml as _yaml
    try:
        _yaml.safe_load(body.text)
    except _yaml.YAMLError as e:
        raise HTTPException(400, f"invalid YAML: {e}")
    spec_path = profile_dir(body.profile) / "spec.yaml"
    if not spec_path.parent.exists():
        raise HTTPException(404, f"profile '{body.profile}' not found")
    spec_path.write_text(body.text)
    return {"ok": True, "bytes": len(body.text)}


class RebuildBody(BaseModel):
    profile: str = DEFAULT_PROFILE


@app.post("/api/rebuild")
async def rebuild(body: RebuildBody):
    pdir = profile_dir(body.profile)
    if not (pdir / "spec.yaml").exists():
        raise HTTPException(404, f"profile '{body.profile}' not found")
    proc = await asyncio.create_subprocess_exec(
        "python3", "-m", "constructor", "up", str(pdir), "--emit-only",
        cwd=str(CORE_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
    }


@app.get("/api/coverage")
def get_coverage(profile: str = DEFAULT_PROFILE):
    return coverage_module.build_coverage(profile)


_DOC_ALLOWLIST_TEXT = {"DATA_FLOW.md", "WIRING.md", "DESIGN_DIAGRAM.md"}
_DOC_ALLOWLIST_BINARY = {"SANDBOX_DESIGN.pptx"}


@app.get("/api/docs")
def list_docs():
    items = []
    for name in sorted(_DOC_ALLOWLIST_TEXT):
        p = CORE_DIR / name
        if p.exists():
            items.append({"name": name, "bytes": p.stat().st_size})
    for name in sorted(_DOC_ALLOWLIST_BINARY):
        p = CORE_DIR / name
        if p.exists():
            items.append({"name": name, "bytes": p.stat().st_size, "binary": True})
    return {"docs": items}


@app.post("/api/uploads")
async def upload_test_files(
    feature_file: UploadFile = File(...),
    steps_file: UploadFile = File(...),
):
    feat = await feature_file.read()
    steps = await steps_file.read()
    if not feat or not steps:
        raise HTTPException(400, "both feature and steps files are required")
    info = uploads_module.create_upload(
        feature_bytes=feat,
        feature_name=feature_file.filename or "uploaded.feature",
        steps_bytes=steps,
        steps_name=steps_file.filename or "uploaded_steps.py",
    )
    return info


@app.get("/api/uploads")
def list_uploads():
    return {"uploads": uploads_module.list_uploads()}


@app.delete("/api/uploads/{upload_id}")
def delete_upload(upload_id: str):
    if not uploads_module.delete_upload(upload_id):
        raise HTTPException(404, "upload not found")
    return {"ok": True}


@app.get("/api/sandbox/health")
def sandbox_health():
    return uploads_module.check_infra_health()


@app.post("/api/uploads/{upload_id}/run")
async def start_upload_run(upload_id: str):
    try:
        run = uploads_module.start_run(upload_id)
    except KeyError:
        raise HTTPException(404, "upload not found")
    return {
        "run_id": run.id,
        "upload_id": run.upload_id,
        "state": run.state,
        "infra_health": run.infra_health,
    }


@app.get("/api/uploads/runs/{run_id}")
def get_upload_run(run_id: str):
    run = uploads_module.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return {
        "id": run.id,
        "upload_id": run.upload_id,
        "state": run.state,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "returncode": run.returncode,
        "lines": run.lines,
        "infra_health": run.infra_health,
    }


@app.get("/api/uploads/runs/{run_id}/events")
async def stream_upload_run(run_id: str):
    if not uploads_module.get_run(run_id):
        raise HTTPException(404, "run not found")
    return StreamingResponse(
        uploads_module.event_stream(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/docs/{name}")
def get_doc(name: str):
    p = CORE_DIR / name
    if name in _DOC_ALLOWLIST_TEXT:
        if not p.exists():
            raise HTTPException(404, f"doc '{name}' not found")
        return PlainTextResponse(p.read_text())
    if name in _DOC_ALLOWLIST_BINARY:
        if not p.exists():
            raise HTTPException(404, f"doc '{name}' not found")
        return FileResponse(p, filename=name)
    raise HTTPException(404, f"doc '{name}' not allowed")


@app.get("/api/contract")
def get_contract(name: str, profile: str = DEFAULT_PROFILE):
    try:
        spec = read_spec(profile)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    target = name.lower()
    for c in spec.get("behavioral_contracts", []) or []:
        if (c.get("name") or "").lower() == target:
            return c
    raise HTTPException(404, f"contract '{name}' not found")


