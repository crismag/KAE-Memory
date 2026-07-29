import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Trace } from "../api/client";
import { ErrorNote } from "./ErrorNote";

const AREAS = [
  "problem_and_value",
  "users_and_stakeholders",
  "scope_and_boundaries",
  "functional_requirements",
  "quality_attributes",
  "domain_model_and_data",
  "interfaces_and_integrations",
  "constraints_and_assumptions",
  "acceptance_criteria",
  "delivery_and_operations",
];

/** Candidates and confirmed knowledge, with the trace behind each item. */
export function KnowledgePanel({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const [trace, setTrace] = useState<Trace | null>(null);
  const knowledge = useQuery({
    queryKey: ["knowledge", projectId],
    queryFn: () => api.knowledge(projectId),
  });

  const confirm = useMutation({
    mutationFn: (id: string) => api.confirmKnowledge(id),
    onSuccess: () => void client.invalidateQueries(),
  });
  const assign = useMutation({
    mutationFn: ({ id, area }: { id: string; area: string }) =>
      api.assignArea(projectId, id, area),
    onSuccess: () => void client.invalidateQueries(),
  });

  return (
    <div className="stack">
      <p className="muted">
        Confirmation is a human act — no agent confirms its own output. An area only counts
        knowledge of a kind it accepts.
      </p>
      <ErrorNote error={confirm.error ?? assign.error} />

      <ul className="stack">
        {(knowledge.data ?? []).map((item) => (
          <li key={item.id} className="card">
            <div className="row">
              <span className={`pill ${item.lifecycle === "validated" ? "ok" : "warn"}`}>
                {item.lifecycle}
              </span>
              <span className="pill">{item.kind}</span>
              <span className="grow" />
              <span className="small muted">v{item.versions.length}</span>
            </div>
            <div>{item.current_content}</div>
            <div className="row">
              {item.lifecycle === "proposed" && (
                <button onClick={() => confirm.mutate(item.id)}>Confirm</button>
              )}
              <select
                defaultValue=""
                aria-label={`Assign area for ${item.id}`}
                onChange={(event) =>
                  event.target.value && assign.mutate({ id: item.id, area: event.target.value })
                }
              >
                <option value="">Assign to area…</option>
                {AREAS.map((area) => (
                  <option key={area} value={area}>
                    {area.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
              <button onClick={() => api.trace(item.id).then(setTrace)}>Trace</button>
            </div>
          </li>
        ))}
      </ul>
      {knowledge.data?.length === 0 && <p className="muted">Nothing extracted yet.</p>}

      {trace && (
        <div className="card">
          <div className="row">
            <strong>Trace</strong>
            <span className="grow" />
            <button onClick={() => setTrace(null)}>Close</button>
          </div>
          <ol className="stack small">
            {trace.steps.map((step, index) => (
              <li key={index}>
                <code>{step.relation}</code> {step.detail ?? step.reference}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
