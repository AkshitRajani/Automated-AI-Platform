# Demo suites (V1 vs V2)

Synthetic DCFO late-fee fixtures for scoring demos.

| Folder | Features | Requirements | Intent |
|--------|----------|--------------|--------|
| `v1/` | 13 | 13 | Lower quality — vague BDD, thin MD, UI/unit noise |
| `v2/` | 6 | 22 | ~40% stronger — journey BDD, structured requirement sections |

Layout (identical):

```
v1|v2/
  feature/         # *.feature
  requirements/    # *.md
```

Regenerate:

```powershell
py generate_demo_suites.py
```

For a fair scoring compare, use the **same golden (manual)** zip against each version’s `feature/` as generated, and optionally each version’s `requirements/` (or a frozen shared requirements set).
