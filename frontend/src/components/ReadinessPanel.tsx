import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import { ErrorNote } from "./ErrorNote";

/**
 * The percentage, never alone.
 *
 * A number a user cannot interrogate misrepresents project state (ADR-0012), so
 * every area's contribution and counts are shown beside it.
 */
export function ReadinessPanel({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const readiness = useQuery({
    queryKey: ["readiness", projectId],
    queryFn: () => api.readiness(projectId),
  });
  const recalculate = useMutation({
    mutationFn: () => api.recalculate(projectId),
    onSuccess: () => void client.invalidateQueries(),
  });

  const data = readiness.data;
  return (
    <div className="stack">
      <ErrorNote error={readiness.error ?? recalculate.error} />
      {data && (
        <>
          <div className="row">
            <span className="score">{data.percentage}%</span>
            <span className={`pill ${data.implementation_eligible ? "ok" : "warn"}`}>
              {data.status}
            </span>
            {data.is_stale && <span className="pill warn">stale</span>}
            <span className="grow" />
            <button onClick={() => recalculate.mutate()}>Recalculate</button>
          </div>
          <p className="muted small">
            Draft eligible: {String(data.draft_eligible)} · implementation eligible:{" "}
            {String(data.implementation_eligible)} · knowledge revision {data.knowledge_revision}
          </p>

          <table>
            <thead>
              <tr>
                <th>Area</th>
                <th>State</th>
                <th>Confirmed</th>
                <th>Needs</th>
                <th>Weight</th>
              </tr>
            </thead>
            <tbody>
              {data.areas.map((area) => (
                <tr key={area.key}>
                  <td>
                    {area.name}
                    {area.mandatory && <span className="small muted"> · mandatory</span>}
                  </td>
                  <td>
                    <span className={`pill ${area.state === "sufficient" ? "ok" : "warn"}`}>
                      {area.state}
                    </span>
                  </td>
                  <td>{area.confirmed_count}</td>
                  <td>{area.minimum_confirmed}</td>
                  <td>{area.weight}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
