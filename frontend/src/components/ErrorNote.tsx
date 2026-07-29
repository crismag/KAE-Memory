import { ApiError } from "../api/client";

/**
 * Shows a failure with its machine-readable code.
 *
 * The code is shown, not hidden: "already confirmed" and "invalid input" are
 * different problems with different fixes, and the API distinguishes them
 * deliberately (ADR-0014).
 */
export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  if (error instanceof ApiError) {
    const permitted = error.detail?.permitted;
    return (
      <p className="error">
        <code>{error.code}</code> {error.message}
        {Array.isArray(permitted) && <> Permitted: {permitted.join(", ")}.</>}
      </p>
    );
  }
  return <p className="error">{String(error)}</p>;
}
