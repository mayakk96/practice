import React, { useEffect, useState } from "react";
import { toMinor, today, words } from "./format.js";
import { Icon, Modal, Badge } from "./components.jsx";
export function PaymentModal({
  close,
  accounts,
  currency,
  call,
  onSuccess,
  onError,
  onAccount,
}) {
  const [accountId, setAccountId] = useState(
      accounts.find((a) => a.currency === currency)?.id ||
        accounts[0]?.id ||
        "",
    ),
    [amount, setAmount] = useState("100.00"),
    [type, setType] = useState("CARD_PURCHASE"),
    [reference, setReference] = useState(
      `DEMO-PAY-${crypto.randomUUID().slice(0, 8)}`,
    ),
    [date, setDate] = useState(today()),
    [key] = useState(crypto.randomUUID()),
    [busy, setBusy] = useState(false),
    [localAccounts, setLocalAccounts] = useState(accounts);
  async function createAccount() {
    setBusy(true);
    try {
      const suffix = crypto.randomUUID().slice(0, 8);
      const customer = await call("/api/customers", {
        method: "POST",
        body: JSON.stringify({
          externalReference: `DEMO-CUSTOMER-${suffix}`,
          displayName: "Synthetic demo customer",
        }),
      });
      const account = await call("/api/accounts", {
        method: "POST",
        body: JSON.stringify({
          customerId: customer.id,
          accountReference: `DEMO-ACCOUNT-${suffix}`,
          currency,
        }),
      });
      setLocalAccounts((a) => [...a, account]);
      setAccountId(account.id);
      onAccount();
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const account = localAccounts.find((a) => a.id === accountId);
      const result = await call("/api/transactions", {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({
          externalReference: reference,
          transactionType: type,
          amountMinor: toMinor(amount),
          currency: account.currency,
          sourceAccountId: accountId,
          counterpartyReference: "DEMO-MERCHANT",
          businessDate: date,
        }),
      });
      onSuccess(result);
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="New payment instruction"
      subtitle="Submit a synthetic instruction with a stable idempotency key."
      close={close}
    >
      <form className="form" onSubmit={submit}>
        {localAccounts.length ? (
          <label>
            Source account
            <select
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
              required
            >
              {localAccounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.accountReference} · {a.currency}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <div className="empty-account">
            <strong>Create your first synthetic account</strong>
            <p>
              A fictional customer and {currency} account will be added to this
              sandbox.
            </p>
            <button
              type="button"
              className="button subtle"
              onClick={createAccount}
              disabled={busy}
            >
              Create synthetic account
            </button>
          </div>
        )}
        <div className="form-columns">
          <label>
            Amount
            <input
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              required
            />
          </label>
          <label>
            Business date
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              required
            />
          </label>
        </div>
        <label>
          Transaction type
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="CARD_PURCHASE">Card purchase</option>
            <option value="ACCOUNT_TRANSFER">Account transfer</option>
          </select>
        </label>
        <label>
          External reference
          <input
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            maxLength={100}
            pattern="[A-Za-z0-9._:-]+"
            required
          />
        </label>
        <div className="key-note">
          <Icon name="shield" size={16} />
          <span>
            Idempotency key<code>{key}</code>
          </span>
        </div>
        <button className="button primary full" disabled={busy || !accountId}>
          {busy ? "Submitting…" : "Submit payment instruction"}
        </button>
      </form>
    </Modal>
  );
}
export function ExternalModal({ call, close, onSuccess, onError }) {
  const [records, setRecords] = useState(""),
    [source, setSource] = useState("DEMO-MANUAL"),
    [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const parsed = JSON.parse(records);
      if (!Array.isArray(parsed))
        throw new Error("Evidence must be a JSON array of external records.");
      await call("/api/reconciliation/external-records", {
        method: "POST",
        body: JSON.stringify({ sourceReference: source, records: parsed }),
      });
      onSuccess();
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="Import external evidence"
      subtitle="Evidence is retained separately from clearing confirmations."
      close={close}
      wide
    >
      <form className="form" onSubmit={submit}>
        <label>
          Source reference
          <input
            value={source}
            onChange={(e) => setSource(e.target.value)}
            required
            maxLength={100}
          />
        </label>
        <label>
          External records (JSON array)
          <textarea
            rows={10}
            className="code-input"
            value={records}
            onChange={(e) => setRecords(e.target.value)}
            placeholder={`[{"externalReference":"DEMO-PAY-001","amountMinor":10000,"currency":"USD","status":"SETTLED","businessDate":"${today()}"}]`}
            required
          />
        </label>
        <p className="form-note">
          Use integer minor units. Refunds use negative external amounts.
          Duplicate rows remain evidence and are classified during
          reconciliation.
        </p>
        <button className="button primary" disabled={busy}>
          {busy ? "Importing…" : "Import evidence"}
        </button>
      </form>
    </Modal>
  );
}
export function ImportRows({ call, importId }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let active = true;
    setRows(null);
    setError(null);
    call(`/api/clearing/imports/${importId}/rows?size=100`)
      .then((data) => active && setRows(data))
      .catch((failure) => active && setError(failure.message));
    return () => {
      active = false;
    };
  }, [call, importId]);
  if (error) return <p className="error-banner" role="alert">Row audit could not be loaded: {error}</p>;
  if (!rows) return <p className="muted" role="status">Loading row audit…</p>;
  return rows?.items?.length ? (
    <div>
      <h3>Row audit</h3>
      <p className="form-note">Showing {rows.items.length} of {rows.total} audited rows.</p>
      {rows.items.map((row) => (
        <div className="simple-row" key={row.id || row.rowNumber}>
          <span>
            Row {row.rowNumber} · {row.reason}
          </span>
          <Badge value={row.status} />
        </div>
      ))}
    </div>
  ) : null;
}
