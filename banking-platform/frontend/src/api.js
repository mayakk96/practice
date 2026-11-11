import JSONbigFactory from "json-bigint";
const JSONbig = JSONbigFactory({ storeAsString: true });
export async function request(path, credentials, options = {}) {
  const headers = new Headers(options.headers || {});
  if (credentials?.username) {
    const bytes = new TextEncoder().encode(
      `${credentials.username}:${credentials.password}`,
    );
    headers.set(
      "Authorization",
      `Basic ${btoa(Array.from(bytes, (b) => String.fromCharCode(b)).join(""))}`,
    );
  }
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(path, {
    ...options,
    credentials: "omit",
    headers,
    signal: AbortSignal.timeout(20000),
  });
  const text = await response.text();
  let data;
  try {
    data = text ? JSONbig.parse(text) : {};
  } catch {
    throw new Error("The server returned an unreadable response.");
  }
  if (!response.ok) {
    const error = new Error(
      data.detail || `Request failed (${response.status}).`,
    );
    error.status = response.status;
    error.requestId = data.requestId || response.headers.get("X-Request-ID");
    throw error;
  }
  return data;
}
