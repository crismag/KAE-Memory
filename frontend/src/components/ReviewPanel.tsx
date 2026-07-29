import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import { ErrorNote } from "./ErrorNote";

/** What is unresolved, without inspecting the database (FR-015). */
export function ReviewPanel({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const review = useQuery({
    queryKey: ["review", projectId],
    queryFn: () => api.review(projectId),
  });
  const runReview = useMutation({
    mutationFn: () => api.enqueueRun(projectId, "review", `review-${Date.now()}`),
    onSuccess: () => void client.invalidateQueries(),
  });

  return (
    <div className="stack">
      <div className="row">
        <p className="muted grow">
          Findings are derived from current state, not stored. One disappears when the
          condition that produced it is resolved.
        </p>
        <button onClick={() => runReview.mutate()}>Run Review agent</button>
      </div>
      <ErrorNote error={review.error ?? runReview.error} />

      {review.data && (
        <p className="small muted">
          {review.data.counts.total} finding(s) · {review.data.counts.critical} critical ·{" "}
          {review.data.counts.major} major · {review.data.counts.minor} minor
        </p>
      )}

      <ul className="stack">
        {(review.data?.findings ?? []).map((finding, index) => (
          <li key={index} className="card">
            <div className="row">
              <span className={`pill ${finding.severity === "critical" ? "bad" : "warn"}`}>
                {finding.severity}
              </span>
              <span className="pill">{finding.kind}</span>
            </div>
            <div>{finding.summary}</div>
            <div className="small muted">{finding.recommended_action}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
