// =============================================================================
// CAL (Calculation Service) — Microcks SCRIPT dispatcher
// =============================================================================
// Mode: STUB (permanent — the tenant ships the contract, we own the mock behavior)
// Generated: 2026-04-30 (hand-written)
//
// What this file does:
//   CAL is *stateful* and *async*. Caller POSTs to /calculation2/execute and
//   gets execution_id + state=SUBMITTED. Caller then polls
//   /calculation2/status?execution_id=X. State transitions on a timer:
//
//        SUBMITTED  ──[immediate]──▶  RUNNING  ──[2s TTL]──▶  SUCCEEDED
//
//   This dispatcher uses Microcks's kvStore to track per-execution state.
//   The kvStore TTL drives the RUNNING→SUCCEEDED flip without a real timer
//   thread.
//
// Why 2 seconds (vs real CAL's 10+ minutes):
//   Tests need to complete in seconds, not hours. The contract is preserved;
//   only the *time* dimension is compressed. Scenarios that assert on real
//   timing must tag @requires-cal-real-timing and route to L4.
//
// What this file DOES NOT do:
//   - Run any actual calculation (CAL's math is tenant proprietary)
//   - Validate the submission_data fields (Microcks does shape validation
//     against the OpenAPI; this dispatcher handles routing only)
//   - Model the FAILED state randomly — only returns FAILED if the caller
//     explicitly submits stress_toggle="FAIL_ME" (testing hook)
//
// Replace when:
//   Never. the tenant won't ship dispatcher logic. the tenant's real OpenAPI may
//   change response shapes, in which case we update the OpenAPI's examples
//   and adjust this dispatcher accordingly.
// =============================================================================

var method = requestContext.getRequest().getMethod();
var path = requestContext.getRequest().getURI();

// ─── POST /calculation2/execute ──────────────────────────────────────────────
if (method === "POST" && path.indexOf("/execute") !== -1) {
    var body = JSON.parse(requestContext.getRequest().getContent());
    var executionId = body.scenario_id || ("auto_" + Date.now());

    // Testing hook: if stress_toggle is "FAIL_ME", schedule a FAILED outcome
    if (body.stress_toggle === "FAIL_ME") {
        kvStore.put(executionId, "FAILED", 1);
    } else {
        // Normal path: store RUNNING with a 2-second TTL.
        // After TTL expires, kvStore.get returns null and we treat null = SUCCEEDED.
        kvStore.put(executionId, "RUNNING", 2);
    }

    // Stash the execution_id back in context so the response example can use it.
    requestContext.setProperty("execution_id", executionId);
    return "submitted";  // matches the 202 example in cal.openapi.yaml
}

// ─── GET /calculation2/status?execution_id=X ─────────────────────────────────
if (method === "GET" && path.indexOf("/status") !== -1) {
    var executionId = requestContext.getRequest().getQueryParameter("execution_id");

    if (!executionId) {
        return "not-found";  // 404 example
    }

    var state = kvStore.get(executionId);

    // null means: either we never saw this execution_id, or the TTL expired.
    // For the sandbox we treat TTL-expiry as SUCCEEDED.
    if (state === null) {
        // Distinguish "never seen" from "TTL expired and now succeeded".
        // Heuristic: if executionId looks like one of our generated formats
        // (starts with "202" or "auto_"), treat as TTL-expired = SUCCEEDED.
        if (/^(202|auto_)/.test(executionId)) {
            return "succeeded";  // matches the 'succeeded' example
        }
        return "not-found";
    }

    if (state === "RUNNING")    return "running";    // matches the 'running' example
    if (state === "FAILED")     return "failed";     // matches the 'failed' example
    if (state === "SUCCEEDED")  return "succeeded";

    // Unknown state in kv — defensive
    return "running";
}

// ─── Anything else ───────────────────────────────────────────────────────────
return "not-found";
