# Why `analyzer/extract.py` was changed

## The bug

Running the analyzer against a **single file** directly (e.g.
`python -m analyzer eval\examples\discount\sut.py --app-id DISCOUNT`, or the
original `python -m analyzer "...Pam Qian_Tic Tac Toe_2016.py" --app-id TICTACTOE`)
produced entities with broken qualified names:

```
Function:..apply_discount     (expected: Function:sut.apply_discount)
Function:..is_eligible        (expected: Function:sut.is_eligible)
Module:.                      (expected: Module:sut)
```

Every function's identity collapsed onto a bare `"."`, instead of using the
file's own name.

## Root cause

In `analyze()` (`extract.py`), three separate call sites computed a file's
relative path like this:

```python
rel = os.path.relpath(path, app_dir)
```

This is correct when `app_dir` is a **directory**: `discover(app_dir)` walks
it, and `path` (a file inside it) relative to `app_dir` gives a real relative
filename, e.g. `sut.py`.

But `discover()` has a special case for when `app_dir` is a **single file**
(`extract.py:145-147`):

```python
if os.path.isfile(root):
    return [root] if root.endswith(exts) else []
```

In that case, `discover()` returns `[app_dir]` — the same string as `app_dir`
itself. So `path == app_dir`, and `os.path.relpath(x, x)` always returns
`"."` (a path is trivially "." relative to itself). That degenerate `"."`
then fed into `_module(rel)`, which produces a module name of `"."`, which
then produces qualified names like `"." + "." + "apply_discount"` →
`"..apply_discount"`.

This is a real, reproducible defect — not a one-off glitch — and it silently
corrupts every entity's identity whenever `analyzer` is pointed at a file
instead of a folder, a supported and documented usage (`__main__.py`'s own
docstring and the CLI help text both allow a single file as `app_dir`).

## Why this matters

Entity identity (`canon(kind, qualname)`) is the thing ingestion, the
knowledge base, `requirement_agent`, and the graph all key off of. A
collapsed `"."` identity means:

- Two different single-file analyses under the same `app_id` would produce
  **colliding** entity IDs (both would be `Function:.apply_discount`-style,
  regardless of which real file each came from).
- Anything downstream that groups or displays entities by module (e.g.
  `requirement_agent`'s `inventory()`, used to decide what to write a spec
  for) shows a meaningless `"."` instead of the actual source file.

## The fix

Added one line, computed once per `analyze()` call:

```python
rel_base = os.path.dirname(app_dir) if os.path.isfile(app_dir) else app_dir
```

Then changed all three `os.path.relpath(path, app_dir)` call sites to use
`rel_base` instead of `app_dir`. When `app_dir` is a file, this uses the
file's **parent directory** as the base for the relative-path computation —
so `rel` becomes the file's own basename (`sut.py`) instead of `"."`. When
`app_dir` is already a directory (the common case), `rel_base == app_dir`,
so behavior is completely unchanged.

## Verification

- `analyzer`'s own test suite: 139 passed, 4 skipped (pre-existing, unrelated
  to this change), 0 failed, both before and after — no regression.
- Re-ran `analyzer` directly on `eval\examples\discount\sut.py` after the fix:
  entity names changed from `Function:..apply_discount` /
  `Function:..is_eligible` / `Module:.` to the correct
  `Function:sut.apply_discount` / `Function:sut.is_eligible` / `Module:sut`.
- Confirmed via `requirement_agent`'s `AnalyzerFacts.from_file(...).inventory()`
  loading the real quad file produced by both the buggy and fixed versions,
  showing the exact before/after difference on real data (not a synthetic
  test case).

## Why the fix was scoped this way (not something broader)

The three call sites already shared the exact same pattern
(`os.path.relpath(path, app_dir)`), so a single shared `rel_base` variable
fixes all three consistently instead of patching each site with its own
one-off conditional. `_module()` already defensively handles both `/` and
`os.sep` in its input, so no change was needed there — the bug was purely in
what value got passed in, not in how that value was later parsed.
