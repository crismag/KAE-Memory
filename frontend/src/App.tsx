import { useQuery } from "@tanstack/react-query";
import { Link, Outlet } from "react-router-dom";

import { api } from "./api/client";

/** The shell: navigation, and an honest health indicator. */
export function App() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });

  return (
    <>
      <header className="bar">
        <Link to="/" className="brand">
          KAE-Memory
        </Link>
        <span className="grow" />
        <span className={`pill ${health.data?.status === "ok" ? "ok" : "warn"}`}>
          {health.isError
            ? "api unreachable"
            : `${health.data?.database ?? "…"} · rev ${health.data?.migration_revision ?? "?"}`}
        </span>
      </header>
      <main>
        <Outlet />
      </main>
    </>
  );
}
