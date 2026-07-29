"""Run a Behave bundle in a FRESH process for one executable-gate check.

``BehaveEnv`` invokes this as a subprocess so every run — the baseline, each
gate-6 mutant, and each gate-7 repeat — imports the SUT fresh from disk. That is
the whole point: a single long-lived interpreter caches the SUT module on the
first run (``sys.modules``), after which a mutated file on disk is never re-read,
so mutation testing silently verifies the *original* code. A fresh process per
run is how real mutation tools (mutmut, cosmic-ray) avoid exactly this.

Pure stdlib + Behave (already a dependency).

argv: <features_dir> <sut_path> <out_json>
Writes {"passed", "undefined", "covered": [lines], "error"} to <out_json>.
"""
import json
import os
import sys


def main() -> None:
    features, sut_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

    # workspace (the parent of features/) on the path, so an in-workspace package
    # resolves naturally; harmless if the test imports the SUT by file path instead.
    workspace_root = os.path.dirname(os.path.abspath(features))
    if workspace_root not in sys.path:
        sys.path.insert(0, workspace_root)

    sut_real = os.path.realpath(sut_path)
    sut_base = os.path.basename(sut_path)
    covered = set()

    def tracer(frame, event, arg):
        co = frame.f_code.co_filename
        if co.endswith(sut_base) and os.path.realpath(co) == sut_real:
            if event == "line":
                covered.add(frame.f_lineno)
            return tracer
        return None

    result = {"passed": False, "undefined": 0, "covered": [], "error": None}
    try:
        from behave.configuration import Configuration
        from behave.runner import Runner

        # load_config=False → ignore any behave.ini/setup.cfg on the host.
        # 'null' formatter emits nothing (we only need pass/fail + coverage).
        config = Configuration(
            command_args=[features, "--no-color", "--format", "null",
                          "--no-logcapture", "--no-capture", "--no-summary"],
            load_config=False,
        )
        if not getattr(config, "format", None):     # defensive: no config files loaded
            config.format = ["null"]
            config.outputs = config.outputs or []
        runner = Runner(config)
        sys.settrace(tracer)
        try:
            failed = runner.run()                   # True if any scenario failed
        finally:
            sys.settrace(None)
        undefined = list(getattr(runner, "undefined_steps", []))
        result["passed"] = (not failed) and (not undefined)
        result["undefined"] = len(undefined)
        result["covered"] = sorted(covered)
        if undefined and not failed:
            result["error"] = f"{len(undefined)} undefined step(s)"
    except Exception as exc:                          # could not run cleanly
        sys.settrace(None)
        result["error"] = f"{type(exc).__name__}: {exc}"

    with open(out_path, "w") as fh:
        json.dump(result, fh)


if __name__ == "__main__":
    main()
