export const today = () => new Date().toISOString().slice(0, 10);
export function money(minor, currency = "USD") {
  if (minor === null || minor === undefined) return "—";
  const value = BigInt(minor),
    negative = value < 0n,
    absolute = negative ? -value : value;
  return `${negative ? "−" : ""}${{ USD: "$", EUR: "€", GBP: "£" }[currency] || `${currency} `}${(absolute / 100n).toLocaleString("en-US")}.${String(absolute % 100n).padStart(2, "0")}`;
}
export function toMinor(text) {
  if (!/^\d{1,11}(\.\d{1,2})?$/.test(text))
    throw new Error("Enter a positive amount with at most two decimal places.");
  const [major, cents = ""] = text.split(".");
  const value = BigInt(major) * 100n + BigInt(cents.padEnd(2, "0"));
  if (value <= 0n || value > 1000000000000n)
    throw new Error("Amount must be between 0.01 and 10,000,000,000.00.");
  return Number(value);
}
export const shortId = (value) =>
  value ? `${value.slice(0, 8)}…${value.slice(-4)}` : "—";
export const words = (value) =>
  value
    ? value
        .replaceAll("_", " ")
        .toLowerCase()
        .replace(/^./, (s) => s.toUpperCase())
    : "—";
export const timestamp = (value) =>
  value
    ? new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "UTC",
      }).format(new Date(value)) + " UTC"
    : "—";
