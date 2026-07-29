// =============================================================================
// DBM (Data Backbone Manager) — Microcks SCRIPT dispatcher
// =============================================================================
// Mode: STUB (permanent — tenant will ship the real OpenAPI but never their
//             internal dispatcher logic; we maintain this file ourselves)
// Generated: 2026-04-30 (hand-written)
//
// What this file does:
//   When Microcks receives a request matched against dbm.openapi.yaml, this
//   script decides which response example to return based on the request's
//   query parameters. DBM is stateless (a registry lookup), so no kvStore
//   is needed — just a switch on `name`.
//
// What it DOES NOT do:
//   - Validate auth tokens (real DBM has internal-service auth)
//   - Enforce business rules ("this name is only valid for this jumpoff")
//   - Return real production data
//
// Replace when:
//   the tenant ships the real DBM OpenAPI (P0.2). Even then, this dispatcher
//   stays — the tenant ships the *contract*, we keep the *mock behavior*.
//   A new delivered/dbm.openapi.yaml may add fields we should reflect here.
// =============================================================================

// requestContext is provided by Microcks; we read query params from it.
var name = requestContext.getRequest().getQueryParameter("name");
var scenario_id = requestContext.getRequest().getQueryParameter("scenario_id");
var jumpoff = requestContext.getRequest().getQueryParameter("jumpoff");

// 400 if neither scenario_id nor jumpoff provided
if (!scenario_id && !jumpoff) {
    return "missing-coordinate";  // matches a 400 example in the OpenAPI
}

// Catalog: maps logical dataset names to physical coordinates.
// Names taken from real evidence:
//   - 'CCFA_CashFlow_TV'   → ccfa_tv_load_yml_metadata_ingest.json
//   - 'LN_INTRM_TM_SERS_DATA_PREP_SPST' → mb4.yml input table reference
//   - 'LN_TM_SERS_MBS4PLUS' → mb4.yml output table reference
var catalog = {
    "CCFA_CashFlow_TV": {
        s3_bucket: "etl-devl-fcdl-pp80-staging",
        s3_prefix: "cashflow/CCFA_CashFlow_TV/",
        glue_database_name: "aap_sandbox_devl",
        glue_table_name: "ccfa_cashflow_tv"
    },
    "LN_INTRM_TM_SERS_DATA_PREP_SPST": {
        s3_bucket: "etl-devl-fcdl-pp80-staging",
        s3_prefix: "input/LN_INTRM_TM_SERS_DATA_PREP_SPST/",
        glue_database_name: "aap_sandbox_devl",
        glue_table_name: "ln_intrm_tm_sers_data_prep_spst"
    },
    "LN_TM_SERS_MBS4PLUS": {
        s3_bucket: "etl-devl-fcdl-pp80-staging",
        s3_prefix: "output/MBS4PLUS/",
        glue_database_name: "aap_sandbox_devl",
        glue_table_name: "ln_tm_sers_mbs4plus"
    },
    "CCFA_Loan_List": {
        s3_bucket: "aap_sandbox-devl-fcdl-us-east-1",
        s3_prefix: "insight/cin/dflt/CCFA_Loan_List/",
        glue_database_name: "aap_sandbox_devl",
        glue_table_name: "ccfa_loan_list"
    }
};

// Lookup: return matching example or 404
if (catalog[name]) {
    // Pick the matching example name in the OpenAPI's examples block.
    // dbm.openapi.yaml has two named examples: "ccfa_tv_resolution" and
    // "input_table_resolution". We dispatch by name.
    if (name === "CCFA_CashFlow_TV") return "ccfa_tv_resolution";
    if (name === "LN_INTRM_TM_SERS_DATA_PREP_SPST") return "input_table_resolution";
    // Fallback: return the first example in the OpenAPI for any other catalog hit.
    return "ccfa_tv_resolution";
}

// Unknown name → 404
return "not-found";
