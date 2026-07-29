# Parameter Bindings

Drop YAML files here. One per application.

## Format

```yaml
TOKEN_NAME.property: resolved_value
```

## Example

```yaml
LN_TM_SERS_MBS4PLUS.glue_database_name: actual_database_name
LN_TM_SERS_MBS4PLUS.glue_table_name: actual_table_name
BUCKET: actual-bucket-name
```

Re-run `python -m ingestion` and tokens resolve automatically.
