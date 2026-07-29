/**
 * The API client.
 *
 * Types come from `schema.ts`, generated from the OpenAPI document the running
 * API serves (ADR-0009). They are never hand-written: a hand-maintained shape
 * beside a `mypy --strict` backend is a second source of truth that will drift.
 *
 * Regenerate with `npm run generate-client` after `uv run python
 * scripts/development/dump-openapi.py`.
 */

import type { components } from "./schema";

export type Project = components["schemas"]["ProjectResponse"];
export type Session = components["schemas"]["SessionResponse"];
export type Message = components["schemas"]["MessageResponse"];
export type Knowledge = components["schemas"]["KnowledgeResponse"];
export type Run = components["schemas"]["RunResponse"];
export type Readiness = components["schemas"]["ReadinessResponse"];
export type Review = components["schemas"]["ReviewResponse"];
export type Finding = components["schemas"]["FindingResponse"];
export type Blueprint = components["schemas"]["BlueprintResponse"];
export type Trace = components["schemas"]["TraceResponse"];
export type Health = components["schemas"]["HealthResponse"];

/** The error envelope every failure arrives in (ADR-0014). */
export interface ApiErrorBody {
  error: { code: string; message: string; detail: Record<string, unknown> };
}

/**
 * A failed request, carrying the machine-readable code.
 *
 * The code is what the interface acts on: a 409 `invalid_lifecycle_transition`
 * means "reload, it is already confirmed", which is a different message to the
 * user than a 422.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly detail: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });

  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      // A response that is not the envelope — a proxy error, say. Fall through
      // to a generic code rather than pretending to know what happened.
    }
    throw new ApiError(
      response.status,
      body?.error.code ?? "unknown_error",
      body?.error.message ?? response.statusText,
      body?.error.detail,
    );
  }

  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") ?? "";
  return (type.includes("json") ? await response.json() : await response.text()) as T;
}

const post = <T>(path: string, body?: unknown): Promise<T> =>
  request<T>(path, { method: "POST", body: body === undefined ? "{}" : JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/health"),

  projects: () => request<Project[]>("/v1/projects"),
  project: (id: string) => request<Project>(`/v1/projects/${id}`),
  createProject: (name: string, description?: string) =>
    post<Project>("/v1/projects", { name, description }),

  sessions: (projectId: string) => request<Session[]>(`/v1/projects/${projectId}/sessions`),
  openSession: (projectId: string, sessionType = "discovery") =>
    post<Session>(`/v1/projects/${projectId}/sessions`, { session_type: sessionType }),

  messages: (sessionId: string) => request<Message[]>(`/v1/sessions/${sessionId}/messages`),
  recordMessage: (sessionId: string, content: string) =>
    post<Message>(`/v1/sessions/${sessionId}/messages`, { content }),

  knowledge: (projectId: string) => request<Knowledge[]>(`/v1/projects/${projectId}/knowledge`),
  confirmKnowledge: (itemId: string) => post<Knowledge>(`/v1/knowledge/${itemId}/confirm`),
  trace: (itemId: string) => request<Trace>(`/v1/knowledge/${itemId}/trace`),

  runs: (projectId: string) => request<Run[]>(`/v1/projects/${projectId}/runs`),
  run: (runId: string) => request<Run>(`/v1/runs/${runId}`),
  /** Returns 202 with a durable run identifier; the browser never owns the run. */
  enqueueRun: (projectId: string, role: string, key: string, input: Record<string, unknown> = {}) =>
    post<Run>(`/v1/projects/${projectId}/runs`, {
      role,
      idempotency_key: key,
      input_context: input,
    }),

  readiness: (projectId: string) => request<Readiness>(`/v1/projects/${projectId}/readiness`),
  recalculate: (projectId: string) =>
    post<Readiness>(`/v1/projects/${projectId}/readiness/calculate`, {}),
  assignArea: (projectId: string, knowledgeItemId: string, areaKey: string) =>
    post<void>(`/v1/projects/${projectId}/readiness/areas`, {
      knowledge_item_id: knowledgeItemId,
      area_key: areaKey,
    }),

  review: (projectId: string) => request<Review>(`/v1/projects/${projectId}/review`),
  blueprint: (projectId: string) => request<Blueprint>(`/v1/projects/${projectId}/blueprint`),
  blueprintMarkdown: (projectId: string) =>
    request<string>(`/v1/projects/${projectId}/blueprint.md`),
};

/**
 * Subscribe to a run's progress.
 *
 * A convenience over polling, never a replacement for it: correctness must not
 * depend on an uninterrupted browser connection (ADR-0009), so callers keep
 * their query and treat this as an invalidation signal.
 */
export function subscribeToRun(runId: string, onChange: (run: Run) => void): () => void {
  const source = new EventSource(`/v1/runs/${runId}/events`);
  source.addEventListener("run", (event) => onChange(JSON.parse((event as MessageEvent).data)));
  source.addEventListener("close", () => source.close());
  return () => source.close();
}
