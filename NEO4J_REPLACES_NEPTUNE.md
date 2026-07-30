# Neptune → Neo4j Community Edition — replacement, confirmed working

**Why:** Amazon Neptune is a paid, continuously-billed AWS service (instance-hours +
storage + I/O, no meaningful free tier). Neo4j Community Edition is free,
open-source, and runs locally in Docker — no AWS account needed. Neptune's
Gremlin support is itself built on the Apache TinkerPop standard, but Neo4j
uses Cypher instead, so query strings needed rewriting (not just a driver swap).

**Policy followed:** every place Neptune code got replaced, the original was
**commented out, not deleted** — see `neptune_writer.py` (fully intact,
untouched) and the commented blocks inside `pipeline.py`,
`coding_agent\kb\graph.py`, `coding_agent\config.py`, `coding_agent\_env.py`,
`ingestion\config.py`, and `coding_agent\tests\test_graph.py`.

---

## What changed

| File | Change |
|---|---|
| `docker-compose.local.yml` | Added `neo4j` service (Neo4j 5 Community, ports 7474/7687) |
| `ingestion\requirements.txt`, `coding_agent\requirements.txt` | Added `neo4j>=5.0` driver |
| `ingestion\graph\neo4j_writer.py` | **New file.** `Neo4jWriter` — same public interface as `NeptuneWriter` (`delete_app`, `write_nodes`, `write_edges`), writes via Cypher `MERGE` over the Bolt protocol instead of CSV+S3+bulk-load |
| `ingestion\config.py`, `ingestion\pipeline.py` | Added `"neo4j"` config block; commented out the `NeptuneWriter(...)` instantiation, wired in `Neo4jWriter(...)` instead |
| `coding_agent\kb\graph.py` | Added `build_cypher()` and `_Neo4jExecutor` (replacing `build_gremlin()`/`_NeptuneExecutor`, both commented out, not deleted); `GraphClient.from_env()` now calls `neo4j_settings()` |
| `coding_agent\config.py`, `coding_agent\_env.py` | Added `neo4j_settings()` / `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD` reading |
| `coding_agent\tests\test_graph.py` | Gremlin-builder tests commented out; added `test_cypher_builder_shape`/`test_cypher_direction_in` |

---

## Regression check — no existing tests broken

```
& $env:AAP_PYTHON -m pytest ingestion\ -q
35 passed in 0.60s

& $env:AAP_PYTHON -m pytest coding_agent\tests -q
54 passed in 1.69s
```

---

## Real, live proof it works — ran against the bundled `sample_app` fixture

```powershell
$env:NEO4J_PASSWORD="localgraphpw"
& $env:AAP_PYTHON -m analyzer analyzer\tests\fixtures\sample_app --app-id NEO4JTEST --out .platform_runs\quads\NEO4JTEST.yaml --stats
$env:QUAD_FILES_SOURCE = ".platform_runs\quads"
& $env:AAP_PYTHON -m ingestion
```
```
wrote .platform_runs\quads\NEO4JTEST.yaml: 10 entities, 22 quads
...
Processing: .platform_runs\quads\NEO4JTEST.yaml (fallback app_id: NEO4JTEST)
  Parsed: 10 entities, 22 quads, 0 quarantined
  Components inferred: 1
  Postgres: done
  Neo4j: wrote 22 edge(s) for NEO4JTEST
  Neo4j: done

=== Pipeline Complete ===
Files processed: 1
Succeeded: 1
Failed: 0
```

**Then queried Neo4j directly** (not just trusting the log line):
```powershell
docker exec aap_neo4j cypher-shell -u neo4j -p localgraphpw "MATCH (n {app_id: 'NEO4JTEST'}) RETURN labels(n), n.name LIMIT 20"
```
```
labels(n), n.name
["Application"], NULL
["Component"], "_unassigned"
["BehaviorGroup"], "BehaviorGroup:helpers"
["BehaviorGroup"], "BehaviorGroup:service"
["Function"], "helpers.invoke_worker"
["Function"], "helpers.read_dynamic"
["Module"], "helpers"
["Function"], "service.create_item"
["Function"], "service.get_client"
["Function"], "service.list_items"
["Function"], "service.log_event"
["Module"], "service"
[], "service"
[], "GET /items"
[], "POST /items"
[], "helpers"
[], "worker-fn"
[], "bucket/key"
[], "API_KEY"
[], "my-bucket/items.json"
```

**Confirmed:** all 10 entities from the analyzer's own count (`BehaviorGroup:2,
Function:6, Module:2`) are present in Neo4j with correct labels and names.
The `[]` rows above are auto-created resource-reference stub nodes (endpoints,
S3 paths, env vars) — see the gap found and fixed immediately below; this was
the run that surfaced it.

## Found and fixed: empty-label gap on auto-created stub nodes

**Root cause:** `write_edges()` called `_split_typed()` to split e.g.
`"Table:orders"` into type + name, but discarded the type half and only used
the name — so nodes it auto-created (when `write_nodes()` hadn't already
created them with a proper label) ended up with no label at all, shown as
`[]` above. `NeptuneWriter` never had this gap — it always set a `~label`
property via the same split.

**Fix:** use the discarded type to set a real Cypher label instead —
`MERGE (s:{s_type} {{id: $source_id}})` — restoring parity with
`NeptuneWriter`'s original behavior.

**Re-verified after the fix**, re-running ingestion on `DISCOUNT`:
```powershell
docker exec aap_neo4j cypher-shell -u neo4j -p localgraphpw "MATCH (n {app_id: 'DISCOUNT'}) RETURN labels(n), n.name LIMIT 20"
```
```
labels(n), n.name
["Application"], NULL
["Component"], "_unassigned"
["BehaviorGroup"], "BehaviorGroup:test_good"
["Function"], "sut.apply_discount"
["Function"], "sut.is_eligible"
["Module"], "sut"
["Function"], "test_fake.run"
["Module"], "test_fake"
["Function"], "test_good.run"
["Module"], "test_good"
["BehaviorGroup"], "test_good"
```
**Zero empty `[]` labels remain** — the previously-empty node (`"test_good"`)
now correctly shows `["BehaviorGroup"]`. The `NEO4JTEST` example above is
intentionally left showing the pre-fix state, as the historical record of
what the gap looked like before the fix.

## Still not exercised
`coding_agent\kb\graph.py`'s read side (`_Neo4jExecutor`, `build_cypher`,
`kb_graph` tool) has unit tests passing against a fake executor, but has
**not** been exercised against this live Neo4j instance — that only happens
inside `core generate`'s AI agent loop, which still requires AWS Bedrock
credentials we don't have (same blocker as before, unrelated to this swap).
