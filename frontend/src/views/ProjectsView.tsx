import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { ErrorNote } from "../components/ErrorNote";

export function ProjectsView() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });

  const create = useMutation({
    mutationFn: (value: string) => api.createProject(value),
    onSuccess: () => {
      setName("");
      void client.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) create.mutate(name.trim());
  };

  return (
    <section className="stack">
      <h1>Projects</h1>
      <p className="muted">
        A project is the durable boundary. Nothing is read across projects.
      </p>

      <form className="row" onSubmit={submit}>
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Name a project"
          aria-label="Project name"
        />
        <button type="submit" disabled={create.isPending || !name.trim()}>
          Create
        </button>
      </form>
      <ErrorNote error={create.error} />

      {projects.isLoading && <p className="muted">Loading…</p>}
      <ErrorNote error={projects.error} />

      <ul className="cards">
        {(projects.data ?? []).map((project) => (
          <li key={project.id} className="card">
            <Link to={`/projects/${project.id}`}>{project.name}</Link>
            <div className="muted small">{project.key}</div>
          </li>
        ))}
      </ul>
      {projects.data?.length === 0 && <p className="muted">No projects yet.</p>}
    </section>
  );
}
