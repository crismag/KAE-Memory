import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api } from "../api/client";
import { ErrorNote } from "./ErrorNote";

/** Submit an idea, then ask the Requirements agent to read it. */
export function DiscoveryPanel({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const [text, setText] = useState("");

  const sessions = useQuery({
    queryKey: ["sessions", projectId],
    queryFn: () => api.sessions(projectId),
  });
  const current = sessions.data?.[0];
  const messages = useQuery({
    queryKey: ["messages", current?.id],
    queryFn: () => api.messages(current!.id),
    enabled: Boolean(current),
  });

  const submit = useMutation({
    mutationFn: async (content: string) => {
      const session = current ?? (await api.openSession(projectId));
      const message = await api.recordMessage(session.id, content);
      // 202 with a durable identifier. The worker claims it; closing this tab
      // cannot lose the run (ADR-0009).
      await api.enqueueRun(projectId, "requirements", `extract-${message.id}`, {
        message_id: message.id,
      });
      return message;
    },
    onSuccess: () => {
      setText("");
      void client.invalidateQueries();
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (text.trim()) submit.mutate(text.trim());
  };

  return (
    <div className="stack">
      <p className="muted">
        What you submit is stored verbatim as evidence. Extraction never rewrites it.
      </p>

      <form className="stack" onSubmit={onSubmit}>
        <textarea
          rows={4}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Describe the idea, however incomplete."
          aria-label="Idea"
        />
        <div className="row">
          <button type="submit" disabled={submit.isPending || !text.trim()}>
            Submit and extract
          </button>
          {submit.isPending && <span className="muted">Enqueueing…</span>}
        </div>
      </form>
      <ErrorNote error={submit.error} />

      <ul className="stack">
        {(messages.data ?? []).map((message) => (
          <li key={message.id} className="card">
            <div className="small muted">
              #{message.sequence_number} · {message.actor_type} · {message.message_type}
            </div>
            <div className="verbatim">{message.content}</div>
          </li>
        ))}
      </ul>
      {current && messages.data?.length === 0 && <p className="muted">No messages yet.</p>}
    </div>
  );
}
