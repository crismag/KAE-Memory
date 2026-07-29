import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import { BlueprintPanel } from "../components/BlueprintPanel";
import { DiscoveryPanel } from "../components/DiscoveryPanel";
import { ErrorNote } from "../components/ErrorNote";
import { KnowledgePanel } from "../components/KnowledgePanel";
import { ReadinessPanel } from "../components/ReadinessPanel";
import { ReviewPanel } from "../components/ReviewPanel";
import { RunsPanel } from "../components/RunsPanel";

const TABS = ["Discovery", "Knowledge", "Readiness", "Review", "Runs", "Blueprint"] as const;
type Tab = (typeof TABS)[number];

/**
 * The workspace.
 *
 * Tabs rather than one scroll, because the product's three kinds of state —
 * conversation, knowledge, and execution — are distinct and a chat-only view
 * would hide the memory, the provenance, and the recovery (ADR-0009).
 */
export function ProjectView() {
  const { projectId = "" } = useParams();
  const [tab, setTab] = useState<Tab>("Discovery");
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.project(projectId),
  });

  if (project.isError) return <ErrorNote error={project.error} />;

  return (
    <section className="stack">
      <h1>{project.data?.name ?? "…"}</h1>

      <nav className="tabs">
        {TABS.map((name) => (
          <button
            key={name}
            className={name === tab ? "tab active" : "tab"}
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </nav>

      {tab === "Discovery" && <DiscoveryPanel projectId={projectId} />}
      {tab === "Knowledge" && <KnowledgePanel projectId={projectId} />}
      {tab === "Readiness" && <ReadinessPanel projectId={projectId} />}
      {tab === "Review" && <ReviewPanel projectId={projectId} />}
      {tab === "Runs" && <RunsPanel projectId={projectId} />}
      {tab === "Blueprint" && <BlueprintPanel projectId={projectId} />}
    </section>
  );
}
