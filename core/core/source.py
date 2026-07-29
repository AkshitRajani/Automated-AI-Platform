"""
Resolve an onboarding source to a local directory of code.

The source is **configurable** — you hand in whatever you have and the core turns
it into a folder the parser can read:

  * a local directory        → used as-is
  * a local ``.zip``         → extracted to a temp dir
  * an ``s3://bucket/key``   → downloaded (boto3, creds from env/config), and
                               extracted if it is a zip

boto3 is only imported on the S3 path, so local runs need no AWS at all. Returns a
``ResolvedSource`` whose ``.cleanup()`` removes any temp dir it created.
"""
from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Optional


@dataclass
class ResolvedSource:
    root: str                       # the local directory the parser will read
    _tmp: Optional[str] = None      # a temp dir to remove, if we created one

    def cleanup(self) -> None:
        if self._tmp and os.path.isdir(self._tmp):
            import shutil
            shutil.rmtree(self._tmp, ignore_errors=True)


def _unzip(zip_path: str) -> str:
    dest = tempfile.mkdtemp(prefix="core_src_")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    # if the zip contained a single top-level folder, descend into it
    entries = [e for e in os.listdir(dest) if not e.startswith("__MACOSX")]
    if len(entries) == 1 and os.path.isdir(os.path.join(dest, entries[0])):
        return os.path.join(dest, entries[0])
    return dest


def _fetch_s3(uri: str, region: str) -> str:
    import boto3  # imported only on the S3 path
    without = uri[len("s3://"):]
    bucket, _, key = without.partition("/")
    s3 = boto3.client("s3", region_name=region)
    tmp = tempfile.mkdtemp(prefix="core_s3_")
    local = os.path.join(tmp, os.path.basename(key) or "download")
    s3.download_file(bucket, key, local)
    return local


def resolve_source(src: str, region: str = "us-east-1", trace=None) -> ResolvedSource:
    """Turn ``src`` into a local code directory. ``trace`` is an optional span to
    log into."""
    def _log(msg, **kw):
        if trace is not None:
            trace.log(msg, **kw)

    if src.startswith("s3://"):
        _log("downloading from S3", uri=src)
        local = _fetch_s3(src, region)
        if local.endswith(".zip"):
            root = _unzip(local)
            return ResolvedSource(root=root, _tmp=os.path.dirname(local))
        return ResolvedSource(root=local, _tmp=os.path.dirname(local))

    if src.endswith(".zip"):
        _log("extracting zip", path=src)
        root = _unzip(src)
        return ResolvedSource(root=root, _tmp=root)

    if os.path.isdir(src):
        return ResolvedSource(root=src)

    raise FileNotFoundError(
        f"onboarding source not found / unsupported: {src!r} "
        f"(expected a directory, a .zip, or an s3:// URI)"
    )
