import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { api, subscribeToRun } from "../api/client";
import { ErrorNote } from "./ErrorNote";

const LIVE = new Set(["pending", "running", "interrupted"]);

/**
 * Execution state.
 *
 * Subscribes to unfinished runs over Server-Sent Events, but the list is still a
 * query: correctness never depends on an uninterrupted browser connection
 * (ADR-0009), so the stream only invalidates what a reload would fetch anyway.
 */
export function RunsPanel({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const runs = useQuery({ queryKey: ["runs", projectId], queryFn: () => api.runs(projectId) });

  const live = (runs.data ?? []).filter((run) => LIVE.has(run.status)).map((run) => run.id);
  const key = live.join(",");

  useEffect(() => {
    if (!key) return;
    const stop = key
      .split(",")
      .map((id) => subscribeToRun(id, () => void client.invalidateQueries()));
    return () => stop.forEach((close) => close());
  }, [key, client]);

  return (
    <div className="stack">
      <ErrorNote error={runs.error} />
      <ul className="stack">
        {(runs.data ?? []).map((run) => (
          <li key={run.id} className="card">
            <div className="row">
              <span className="pill">{run.role}</span>
              <span className={`pill ${run.status === "succeeded" ? "ok" : "warn"}`}>
                {run.status}
              </span>
              <span className="small muted">attempt {run.attempt_number}</span>
              <span className="grow" />
              <span className="small muted">{run.idempotency_key}</span>
            </div>
            {run.error_message && <div className="error small">{run.error_message}</div>}
            {Object.keys(run.output_summary).length > 0 && (
              <pre className="small">{JSON.stringify(run.output_summary, null, 2)}</pre>
            )}
          </li>
        ))}
      </ul>
      {runs.data?.length === 0 && <p className="muted">No runs yet.</p>}
    </div>
  );
}
