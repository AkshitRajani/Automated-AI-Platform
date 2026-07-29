# Verification — one-line commands that tell you what's wrong

Copy this folder anywhere. It never writes to the database — every command is
read-only and safe to run in any environment, any number of times.

## Setup (once)

```bash
pip install psycopg2-binary pyyaml
export PG_HOST=<host> PG_PORT=<port> PG_DATABASE=<db> PG_USER=<user> PG_PASSWORD=<password>
```
(Same values ingestion uses. Passwords are never printed or written to reports.)

## The one command that does everything

```bash
python verify_all.py --app <app_id> --quads <quad_file.yaml> --specs <spec_workspace>
```

Every run writes a report into `verification_report/`. **When you report an
issue, zip that folder and send it — it tells us exactly where things broke.**

Each run writes **two files** with the same name: a `.json` (the raw numbers) and a
plain-English `.md` (the same numbers, each with a one-line explanation of what it
counts — no good/bad judgments). Open the `.md` to read the results without us.

## Individual commands

| You want to know | Run | Needs DB? |
|---|---|---|
| Did the analyzer produce a healthy file, and is it READY TO INGEST or should you WAIT? (entities, facts, journeys, blocked state, human answers, skips, `--against <previous>` to see what changed) | `python check_quadfile.py <quad_file.yaml> [--against <previous.yaml>]` — exit 0 = ingest, exit 1 = wait | no |
| Did the spec agent cover everything? (all docs present, 9 sections, every journey covered) | `python check_specs.py <spec_workspace> --quads <quad_file>` | no |
| Did ingestion load completely? (row counts, duplicates, spec join, leftovers) | `python check_kb.py --app <app_id>` | yes |
| What's in the graph? (nodes by type, every relationship kind + counts, dead ends) | `python check_graph.py --app <app_id>` | yes |
| How many journeys, and the longest chain printed hop by hop | `python check_journeys.py --app <app_id>` | yes |

## Reading the output

Every line starts with a verdict:
- `[PASS]` — healthy.
- `[WARN]` — works, but something needs attention; the line says what to do.
- `[FAIL]` — broken; the line says the most likely cause and what to send us.
- `[INFO]` — a number for context, no judgment.

## When something looks wrong

1. Run `verify_all.py` with all three inputs.
2. Zip `verification_report/` and send it, with one sentence: which step you ran
   last (analyzer / names / spec agent / journey review / ingestion / tests).
That is enough for us to locate the problem without access to your environment.
