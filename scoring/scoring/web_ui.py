"""
Minimal upload UI for standalone BDD scoring (stdlib only).

    python -m scoring serve
    python -m scoring serve --port 8080 --open
"""
from __future__ import annotations

import html
import shutil
import tempfile
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .multipart import parse_multipart_form
from .report_views import build_simplified
from .standalone import run_from_zips
from .zip_input import ZipInputError


_UPLOAD_FORM = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BDD Scoring</title>
  <style>
    :root { --bg:#f8fafc; --card:#fff; --text:#0f172a; --muted:#64748b; --accent:#2563eb; --border:#e2e8f0; }
    * { box-sizing:border-box; }
    body { font-family:system-ui,sans-serif; background:var(--bg); color:var(--text); margin:0; line-height:1.5; }
    .wrap { max-width:640px; margin:0 auto; padding:32px 20px 48px; }
    h1 { font-size:1.5rem; margin:0 0 8px; }
    .sub { color:var(--muted); margin-bottom:24px; }
    .card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:24px; box-shadow:0 1px 3px rgba(0,0,0,.06); }
    label { display:block; font-weight:600; margin:16px 0 6px; }
    label:first-of-type { margin-top:0; }
    .hint { font-size:0.85rem; color:var(--muted); font-weight:400; }
    input[type=file] { width:100%; padding:8px; border:1px dashed var(--border); border-radius:8px; background:#fafbfc; }
    button { margin-top:20px; width:100%; padding:12px 16px; background:var(--accent); color:#fff; border:0; border-radius:8px; font-size:1rem; font-weight:600; cursor:pointer; }
    button:hover { filter:brightness(1.05); }
    .err { background:#fef2f2; color:#991b1b; border:1px solid #fecaca; padding:12px; border-radius:8px; margin-bottom:16px; }
    ul { padding-left:20px; }
  </style>
</head>
<body>
<div class="wrap">
  <h1>BDD Behaviour Scoring</h1>
  <p class="sub">Upload manual BDD (ground truth), generated BDD (scored), and optionally requirement-agent docs — get JSON and HTML reports.</p>
  {error}
  <div class="card">
    <form method="post" enctype="multipart/form-data" action="/score">
      <label>Manual feature folder (.zip) <span class="hint">— correct reference BDD (always ground truth)</span></label>
      <input type="file" name="golden_zip" accept=".zip,application/zip" required>
      <label>Generated feature folder (.zip) <span class="hint">— agent output under evaluation</span></label>
      <input type="file" name="generated_zip" accept=".zip,application/zip" required>
      <label>Requirement docs (.zip) <span class="hint">— optional requirement-agent output (.json / .md)</span></label>
      <input type="file" name="requirements_zip" accept=".zip,application/zip">
      <label>Match threshold <span class="hint">— 0.45 default</span></label>
      <input type="number" name="threshold" min="0" max="1" step="0.05" value="0.45" style="width:100%;padding:8px;border:1px solid var(--border);border-radius:8px;">
      <button type="submit">Run scoring</button>
    </form>
  </div>
</div>
</body>
</html>
"""


def _result_page(run_id: str, simple: dict, json_name: str, html_name: str) -> str:
    score = simple["overall_score_pct"]
    color = "#15803d" if score >= 75 else ("#ca8a04" if score >= 50 else "#dc2626")
    highlights = "".join(f"<li>{html.escape(line)}</li>" for line in simple.get("highlights", []))
    gaps = "".join(f"<li>{html.escape(line)}</li>" for line in simple.get("top_gaps", []))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Score results</title>
  <style>
    :root {{ --bg:#f8fafc; --text:#0f172a; --muted:#64748b; --border:#e2e8f0; }}
    body {{ font-family:system-ui,sans-serif; background:var(--bg); color:var(--text); margin:0; line-height:1.5; }}
    .wrap {{ max-width:720px; margin:0 auto; padding:32px 20px 48px; }}
    .card {{ background:#fff; border:1px solid var(--border); border-radius:12px; padding:24px; margin-bottom:16px; }}
    .score {{ font-size:2.5rem; font-weight:700; color:{color}; }}
    a.btn {{ display:inline-block; margin:8px 8px 0 0; padding:10px 16px; background:#2563eb; color:#fff; text-decoration:none; border-radius:8px; font-weight:600; }}
    a.btn.secondary {{ background:#e2e8f0; color:#0f172a; }}
    .back {{ color:#2563eb; text-decoration:none; font-size:0.9rem; }}
  </style>
</head>
<body>
<div class="wrap">
  <p><a class="back" href="/">&#8592; Score another pair</a></p>
  <h1>Scoring complete</h1>
  <div class="card">
    <div class="score">{score:.0f}%</div>
    <p>{html.escape(simple["summary"])}</p>
    <p><strong>Verdict:</strong> {html.escape(simple["verdict"])}</p>
    <p>
      <a class="btn" href="/runs/{run_id}/{html_name}" target="_blank">Open HTML report</a>
      <a class="btn secondary" href="/runs/{run_id}/{json_name}" download>Download JSON</a>
    </p>
  </div>
  <div class="card">
    <h2>Highlights</h2>
    <ul>{highlights or "<li>None</li>"}</ul>
    <h2>Top gaps</h2>
    <ul>{gaps or "<li>None</li>"}</ul>
  </div>
</div>
</body>
</html>
"""


class _ScoringServerState:
    def __init__(self, runs_root: Path) -> None:
        self.runs_root = runs_root
        self.runs_root.mkdir(parents=True, exist_ok=True)


def make_handler(state: _ScoringServerState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BDDScoring/1.0"

        def log_message(self, fmt, *args) -> None:
            print(f"[scoring] {self.address_string()} - {fmt % args}")

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                self._send_html(_UPLOAD_FORM.replace("{error}", ""))
                return
            if parsed.path.startswith("/runs/"):
                self._serve_run_file(parsed.path)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/score":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                golden_bytes, generated_bytes, requirements_bytes, threshold = self._parse_upload()
            except ZipInputError as exc:
                block = f'<div class="err">{html.escape(str(exc))}</div>'
                self._send_html(_UPLOAD_FORM.replace("{error}", block), status=400)
                return

            run_id = _new_run_id()
            run_dir = state.runs_root / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            golden_zip = run_dir / "golden.zip"
            generated_zip = run_dir / "generated.zip"
            golden_zip.write_bytes(golden_bytes)
            generated_zip.write_bytes(generated_bytes)
            requirements_zip = None
            if requirements_bytes:
                requirements_zip = run_dir / "requirements.zip"
                requirements_zip.write_bytes(requirements_bytes)

            try:
                result = run_from_zips(
                    golden_zip, generated_zip,
                    requirements_zip=requirements_zip,
                    output_dir=run_dir,
                    threshold=threshold,
                )
            except ZipInputError as exc:
                shutil.rmtree(run_dir, ignore_errors=True)
                block = f'<div class="err">{html.escape(str(exc))}</div>'
                self._send_html(_UPLOAD_FORM.replace("{error}", block), status=400)
                return

            simple = build_simplified(result.report)
            page = _result_page(
                run_id, simple,
                result.json_path.name,
                result.html_path.name,
            )
            self._send_html(page)

        def _parse_upload(self) -> tuple[bytes, bytes, bytes | None, float]:
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                raise ZipInputError("Expected multipart file upload.")
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            try:
                fields = parse_multipart_form(body, content_type)
            except ValueError as exc:
                raise ZipInputError(str(exc)) from exc

            golden_bytes = fields.get("golden_zip")
            generated_bytes = fields.get("generated_zip")
            requirements_bytes = fields.get("requirements_zip")
            if not isinstance(golden_bytes, (bytes, bytearray)) or not golden_bytes:
                raise ZipInputError("Manual feature zip is required.")
            if not isinstance(generated_bytes, (bytes, bytearray)) or not generated_bytes:
                raise ZipInputError("Generated feature zip is required.")
            req_out = None
            if isinstance(requirements_bytes, (bytes, bytearray)) and requirements_bytes:
                req_out = bytes(requirements_bytes)

            threshold_raw = fields.get("threshold", b"0.45")
            if isinstance(threshold_raw, bytes):
                threshold_raw = threshold_raw.decode("utf-8", errors="replace")
            try:
                threshold = float(threshold_raw)
            except (TypeError, ValueError):
                threshold = 0.45
            threshold = max(0.0, min(1.0, threshold))
            return bytes(golden_bytes), bytes(generated_bytes), req_out, threshold

        def _serve_run_file(self, path: str) -> None:
            # /runs/{id}/score_report.html
            parts = path.strip("/").split("/")
            if len(parts) != 3 or parts[0] != "runs":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            _, run_id, filename = parts
            if filename not in ("score_report.json", "score_report.html"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            file_path = state.runs_root / run_id / filename
            if not file_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if filename.endswith(".json"):
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
            else:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(file_path.stat().st_size))
            self.end_headers()
            self.wfile.write(file_path.read_bytes())

        def _send_html(self, body: str, status: int = 200) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def _new_run_id() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


def serve(
    host: str = "127.0.0.1",
    port: int = 8766,
    *,
    open_browser: bool = False,
    runs_dir: Optional[str | Path] = None,
) -> None:
    root = Path(runs_dir) if runs_dir else Path(tempfile.gettempdir()) / "scoring_runs"
    state = _ScoringServerState(root)
    handler = make_handler(state)
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    print(f"BDD scoring UI running at {url}")
    print(f"Reports saved under {root}")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        httpd.shutdown()
