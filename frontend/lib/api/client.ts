// Single API client boundary. All backend calls go through this module so the
// wire contract (camelCase JSON, structured {error:{message,details}} errors)
// lives in exactly one place. Backend field names are never renamed here.

import type {
  AnalysisComparison,
  AnalysisRun,
  DefaultRanges,
  RangeCombo,
  RangeSummary,
  SavedScenario,
  Scenario,
  ScenarioRevision,
} from "../../types/scenario";
import type {
  AnalysisResponse,
  PracticeOutcome,
  PracticeQuestion,
  SolveJob,
  SolverSpotPayload,
  StateResponse,
  ContinuousTableResponse,
  TableInsightsResponse,
  TeachingResponse,
} from "../../types/api";
import type { RangeBeliefTraceResponse, RangeBeliefView } from "../../types/rangeBelief";
import type { HandReviewApiResponse } from "../../types/handReview";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

/** Extract the backend's structured message: {error:{message,details?}}. */
export function errorMessage(payload: unknown, fallback: string): string {
  const error = (payload as { error?: { message?: string; details?: unknown } })?.error;
  let message = error?.message ?? fallback;
  const details = error?.details;
  if (Array.isArray(details) && details.length > 0) {
    const first = details[0] as { msg?: string };
    if (first?.msg) message = `${message}：${first.msg}`;
  }
  return message;
}

async function request<T = unknown>(path: string, body: unknown, method: "POST" | "PUT" = "POST"): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(errorMessage(payload, "请求失败"));
  return payload as T;
}

async function requestGet<T = unknown>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  const payload = await response.json();
  if (!response.ok) throw new Error(errorMessage(payload, "请求失败"));
  return payload as T;
}

async function requestDelete<T = unknown>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
  const payload = await response.json();
  if (!response.ok) throw new Error(errorMessage(payload, "请求失败"));
  return payload as T;
}

export const scenariosApi = {
  list: () => requestGet<{ scenarios: SavedScenario[] }>("/v1/scenarios"),
  create: (payload: { scenario: Scenario; title: string; tags: string[] }) =>
    request<{ scenario: SavedScenario }>("/v1/scenarios", payload),
  update: (scenarioId: string, payload: { scenario: Scenario; title: string; tags: string[] }) =>
    request<{ scenario: SavedScenario }>(`/v1/scenarios/${scenarioId}`, payload, "PUT"),
  remove: (scenarioId: string) => requestDelete(`/v1/scenarios/${scenarioId}`),
  copy: (scenarioId: string, title: string) =>
    request(`/v1/scenarios/${scenarioId}/copy`, { title }),
  analyses: (scenarioId: string) =>
    requestGet<{ analyses: AnalysisRun[] }>(`/v1/scenarios/${scenarioId}/analyses`),
  revisions: (scenarioId: string) =>
    requestGet<{ revisions: ScenarioRevision[] }>(`/v1/scenarios/${scenarioId}/revisions`),
  compare: (scenarioId: string, leftAnalysisId: string, rightAnalysisId: string) =>
    requestGet<AnalysisComparison>(
      `/v1/scenarios/${scenarioId}/analyses/compare?leftAnalysisId=${encodeURIComponent(leftAnalysisId)}&rightAnalysisId=${encodeURIComponent(rightAnalysisId)}`,
    ),
  analyze: (scenarioId: string) =>
    request<{ analysis: AnalysisResponse["analysis"] }>(`/v1/scenarios/${scenarioId}/analyze`, {}),
  analyzeRevision: (scenarioId: string, revisionNo: number) =>
    request<{ analysis: AnalysisResponse["analysis"] }>(
      `/v1/scenarios/${scenarioId}/revisions/${revisionNo}/analyze`,
      {},
    ),
  state: (scenario: Scenario) => request<StateResponse>("/v1/scenarios/state", scenario),
};

export const analysisApi = {
  run: (scenario: Scenario) => request<AnalysisResponse>("/v1/analysis", scenario),
};

export type BeliefPolicyPayload =
  | { source: "fixture"; frequencies: Record<string, Record<string, Record<string, string>>> }
  | { source: "preflop_policy" }
  | { source: "solver"; jobId: string }
  | { source: "solver"; result: NonNullable<SolveJob["result"]> }
  | { source: "manual" };

export const rangesApi = {
  defaults: () => requestGet<{ ranges: DefaultRanges }>("/v1/ranges/defaults"),
  parse: (notation: string, deadCards: string[]) =>
    request<{ range: Scenario["heroRange"] & { matrix169: Record<string, string> }; summary: RangeSummary; combos: RangeCombo[] }>(
      "/v1/ranges/parse",
      { notation, deadCards },
    ),
  /** Combo-level action-conditioned belief for one seat (prior/current/delta). */
  belief: (payload: {
    scenario: Scenario;
    seatId: number;
    afterSequence?: number;
    policy?: BeliefPolicyPayload | BeliefPolicyPayload[];
  }) => request<RangeBeliefView>("/v1/ranges/belief", payload),
  trace: (payload: {
    scenario: Scenario;
    seatId: number;
    afterSequence?: number;
    policy?: BeliefPolicyPayload | BeliefPolicyPayload[];
  }) => request<RangeBeliefTraceResponse>("/v1/ranges/trace", payload),
};

export const coachApi = {
  explain: (payload: { scenario: Scenario; depth: string; question?: string }) =>
    request<TeachingResponse>("/v1/teaching", payload),
};

export const solverApi = {
  submit: (scenario: Scenario) =>
    request<SolveJob>(
      "/v1/solve/jobs",
      { scenario, maxIterations: 200 },
    ),
  get: (jobId: string) => requestGet<SolveJob>(`/v1/solve/jobs/${jobId}`),
  cancel: (jobId: string) =>
    request<{ jobId: string; status: string }>(`/v1/solve/jobs/${jobId}/cancel`, {}),
};

export const practiceApi = {
  generate: (payload: { scenario: Scenario; profileId: string; mistakeTag: string }) =>
    request<{ question: PracticeQuestion }>("/v1/practice/generate", payload),
  attempt: (questionId: string, selectedAction: string) =>
    request<{ outcome: PracticeOutcome }>(`/v1/practice/${questionId}/attempt`, { selectedAction }),
};

export const handReviewApi = {
  review: (payload: { scenario: Scenario; solverJobs?: Record<string, string> }) =>
    request<HandReviewApiResponse>("/v1/hand-reviews", payload),
};

export const continuousTableApi = {
  create: (payload: { commandId: string; seed?: number; botProfile: string; sessionId?: string }) =>
    request<ContinuousTableResponse>("/v1/tables", { schemaVersion: 1, ...payload }),
  get: (sessionId: string) => requestGet<ContinuousTableResponse>(`/v1/tables/${encodeURIComponent(sessionId)}`),
  action: (sessionId: string, payload: Record<string, unknown>) =>
    request<ContinuousTableResponse>(`/v1/tables/${encodeURIComponent(sessionId)}/actions`, { schemaVersion: 1, ...payload }),
  nextHand: (sessionId: string, payload: { commandId: string; expectedRevision: number }) =>
    request<ContinuousTableResponse>(`/v1/tables/${encodeURIComponent(sessionId)}/hands`, { schemaVersion: 1, ...payload }),
  insights: (sessionId: string) => requestGet<TableInsightsResponse>(`/v1/tables/${encodeURIComponent(sessionId)}/insights`),
};
