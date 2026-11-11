import assert from "node:assert/strict";
import test from "node:test";
import { request } from "./api.js";

test("API authentication excludes ambient credentials and retains explicit UTF-8 authorization", async () => {
  const originalFetch = globalThis.fetch;
  let received;
  globalThis.fetch = async (path, options) => {
    received = { path, options };
    return new Response('{"totalMinor":90071992547409930001}', {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  try {
    const result = await request(
      "/api/transactions",
      { username: "synthetic-opérateur", password: "synthetic-sécret" },
      { method: "POST", body: '{"amountMinor":100}', credentials: "include" },
    );
    assert.equal(received.path, "/api/transactions");
    assert.equal(received.options.credentials, "omit");
    assert.equal(
      received.options.headers.get("Authorization"),
      `Basic ${Buffer.from("synthetic-opérateur:synthetic-sécret", "utf8").toString("base64")}`,
    );
    assert.equal(received.options.headers.get("Content-Type"), "application/json");
    assert.equal(result.totalMinor, "90071992547409930001");
    assert(received.options.signal instanceof AbortSignal);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("API failures preserve safe Problem Details and correlation metadata", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response('{"detail":"Read-only account cannot perform this operation."}', {
    status: 403,
    headers: { "Content-Type": "application/problem+json", "X-Request-ID": "synthetic-correlation" },
  });
  try {
    await assert.rejects(request("/api/transactions", null), (error) => {
      assert.equal(error.status, 403);
      assert.equal(error.requestId, "synthetic-correlation");
      assert.equal(error.message, "Read-only account cannot perform this operation.");
      return true;
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
