import test from "node:test";
import assert from "node:assert/strict";
import { money, toMinor } from "./format.js";
test("financial display preserves aggregate integer precision and currency signs", () => {
  assert.equal(money("10000000000000001", "USD"), "$100,000,000,000,000.01");
  assert.equal(money(-51, "EUR"), "−€0.51");
  assert.equal(money(0, "GBP"), "£0.00");
});
test("decimal input uses exact integer conversion without rounding", () => {
  assert.equal(toMinor("10.01"), 1001);
  assert.equal(toMinor("0.1"), 10);
  assert.equal(toMinor("10000000000.00"), 1000000000000);
  for (const text of ["0", "1.001", "-1", "1e2", "1,000", "10000000000.01"])
    assert.throws(() => toMinor(text));
});
