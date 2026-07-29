import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Trace } from "../api/client";
import { ErrorNote } from "./ErrorNote";

/** Every statement carries a label and a trace target (FR-008). */
export function BlueprintPanel({ projectId }: { projectId: string }) {
  const [trace, setTrace] = useState<Trace | null>(null);
  const blueprint = useQuery({
    queryKey: ["blueprint", projectId],
    queryFn: () => api.blueprint(projectId),
  });

  const data = blueprint.data;
  return (
    <div className="stack">
      <ErrorNote error={blueprint.error} />
      {data && (
        <>
          <div className="row">
            <span className={`pill ${data.complete ? "ok" : "warn"}`}>
              {data.complete ? "implementation blueprint" : "draft — incomplete"}
            </span>
            <span className="small muted">
              {data.statement_count} statement(s) · readiness {data.readiness_percentage}%
            </span>
            <span className="grow" />
            <a href={`/v1/projects/${projectId}/blueprint.md`}>Export Markdown</a>
          </div>

          {data.sections.map((section) => (
            <div key={section.area_key} className="stack">
              <h2>{section.area_name}</h2>
              <ul className="stack">
                {section.statements.map((statement) => (
                  <li key={statement.id} className="card">
                    <div>{statement.text}</div>
                    <div className="row small">
                      <span className="pill">{statement.label}</span>
                      <button onClick={() => api.trace(statement.knowledge_item_id).then(setTrace)}>
                        Trace
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}

          {data.sections.length === 0 && (
            <p className="muted">
              No confirmed knowledge is assigned to an area, so there is nothing to render.
              {data.unassigned_confirmed_count > 0 &&
                ` ${data.unassigned_confirmed_count} confirmed item(s) belong to no area.`}
            </p>
          )}

          {data.missing_mandatory_areas.length > 0 && (
            <div className="card">
              <strong>Missing mandatory areas</strong>
              <ul className="small">
                {data.missing_mandatory_areas.map((area) => (
                  <li key={area}>{area.replaceAll("_", " ")}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

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
