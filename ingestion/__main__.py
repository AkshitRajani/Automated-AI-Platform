"""
Ingestion Pipeline — Entry Point

Two modes:

  Quad ingestion (default):
      python -m ingestion
      Reads QUAD_FILES_SOURCE from .env and processes every quad .yaml in that folder.

  Requirements ingestion (the requirement agent's output):
      python -m ingestion --requirements <dir> --app-id <APP_ID> [--code-version <v>]
      Loads the per-unit requirement docs into app_requirements. Run after the app's
      quads are ingested. Decoupled from quad discovery.
"""
import argparse
import os
import logging

from ingestion.pipeline import ingest_requirements, run_pipeline
from ingestion.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


def main(argv=None):
    # Ensure ingestion/.env is loaded before reading QUAD_FILES_SOURCE.
    load_config()

    p = argparse.ArgumentParser(prog="ingestion", description=__doc__)
    p.add_argument("--requirements", metavar="DIR", default=None,
                   help="requirement-agent output dir to ingest into app_requirements")
    p.add_argument("--app-id", default=None, help="app id (required with --requirements)")
    p.add_argument("--code-version", default=None,
                   help="optional code version to stamp on the requirement rows")
    args = p.parse_args(argv)

    if args.requirements:
        if not args.app_id:
            p.error("--app-id is required with --requirements")
        report = ingest_requirements(args.app_id, args.requirements,
                                     code_version=args.code_version)
        print("\n=== Requirements Ingestion Complete ===")
        print(f"App: {report['app_id']}")
        print(f"Docs found:   {report['docs_found']}")
        print(f"Units written: {report['units_written']}")
        return

    # default: quad ingestion
    source = os.environ.get("QUAD_FILES_SOURCE", "")
    if not source:
        print("ERROR: QUAD_FILES_SOURCE not set in .env")
        print("Set it to a local folder or S3 URI, e.g.: c:\\data\\quads  or  s3://bucket/quad_files/")
        return

    print(f"Source: {source}")
    report = run_pipeline(source)

    print("\n=== Pipeline Complete ===")
    print(f"Files processed: {report['files_processed']}")
    print(f"Succeeded: {report['succeeded']}")
    print(f"Failed: {report['failed']}")
    if report['failed'] > 0:
        print(f"Failed files: {report['failed_files']}")


if __name__ == "__main__":
    main()
