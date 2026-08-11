# J10/J11 Agent teaching wiring audit

Date: 2026-08-11
Scope: J10 external single-node teaching and J11 external whole-hand review. This is a diagnosis-only audit; no production code was changed.

## Result

| Journey / route | External Teacher transport | Node-bounded facts | Provenance response | UI provenance | Status |
|---|---:|---|---|---|---|
| J10, `POST /v1/teaching` | 1 call / request | Yes, via `TeachingToolGateway` | `provider`, `teacherVersion`, `promptVersion`, `degraded` | Partial: provider, degradation, teacher version | Pass with gaps |
| J10, `POST /v1/scenarios/{id}/teach` | 1 call / request | Yes, same Teacher path | Same four fields | No dedicated frontend caller | Backend pass / UI gap |
| J11, `POST /v1/hand-reviews` | 0 calls / N decisions | Local node snapshots only | No Agent provenance | No provider/version/degraded rendering | **P0 fail** |

The new deterministic audit suite proves the two J10 routes by injecting `RecordingTransport` into `ExternalModelTeacher`, then injecting that teacher through `create_app(..., teacher=...)`. It deliberately fails J11 until the hand-review endpoint is wired to the same constrained Teacher abstraction.

## Endpoint and click call graph

```text
Teaching explanation button
  -> frontend/app/page.tsx runTeaching()
  -> frontend/lib/api/client.ts coachApi.explain()
  -> POST /v1/teaching
  -> analyze_scenario() [deterministic]
  -> ExternalModelTeacher.explain() -> injected transport
  -> response envelope -> TeachingPanel

Saved scenario API (no dedicated frontend client/click)
  -> POST /v1/scenarios/{id}/teach
  -> analyze_scenario() [deterministic]
  -> same ExternalModelTeacher.explain() -> injected transport

Generate whole-hand review button
  -> frontend/app/page.tsx runWholeHandReview()
  -> frontend/lib/api/client.ts handReviewApi.review()
  -> POST /v1/hand-reviews
  -> review.build_hand_review()
  -> analyze_scenario() once per snapshot [deterministic]
  -> compose_hand_review_teaching() [deterministic local templates]
  -> WholeHandReviewPanel / DecisionReviewCard
```

Current scenario analysis does **not** call an Agent. `POST /v1/analysis`, the saved-analysis routes, and the analysis done inside teaching/review call `analyze_scenario`; that is deterministic analysis. An external Teacher is only invoked after analysis in the two J10 teaching routes.

## Audit evidence and commands

The normal `pytest.ini` only collects `backend/tests`; the audit intentionally lives outside it.

```powershell
# Expected current result: J10 tests pass; the final J11 release-gate test fails.
py -3.13 -m pytest audits/agent_teaching -q

# Isolate the passing single-node/saved-route contract checks.
py -3.13 -m pytest audits/agent_teaching/test_wiring_audit.py -q -k "not hand_review"

# Minimal deterministic J11 red signal.
py -3.13 -m pytest audits/agent_teaching/test_wiring_audit.py -q -k hand_review
```

`audits/agent_teaching/test_wiring_audit.py` contains no network transport. The fake records its system prompt, parsed facts, model name, and timeout. It covers:

- external success and exactly one call for `/v1/teaching`;
- saved-scenario `/teach` using the same injected transport;
- timeout and invalid response-shape/schema drift falling back to the deterministic local teacher with `provider=external_llm`, `degraded=true`;
- unknown evidence references being stripped and uncited numeric text replaced, while remaining external output is still correctly labelled `external_llm` rather than local;
- an eight-decision completed hand where J11 expects eight bounded calls but deterministically observes zero.

The successful J10 fake sees only the requested flop node (`2c 7d Jh`) and asserts that future `9s` is absent. Current J11 local tests already prove snapshot board isolation, but an external whole-hand Agent cannot be tested for isolation because no Teacher seam reaches it. That is an architectural gap, not a passing external-Agent result.

## Detailed findings

### P0 — J11 has no external Agent wiring

`api/app.py` calls `build_hand_review(...)` without a teacher. `review/service.py` calls `analyze_scenario(...)` for each snapshot then `compose_hand_review_teaching(...)`. The latter constructs `DecisionTeaching(provider="local")` and fixed `WholeHandTeaching` templates. A recording `ExternalModelTeacher` injected into `create_app` receives **0 calls for 8 real decisions**.

Minimum repro:

```powershell
py -3.13 -m pytest audits/agent_teaching/test_wiring_audit.py -q -k hand_review
```

Expected current failure text: `expected one bounded Teacher call per decision (8), got 0`.

Consequences:

- There is no external success, timeout/error fallback, schema-drift, invalid-evidence, or future-card-isolation contract for J11.
- `wholeHandSummary` is a deterministic local aggregation, not Agent output; it has no provider/version/degraded fields.
- Per-decision `provider` is fixed to `local` in the review schema and frontend type. It should not be described as external Agent output.

### P0 — whole-hand provenance is invisible and local templates are not explicitly labelled

The J11 wire contract exposes no `teacherVersion`, `promptVersion`, or `degraded`, and only allows `provider: "local"` for decisions. `DecisionReviewCard` presents a mode (Solver/原则性说明) but not teaching provider or version. `WholeHandReviewPanel` renders only summary and uncertainty. Therefore a future externally generated summary would currently be indistinguishable in the UI unless the contract and UI change together.

### P1 — J10 prompt version is returned but dropped before UI

Both J10 API routes return `provider`, `teacherVersion`, `promptVersion`, and `degraded`. The frontend `TeachingMeta` stores only provider, degraded, and teacherVersion; `TeachingPanel` renders those three. `promptVersion` is lost and is not visible. The panel does correctly call a local fallback `external_llm · degraded(本地回退)` rather than labelling it as a successful external Agent result.

### P1 — saved-scenario teaching endpoint lacks a direct frontend route

The backend route is correctly wired, but `frontend/lib/api/client.ts` has no saved-scenario `teach` method and the page has no caller for `/v1/scenarios/{id}/teach`. A user may load a saved scenario and use the ordinary J10 button, which calls `/v1/teaching`; that is not a direct trace to the saved-scenario endpoint.

## Recommended contract changes

1. Add a review-scoped Teacher protocol/parameter to `build_hand_review`, passed by `/v1/hand-reviews` from the app's configured Teacher. For each decision, construct the already-existing bounded snapshot scenario and invoke it exactly once with that node's `AnalysisResult`.
2. Define a review teaching envelope with `provider`, `teacherVersion`, `promptVersion`, `degraded`, and explicit `sourceKind` (`external_agent` or `local_deterministic_template`). Put the same provenance on the whole-hand summary. Do not overload Solver `mode` as Agent provenance.
3. Preserve the deterministic local path as an explicit fallback. On external transport, parse, or validation failure, expose `provider=external_llm`, `degraded=true`, `sourceKind=local_deterministic_template`, plus a safe failure reason/category if product policy permits it.
4. Render the review provenance in `DecisionReviewCard` and `WholeHandReviewPanel`; retain `promptVersion` in `TeachingMeta` and display it in the single-node panel as well.
5. Add a deliberate frontend entrypoint if `/v1/scenarios/{id}/teach` remains a supported public journey; otherwise deprecate/document it as API-only so J10 does not claim a nonexistent click path.
6. Once wired, replace the current J11 red assertion with a green contract that verifies N calls for N player decisions, first/second-call facts do not include future turn/river cards, and all fallback/schema/evidence cases carry truthful provenance.

## Risk and boundary

The audit validates the supported Python dependency-injection seam and backend response contracts. It does not start the browser against the in-process fake, so UI conclusions come from the actual TypeScript call/render paths rather than a browser fake-server run. The existing whole-hand local snapshot tests establish deterministic temporal isolation; they do not establish external-Agent temporal isolation.
