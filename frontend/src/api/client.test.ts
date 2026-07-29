import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "./client";

function respond(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("the API client", () => {
  it("surfaces the machine-readable code from the error envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        respond(
          { error: { code: "invalid_lifecycle_transition", message: "already", detail: {} } },
          { status: 409, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    const failure = await api.confirmKnowledge("abc").catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).code).toBe("invalid_lifecycle_transition");
    expect((failure as ApiError).status).toBe(409);
  });

  it("keeps the permitted set a 422 offers, so the interface can show it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        respond(
          {
            error: {
              code: "invalid_role",
              message: "Unknown role",
              detail: { permitted: ["architecture", "requirements", "review"] },
            },
          },
          { status: 422, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    const failure = (await api
      .enqueueRun("p", "reviewer", "k")
      .catch((error: unknown) => error)) as ApiError;

    expect(failure.detail.permitted).toContain("review");
  });

  it("sends an idempotency key with every enqueued run", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond({ id: "r1" }, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);

    await api.enqueueRun("p1", "requirements", "extract-1", { message_id: "m1" });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toMatchObject({
      role: "requirements",
      idempotency_key: "extract-1",
      input_context: { message_id: "m1" },
    });
  });

  it("returns undefined for a 204 rather than trying to parse a body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));

    await expect(api.assignArea("p", "k", "problem_and_value")).resolves.toBeUndefined();
  });
});
