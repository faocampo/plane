import { describe, it, expect, vi } from "vitest";
import { ManualGate2Service } from "../../../../packages/services/src/curve/manual-gate2.service";
import { command, completed, definitionRef, material, response, status, target } from "./manual-plan-gate2-fixtures";
const csrf = () => response({ csrf_token: "a".repeat(64) });
describe("manual Gate2 transport", () => {
  it("checks metadata scope and original material byte identity", async () => {
    const send = vi
      .fn()
      .mockResolvedValueOnce(response(status))
      .mockResolvedValueOnce(response(material("DEFINITION")));
    const api = new ManualGate2Service(send);
    expect((await api.status(target)).data).toEqual(status);
    expect((await api.material(target, definitionRef)).data.content).toEqual(material("DEFINITION").content);
  });
  it.each(["foreign", "extra", "execution", "version"])("rejects %s metadata", async (mode) => {
    const data = {
      ...status,
      ...(mode === "foreign"
        ? { workspace_id: "40000000-0000-4000-8000-000000000099" }
        : mode === "extra"
          ? { private: true }
          : mode === "execution"
            ? { execution_authorized: true }
            : { initiative_version: 9 }),
    };
    await expect(new ManualGate2Service(vi.fn().mockResolvedValue(response(data))).status(target)).rejects.toThrow();
  });
  it("rejects material content substitution even when metadata agrees", async () => {
    const send = vi.fn().mockResolvedValue(response({ ...material("DEFINITION"), content: "substituted" }));
    await expect(new ManualGate2Service(send).material(target, definitionRef)).rejects.toThrow();
  });
  it("binds a posted decision to its exact request and fresh CSRF", async () => {
    const send = vi
      .fn()
      .mockResolvedValueOnce(csrf())
      .mockResolvedValueOnce(response(completed(), 201, 11));
    expect((await new ManualGate2Service(send).execute(target, command())).data).toEqual(completed());
    expect(send.mock.calls[1][1]).toMatchObject({
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: { "Idempotency-Key": command().idempotencyKey, "X-CSRFTOKEN": "a".repeat(64) },
    });
  });
  it("accepts original replay with a newer current version", async () => {
    const send = vi
      .fn()
      .mockResolvedValueOnce(csrf())
      .mockResolvedValueOnce(response(completed(), 200, 14));
    expect((await new ManualGate2Service(send).execute(target, command())).currentVersion).toBe(14);
  });
  it.each(["network", "server", "substitution"])(
    "preserves %s outcome as unknown without automatic resend",
    async (mode) => {
      const send = vi.fn().mockResolvedValueOnce(csrf());
      if (mode === "network") send.mockRejectedValueOnce(new Error("unconfirmed"));
      else
        send.mockResolvedValueOnce(
          response(
            mode === "substitution" ? { ...completed(), request_digest: status.current_record!.request_digest } : {},
            mode === "server" ? 503 : 201,
            11
          )
        );
      await expect(new ManualGate2Service(send).execute(target, command())).rejects.toMatchObject({ code: "UNKNOWN" });
      expect(send).toHaveBeenCalledTimes(2);
    }
  );
});
