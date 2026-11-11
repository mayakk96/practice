import React, { useCallback, useEffect, useRef, useState } from "react";
import { request } from "./api.js";
import { money, shortId, words, timestamp, today } from "./format.js";
import {
  Icon,
  Badge,
  Empty,
  Panel,
  Modal,
  Pager,
  TransactionTable,
  SummaryCard,
  Timeline,
  Citations,
} from "./components.jsx";
import { PaymentModal, ExternalModal, ImportRows } from "./forms.jsx";

const navigation = [
  ["overview", "Overview"],
  ["transactions", "Transactions"],
  ["settlement", "Settlement"],
  ["reconciliation", "Reconciliation"],
  ["exceptions", "Exceptions"],
  ["knowledge", "Knowledge & AI"],
];

export default function App() {
  const [view, setView] = useState("overview"),
    [credentials, setCredentials] = useState(null),
    [login, setLogin] = useState(false),
    [user, setUser] = useState("operator"),
    [password, setPassword] = useState("");
  const [data, setData] = useState({}),
    [errors, setErrors] = useState({}),
    [loading, setLoading] = useState(true),
    [revision, setRevision] = useState(0),
    [currency, setCurrency] = useState("USD"),
    [page, setPage] = useState(0);
  const [modal, setModal] = useState(null),
    [selected, setSelected] = useState(null),
    [toast, setToast] = useState(null),
    [busy, setBusy] = useState(false),
    [action, setAction] = useState(null),
    [reason, setReason] = useState(""),
    [detail, setDetail] = useState({});
  const [businessDate, setBusinessDate] = useState(today()),
    [question, setQuestion] = useState(
      "How should an analyst investigate a reconciliation amount mismatch?",
    ),
    [answer, setAnswer] = useState(null),
    [searching, setSearching] = useState(false);
  const detailRequest = useRef(0);
  const refresh = () => setRevision((v) => v + 1);
  const notify = (message, error = false) => setToast({ message, error });
  const call = useCallback(
    async (path, options) => {
      try {
        return await request(path, credentials, options);
      } catch (error) {
        if (error.status === 401) setLogin(true);
        throw error;
      }
    },
    [credentials],
  );
  const fail = (error) =>
    notify(
      `${error.message}${error.requestId ? ` · Request ${error.requestId}` : ""}`,
      true,
    );
  useEffect(() => {
    let active = true;
    setLoading(true);
    const urls = {
      transactions: `/api/transactions?page=${page}&size=10`,
      accounts: "/api/accounts?size=100",
      settlements: `/api/settlements?page=${view === "settlement" ? page : 0}&size=10`,
      runs: `/api/reconciliation/runs?page=${view === "reconciliation" ? page : 0}&size=10`,
      exceptions: `/api/exceptions?page=${view === "exceptions" ? page : 0}&size=10`,
      openExceptions: "/api/exceptions?status=OPEN&size=1",
      daily: `/api/analytics/daily?currency=${currency}&size=100`,
      health: "/health",
    };
    Promise.allSettled(
      Object.entries(urls).map(async ([key, url]) => {
        const result = await call(url);
        return [key, result];
      }),
    ).then((results) => {
      if (!active) return;
      const next = {},
        issues = {};
      results.forEach((r, i) => {
        const key = Object.keys(urls)[i];
        if (r.status === "fulfilled") next[key] = r.value[1];
        else issues[key] = r.reason.message;
      });
      setData(next);
      setErrors(issues);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [call, revision, currency, page, view]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 9000);
    return () => clearTimeout(timer);
  }, [toast]);
  function closeDetails() {
    detailRequest.current += 1;
    setSelected(null);
  }
  function navigate(key) {
    setView(key);
    setPage(0);
    closeDetails();
  }
  async function openDetail(type, row) {
    const requestNumber = ++detailRequest.current;
    setSelected({ type, row });
    setDetail({ loading: true });
    try {
      const prefix = {
        transaction: "/api/transactions",
        settlement: "/api/settlements",
        run: "/api/reconciliation/runs",
        exception: "/api/exceptions",
      }[type];
      const current = await call(`${prefix}/${row.id}`);
      let extra = {};
      if (type === "transaction") {
        const [history, ledger] = await Promise.all([
          call(`${prefix}/${row.id}/history?size=100`),
          call(`${prefix}/${row.id}/ledger?size=100`),
        ]);
        extra = { history, ledger };
      }
      if (type === "run")
        extra = {
          mismatches: await call(`${prefix}/${row.id}/mismatches?size=100`),
        };
      if (type === "exception")
        extra = { history: await call(`${prefix}/${row.id}/history?size=100`) };
      if (type === "settlement") {
        const [history, items] = await Promise.all([
          call(`${prefix}/${row.id}/history?size=100`),
          call(`${prefix}/${row.id}/items?size=100`),
        ]);
        extra = { history, items };
      }
      if (requestNumber !== detailRequest.current) return;
      setSelected({ type, row: current });
      setDetail(extra);
    } catch (error) {
      if (requestNumber !== detailRequest.current) return;
      setDetail({ error: error.message });
      fail(error);
    }
  }
  function command(title, path, body, method = "POST") {
    setReason("");
    setAction({
      title,
      path,
      body,
      method,
      idempotencyKey: crypto.randomUUID(),
    });
  }
  async function performAction(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const body =
        typeof action.body === "function" ? action.body(reason) : action.body;
      const result = await call(action.path, {
        method: action.method,
        headers: { "Idempotency-Key": action.idempotencyKey },
        body: body ? JSON.stringify(body) : undefined,
      });
      setAction(null);
      notify(`${action.title} completed.`);
      refresh();
      if (selected && result.id)
        openDetail(
          selected.type,
          action.path === "/api/clearing/records"
            ? { id: result.transactionId }
            : result,
        );
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  async function createBatch() {
    setBusy(true);
    try {
      const result = await call("/api/settlements", {
        method: "POST",
        body: JSON.stringify({ businessDate, currency, maxItems: 100 }),
      });
      setModal(null);
      notify("Settlement batch created from eligible cleared transactions.");
      refresh();
      openDetail("settlement", result);
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  async function runReconciliation() {
    setBusy(true);
    try {
      const result = await call("/api/reconciliation/runs", {
        method: "POST",
        body: JSON.stringify({ businessDate, currency }),
      });
      setModal(null);
      notify("Reconciliation snapshot completed.");
      refresh();
      openDetail("run", result);
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  async function uploadClearing(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      const body = new FormData();
      body.append("file", file);
      const result = await call("/api/clearing/import", {
        method: "POST",
        body,
      });
      setModal({ type: "importResult", result });
      notify("Clearing import processed with an audited result for every row.");
      refresh();
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }
  async function searchKnowledge(event) {
    event.preventDefault();
    setSearching(true);
    try {
      setAnswer(
        await call("/api/knowledge/search", {
          method: "POST",
          body: JSON.stringify({ query: question, topK: 3 }),
        }),
      );
    } catch (error) {
      fail(error);
    } finally {
      setSearching(false);
    }
  }
  async function explainException(row) {
    setSearching(true);
    try {
      const result = await call(`/api/assistant/exceptions/${row.id}`);
      setModal({ type: "assistant", result });
    } catch (error) {
      fail(error);
    } finally {
      setSearching(false);
    }
  }
  const transactions = data.transactions,
    latestRun = data.runs?.items?.[0],
    daily = data.daily?.items || [];
  const selectedRow = selected?.row;
  const summed = (field) =>
    data.daily
      ? daily.reduce((sum, row) => sum + BigInt(row[field] || 0), 0n)
      : null;
  const label = navigation.find(([key]) => key === view)?.[1];
  const title = {
    overview: "A clear view of every payment.",
    transactions: "Transaction register",
    settlement: "Settlement workspace",
    reconciliation: "Reconciliation control",
    exceptions: "Exception management",
    knowledge: "Operational knowledge",
  }[view];
  const description = {
    overview:
      "Monitor the lifecycle. Follow the evidence. Keep financial state consistent.",
    transactions:
      "Trace synthetic payment instructions from receipt to final settlement.",
    settlement:
      "Group cleared transactions into auditable, single-currency batches.",
    reconciliation:
      "Compare internal records with external evidence and explain every variance.",
    exceptions:
      "Investigate discrepancies and record human decisions with a complete audit trail.",
    knowledge: "Find cited runbooks and inspect read-only incident evidence.",
  }[view];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("overview");
          }}
        >
          <span className="brand-symbol">
            <Icon name="settlement" size={25} />
          </span>
          <span>
            Banking<span className="brand-light">Platform</span>
          </span>
        </a>
        <div className="workspace-label">OPERATIONS WORKSPACE</div>
        <nav aria-label="Main navigation">
          {navigation.map(([key, text]) => (
            <button
              key={key}
              aria-label={text}
              className={view === key ? "active" : ""}
              onClick={() => navigate(key)}
            >
              <Icon name={key} />
              <span>{text}</span>
              {key === "exceptions" && data.openExceptions?.total > 0 && (
                <b>{data.openExceptions.total}</b>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="security-mark">
            <Icon name="shield" />
            <span>
              Synthetic by design<small>Independent educational project</small>
            </span>
          </div>
          <p>
            No real customer data.
            <br />
            No employer affiliation.
          </p>
          <button className="connection-button" onClick={() => setLogin(true)}>
            <span className="avatar">
              {credentials?.username?.slice(0, 1).toUpperCase() || "D"}
            </span>
            <span>
              {credentials?.username || "Local workspace"}
              <small>
                {credentials ? "Session credentials" : "Demo / sign in"}
              </small>
            </span>
            <Icon name="chevron" size={16} />
          </button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            Banking operations <span>/</span> <strong>{label}</strong>
          </div>
          <div className="topbar-right">
            <span
              className={`connection-status ${data.health ? "online" : ""}`}
            >
              <i />
              {data.health ? "API connected" : "API unavailable"}
            </span>
            <button
              className="icon-button"
              title="Refresh data"
              aria-label="Refresh data"
              onClick={refresh}
            >
              <Icon name="refresh" />
            </button>
            <span className="avatar light">OP</span>
          </div>
        </header>
        <main>
          <div className="environment-banner">
            <span className="environment-label">SANDBOX</span>
            <span>
              Fictional banking environment · All accounts and transactions are
              synthetic.
            </span>
            <span className="environment-version">v1.0</span>
          </div>
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {view === "overview"
                  ? "YOUR OPERATIONS, CONNECTED"
                  : label.toUpperCase()}
              </div>
              <h1>{title}</h1>
              <p>{description}</p>
            </div>
            <div className="heading-action">
              <button
                className="button primary"
                onClick={() => setModal({ type: "payment" })}
              >
                <Icon name="plus" size={18} />
                New payment
              </button>
            </div>
          </div>
          {Object.keys(errors).length > 0 && (
            <div className="error-banner" role="alert">
              <Icon name="exceptions" />
              <div>
                <strong>Some data could not be loaded</strong>
                <p>
                  {Object.entries(errors)
                    .map(([key, error]) => `${words(key)}: ${error}`)
                    .join(" · ")}
                </p>
              </div>
              <button className="text-button" onClick={refresh}>
                Retry
              </button>
            </div>
          )}
          {loading && (
            <div className="loading-line" role="status">
              Refreshing operational data…
            </div>
          )}
          {view === "overview" && (
            <>
              <div className="section-toolbar">
                <span className="section-label">
                  <span className="live-dot" />
                  Operational overview
                </span>
                <label className="inline-select">
                  Reporting currency
                  <select
                    value={currency}
                    onChange={(e) => setCurrency(e.target.value)}
                  >
                    {["USD", "EUR", "GBP"].map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="summary-grid">
                <SummaryCard
                  label="Total transactions"
                  value={transactions?.total?.toLocaleString()}
                  description="Instructions in the transaction register"
                  icon="transactions"
                />
                <SummaryCard
                  label="Settled payment volume"
                  value={money(summed("settledMinor"), currency)}
                  description={`${currency} · ${daily.length} returned daily groups`}
                  icon="settlement"
                  accent
                />
                <SummaryCard
                  label="Open exceptions"
                  value={data.openExceptions?.total}
                  description="Discrepancies awaiting investigation"
                  icon="exceptions"
                />
              </div>
              <div className="overview-grid">
                <Panel
                  title="The payment lifecycle"
                  subtitle="Controlled transitions. An audit trail at every step."
                >
                  <div className="lifecycle">
                    {[
                      "Received",
                      "Authorized",
                      "Captured",
                      "Cleared",
                      "Settled",
                    ].map((step, i) => (
                      <div className="lifecycle-step" key={step}>
                        <span>{String(i + 1).padStart(2, "0")}</span>
                        <strong>{step}</strong>
                        {i < 4 && <Icon name="arrow" size={14} />}
                      </div>
                    ))}
                  </div>
                  <div className="lifecycle-footer">
                    <Icon name="shield" size={16} />
                    <span>
                      Database idempotency · Balanced ledger · At-least-once
                      events
                    </span>
                  </div>
                </Panel>
                <Panel
                  title="Reconciliation health"
                  action={<span className="quiet-chip">Latest snapshot</span>}
                >
                  {latestRun ? (
                    <div className="recon-health">
                      <span>
                        {latestRun.businessDate} · {latestRun.currency}
                      </span>
                      <strong
                        className={
                          BigInt(latestRun.varianceMinor) !== 0n
                            ? "warning-text"
                            : ""
                        }
                      >
                        {money(latestRun.varianceMinor, latestRun.currency)}
                      </strong>
                      <p>
                        Variance · {latestRun.recordsUnmatched} unmatched
                        references
                      </p>
                      <button
                        className="text-button"
                        onClick={() => openDetail("run", latestRun)}
                      >
                        Inspect run <Icon name="arrow" size={15} />
                      </button>
                    </div>
                  ) : (
                    <div className="compact-empty">
                      No reconciliation runs yet.
                      <button
                        className="text-button"
                        onClick={() => setModal({ type: "reconciliation" })}
                      >
                        Run reconciliation <Icon name="arrow" size={15} />
                      </button>
                    </div>
                  )}
                </Panel>
              </div>
              <Panel
                title="Transaction register"
                subtitle="Every instruction has a reference and a controlled state."
                action={
                  <button
                    className="text-button"
                    onClick={() => navigate("transactions")}
                  >
                    View all <Icon name="arrow" size={16} />
                  </button>
                }
              >
                <TransactionTable
                  data={transactions}
                  onOpen={openDetail}
                  compact
                />
              </Panel>
              <div className="reporting-note">
                <Icon name="shield" size={15} />
                <span>
                  Reporting source:{" "}
                  {data.daily?.source === "KAFKA_PROJECTION"
                    ? "Kafka event projection"
                    : data.daily?.source === "DEMO_WRITE_MODEL"
                      ? "local demo write model"
                      : "unavailable"}
                  {data.daily &&
                    ` · ${data.daily.outboxPending} pending outbox events`}
                  {data.daily &&
                    ` · ${daily.length} of ${data.daily.total} daily groups shown`}
                  . Refresh to load the latest committed data.
                </span>
              </div>
            </>
          )}
          {view === "transactions" && (
            <>
              <div className="section-toolbar">
                <span className="section-label">
                  {transactions?.total ?? "—"} recorded instructions
                </span>
                <label className="button subtle upload-label">
                  <Icon name="upload" size={17} />
                  Import clearing CSV
                  <input
                    type="file"
                    accept=".csv,text/csv"
                    onChange={uploadClearing}
                    disabled={busy}
                  />
                </label>
              </div>
              <Panel
                title="All transactions"
                subtitle="Select a transaction to inspect its status history and balanced journals."
              >
                <TransactionTable data={transactions} onOpen={openDetail} />
                <Pager
                  page={page}
                  total={transactions?.total || 0}
                  onChange={setPage}
                />
              </Panel>
              <div className="info-strip">
                <Icon name="shield" />
                <p>
                  Submissions require an idempotency key. Replaying the same key
                  and request returns the original instruction; a changed
                  request returns a conflict.
                </p>
              </div>
            </>
          )}
          {view === "settlement" && (
            <>
              <div className="section-toolbar">
                <span className="section-label">
                  Clearing → batch → confirmation
                </span>
                <button
                  className="button primary"
                  onClick={() => setModal({ type: "settlement" })}
                >
                  <Icon name="plus" size={17} />
                  Create batch
                </button>
              </div>
              <Panel
                title="Settlement batches"
                subtitle="Amounts remain separated by currency. Select a batch to progress its workflow."
              >
                {data.settlements?.items?.length ? (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Batch reference</th>
                          <th>Business date</th>
                          <th>Transactions</th>
                          <th>Net settlement</th>
                          <th>Status</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {data.settlements.items.map((batch) => (
                          <tr
                            key={batch.id}
                            onClick={() => openDetail("settlement", batch)}
                          >
                            <td className="mono">{shortId(batch.id)}</td>
                            <td>{batch.businessDate}</td>
                            <td>{batch.transactionCount}</td>
                            <td className="amount">
                              {money(batch.netSettlementMinor, batch.currency)}
                              <small>{batch.currency}</small>
                            </td>
                            <td>
                              <Badge value={batch.status} />
                            </td>
                            <td>
                              <Icon name="chevron" size={16} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <Empty
                    title="No settlement batches"
                    text="Capture and clear a payment, then create a batch for its business date and currency."
                  />
                )}
                <Pager page={page} total={data.settlements?.total || 0} onChange={setPage} />
              </Panel>
              <div className="info-strip">
                <Icon name="settlement" />
                <p>
                  OPEN → READY → SUBMITTED → CONFIRMED → RECONCILED.
                  Confirmation posts settlement journals; reconciliation
                  requires matching external evidence.
                </p>
              </div>
            </>
          )}
          {view === "reconciliation" && (
            <>
              <div className="section-toolbar">
                <span className="section-label">
                  Immutable evidence, explainable variance
                </span>
                <div className="button-row">
                  <button
                    className="button subtle"
                    onClick={() => setModal({ type: "external" })}
                  >
                    <Icon name="upload" size={17} />
                    Import evidence
                  </button>
                  <button
                    className="button primary"
                    onClick={() => setModal({ type: "reconciliation" })}
                  >
                    <Icon name="reconciliation" size={17} />
                    Run reconciliation
                  </button>
                </div>
              </div>
              <Panel
                title="Reconciliation runs"
                subtitle="Internal minus external. Each run preserves the evidence observed at that moment."
              >
                {data.runs?.items?.length ? (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Run reference</th>
                          <th>Business date</th>
                          <th>Matched / processed</th>
                          <th>Variance</th>
                          <th>Exceptions</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {data.runs.items.map((run) => (
                          <tr
                            key={run.id}
                            onClick={() => openDetail("run", run)}
                          >
                            <td className="mono">{shortId(run.id)}</td>
                            <td>{run.businessDate}</td>
                            <td>
                              {run.recordsMatched} / {run.recordsProcessed}
                            </td>
                            <td
                              className={`amount ${BigInt(run.varianceMinor) !== 0n ? "warning-text" : ""}`}
                            >
                              {money(run.varianceMinor, run.currency)}
                              <small>{run.currency}</small>
                            </td>
                            <td>
                              {run.recordsUnmatched ? (
                                <span className="badge open">
                                  {run.recordsUnmatched} unmatched
                                </span>
                              ) : (
                                <span className="badge matched">Matched</span>
                              )}
                            </td>
                            <td>
                              <Icon name="chevron" size={16} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <Empty
                    title="No reconciliation runs"
                    text="Import synthetic external evidence, then compare it with internal clearing and settlement records."
                  />
                )}
                <Pager page={page} total={data.runs?.total || 0} onChange={setPage} />
              </Panel>
            </>
          )}
          {view === "exceptions" && (
            <Panel
              title="Operational exceptions"
              subtitle="Resolution records the operator’s disposition. It does not alter financial data."
            >
              {data.exceptions?.items?.length ? (
                <div className="exception-list">
                  {data.exceptions.items.map((issue) => (
                    <button
                      className="exception-row"
                      key={issue.id}
                      onClick={() => openDetail("exception", issue)}
                    >
                      <span className="exception-symbol">
                        <Icon name="exceptions" />
                      </span>
                      <span className="exception-content">
                        <strong>{words(issue.category)} discrepancy</strong>
                        <span>{issue.reason}</span>
                        <small>
                          {issue.assignedTeam} · {shortId(issue.id)}
                        </small>
                      </span>
                      <span className="exception-meta">
                        <Badge value={issue.status} />
                        <small>{words(issue.severity)} priority</small>
                      </span>
                      <Icon name="chevron" size={16} />
                    </button>
                  ))}
                </div>
              ) : (
                <Empty
                  title="No operational exceptions"
                  text="Material reconciliation mismatches automatically create an auditable exception for investigation."
                />
              )}
              <Pager page={page} total={data.exceptions?.total || 0} onChange={setPage} />
            </Panel>
          )}
          {view === "knowledge" && (
            <div className="knowledge-layout">
              <Panel
                title="Ask the runbooks"
                subtitle="Read-only retrieval over synthetic banking policies."
              >
                <form className="knowledge-form" onSubmit={searchKnowledge}>
                  <label htmlFor="question">
                    What would you like to investigate?
                  </label>
                  <textarea
                    id="question"
                    value={question}
                    maxLength={500}
                    onChange={(e) => setQuestion(e.target.value)}
                    rows={4}
                    required
                  />
                  <div className="knowledge-form-footer">
                    <span>No customer or confidential data</span>
                    <button className="button primary" disabled={searching}>
                      <Icon name="search" size={17} />
                      {searching ? "Retrieving…" : "Search knowledge"}
                    </button>
                  </div>
                </form>
                {answer && (
                  <div className="knowledge-answer">
                    <Badge
                      value={answer.grounded ? "GROUNDED" : "NO_EVIDENCE"}
                    />
                    <h3>Retrieved guidance</h3>
                    <p className="answer-text">{answer.answer}</p>
                    <Citations citations={answer.citations} />
                  </div>
                )}
              </Panel>
              <Panel title="Permission boundaries" className="knowledge-aside">
                <span className="large-shield">
                  <Icon name="shield" size={32} />
                </span>
                <h3>Evidence supports the operator.</h3>
                <p>
                  Knowledge search and the incident assistant read bounded
                  records and cite runbooks. They cannot approve, settle,
                  reverse, or resolve a payment.
                </p>
                <div className="divider" />
                <h4>Investigating an exception?</h4>
                <p>
                  Open an exception and choose “Explain evidence” for its
                  observed condition, possible causes and suggested
                  investigation steps.
                </p>
                <button
                  className="text-button"
                  onClick={() => navigate("exceptions")}
                >
                  Open exceptions <Icon name="arrow" size={16} />
                </button>
                <small className="model-note">
                  Feature-hash lexical retrieval · Deterministic extractive
                  answers by default
                </small>
              </Panel>
            </div>
          )}
          <footer className="page-footer">
            <span>
              Enterprise Banking Transaction & Reconciliation Platform
            </span>
            <span>Independent educational work · UTC business timestamps</span>
          </footer>
        </main>
      </div>
      {toast && (
        <div
          className={`toast ${toast.error ? "error" : ""}`}
          role={toast.error ? "alert" : "status"}
        >
          <Icon name={toast.error ? "exceptions" : "reconciliation"} />
          <span>{toast.message}</span>
          <button
            className="icon-button"
            aria-label="Dismiss notification"
            onClick={() => setToast(null)}
          >
            <Icon name="close" size={16} />
          </button>
        </div>
      )}
      {login && (
        <Modal
          title="Connect to your workspace"
          subtitle="Credentials stay in this browser tab’s memory."
          close={() => setLogin(false)}
        >
          <form
            className="form"
            onSubmit={(e) => {
              e.preventDefault();
              setCredentials({ username: user, password });
              setLogin(false);
              refresh();
            }}
          >
            <label>
              Username
              <input
                name="username"
                autoComplete="username"
                value={user}
                onChange={(e) => setUser(e.target.value)}
                required
              />
            </label>
            <label>
              Password
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>
            <p className="form-note">
              Use the operator or reader credentials generated in your local
              environment. HTTP Basic is intended for the local sandbox.
            </p>
            <button className="button primary full">Connect workspace</button>
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setCredentials(null);
                setPassword("");
                setLogin(false);
                refresh();
              }}
            >
              Continue with unauthenticated local demo
            </button>
            {credentials && (
              <button
                type="button"
                className="text-button danger"
                onClick={() => {
                  setCredentials(null);
                  setPassword("");
                  setLogin(false);
                }}
              >
                Clear session credentials
              </button>
            )}
          </form>
        </Modal>
      )}
      {modal?.type === "payment" && (
        <PaymentModal
          close={() => setModal(null)}
          accounts={data.accounts?.items || []}
          currency={currency}
          call={call}
          onSuccess={(result) => {
            setModal(null);
            notify("Payment instruction received.");
            refresh();
            openDetail("transaction", result);
          }}
          onError={fail}
          onAccount={refresh}
        />
      )}
      {["settlement", "reconciliation"].includes(modal?.type) && (
        <Modal
          title={
            modal.type === "settlement"
              ? "Create settlement batch"
              : "Run reconciliation"
          }
          subtitle={
            modal.type === "settlement"
              ? "Select eligible cleared payments for one date and currency."
              : "Create an immutable comparison of internal and external records."
          }
          close={() => setModal(null)}
        >
          <form
            className="form"
            onSubmit={(e) => {
              e.preventDefault();
              modal.type === "settlement" ? createBatch() : runReconciliation();
            }}
          >
            <label>
              Business date
              <input
                type="date"
                value={businessDate}
                onChange={(e) => setBusinessDate(e.target.value)}
                required
              />
            </label>
            <label>
              Currency
              <select
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
              >
                {["USD", "EUR", "GBP"].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <p className="form-note">
              {modal.type === "settlement"
                ? "Up to 100 eligible transactions. Existing batch members cannot be included twice."
                : "Material mismatches automatically create operational exceptions. Historical runs are retained."}
            </p>
            <button className="button primary full" disabled={busy}>
              {busy
                ? "Processing…"
                : modal.type === "settlement"
                  ? "Create batch"
                  : "Run reconciliation"}
            </button>
          </form>
        </Modal>
      )}
      {modal?.type === "external" && (
        <ExternalModal
          call={call}
          close={() => setModal(null)}
          onError={fail}
          onSuccess={() => {
            setModal(null);
            refresh();
            notify("External reconciliation evidence imported.");
          }}
        />
      )}
      {modal?.type === "importResult" && (
        <Modal title="Clearing import summary" close={() => setModal(null)}>
          <div className="form">
            <dl className="detail-grid">
              {[
                "fileName",
                "rowsReceived",
                "accepted",
                "rejected",
                "duplicates",
                "duplicateFile",
              ].map((key) => (
                <div key={key}>
                  <dt>{words(key.replace(/([A-Z])/g, " $1"))}</dt>
                  <dd>{String(modal.result[key])}</dd>
                </div>
              ))}
            </dl>
            <ImportRows call={call} importId={modal.result.id} />
            <p className="form-note">
              Import ID: {modal.result.id}. Rejected records remain audited;
              correct their cause before resubmission.
            </p>
          </div>
        </Modal>
      )}
      {modal?.type === "assistant" && (
        <Modal
          title="Read-only incident evidence"
          subtitle="Hypotheses require operator investigation."
          wide
          close={() => setModal(null)}
        >
          <div className="form assistant-output">
            <Badge value="READ_ONLY" />
            <h3>Observed condition</h3>
            <p>{modal.result.observedCondition.classifications.join(" · ")}</p>
            <p>
              Variance:{" "}
              {money(
                modal.result.observedCondition.varianceMinor,
                modal.result.observedCondition.currency,
              )}
            </p>
            <h3>Possible causes</h3>
            {modal.result.possibleCauses.map((cause, i) => (
              <p key={i}>{cause}</p>
            ))}
            <h3>Investigation steps</h3>
            <ol>
              {modal.result.suggestedInvestigationSteps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
            <Citations citations={modal.result.citations} />
            <p className="form-note">
              No financial actions performed. Supporting transactions:{" "}
              {modal.result.supportingTransactionIds.join(", ") ||
                "None linked"}
              .
            </p>
          </div>
        </Modal>
      )}
      {selected && (
        <div
          className="drawer-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) closeDetails();
          }}
        >
          <aside
            className="drawer"
            role="dialog"
            aria-modal="true"
            aria-label={`${words(selected.type)} details`}
          >
            <header>
              <div>
                <span className="eyebrow">
                  {selected.type.toUpperCase()} DETAILS
                </span>
                <h2>
                  {selectedRow.externalReference || shortId(selectedRow.id)}
                </h2>
              </div>
              <button
                className="icon-button"
                aria-label="Close details"
                onClick={closeDetails}
              >
                <Icon name="close" />
              </button>
            </header>
            <div className="drawer-body">
              <div className="detail-status">
                <Badge value={selectedRow.status} />
                <span className="mono">{shortId(selectedRow.id)}</span>
              </div>
              {detail.loading && <p role="status">Loading audit evidence…</p>}
              {detail.error && (
                <div className="error-banner">{detail.error}</div>
              )}
              <dl className="detail-grid">
                {selectedRow.amountMinor != null && (
                  <div>
                    <dt>Amount</dt>
                    <dd className="detail-amount">
                      {money(selectedRow.amountMinor, selectedRow.currency)}
                    </dd>
                  </div>
                )}
                {selectedRow.netSettlementMinor != null && (
                  <div>
                    <dt>Net settlement</dt>
                    <dd>
                      {money(
                        selectedRow.netSettlementMinor,
                        selectedRow.currency,
                      )}
                    </dd>
                  </div>
                )}
                {selectedRow.businessDate && (
                  <div>
                    <dt>Business date</dt>
                    <dd>{selectedRow.businessDate}</dd>
                  </div>
                )}
                {selectedRow.currency && (
                  <div>
                    <dt>Currency</dt>
                    <dd>{selectedRow.currency}</dd>
                  </div>
                )}
                {selectedRow.transactionType && (
                  <div>
                    <dt>Instruction type</dt>
                    <dd>{words(selectedRow.transactionType)}</dd>
                  </div>
                )}
                {selectedRow.version != null && (
                  <div>
                    <dt>Version</dt>
                    <dd>{selectedRow.version}</dd>
                  </div>
                )}
                {selectedRow.createdAt && (
                  <div>
                    <dt>Created</dt>
                    <dd>{timestamp(selectedRow.createdAt)}</dd>
                  </div>
                )}
              </dl>
              {selected.type === "transaction" && (
                <>
                  <h3>Operator actions</h3>
                  <div className="button-row wrap">
                    {["RECEIVED", "VALIDATED"].includes(selectedRow.status) && (
                      <button
                        className="button primary"
                        onClick={() =>
                          command(
                            "Authorize payment",
                            `/api/transactions/${selectedRow.id}/authorize`,
                          )
                        }
                      >
                        Authorize
                      </button>
                    )}
                    {selectedRow.status === "AUTHORIZED" && (
                      <button
                        className="button primary"
                        onClick={() =>
                          command(
                            "Capture payment",
                            `/api/transactions/${selectedRow.id}/capture`,
                          )
                        }
                      >
                        Capture
                      </button>
                    )}
                    {selectedRow.status === "CAPTURED" && (
                      <button
                        className="button primary"
                        onClick={() =>
                          command("Confirm clearing", `/api/clearing/records`, {
                            transactionId: selectedRow.id,
                            networkReference: selectedRow.networkReference,
                            amountMinor: selectedRow.amountMinor,
                            currency: selectedRow.currency,
                            businessDate: selectedRow.businessDate,
                          })
                        }
                      >
                        Confirm clearing
                      </button>
                    )}
                    {["AUTHORIZED", "CAPTURED"].includes(
                      selectedRow.status,
                    ) && (
                      <button
                        className="button subtle"
                        onClick={() =>
                          command(
                            "Reverse payment",
                            `/api/transactions/${selectedRow.id}/reverse`,
                            (reason) => ({ reason }),
                          )
                        }
                      >
                        Reverse
                      </button>
                    )}
                    {selectedRow.status === "SETTLED" &&
                      selectedRow.transactionType !== "REFUND" && (
                        <button
                          className="button subtle"
                          onClick={() =>
                            command(
                              "Create full refund",
                              `/api/transactions/${selectedRow.id}/refund`,
                              (reason) => ({ reason }),
                            )
                          }
                        >
                          Full refund
                        </button>
                      )}
                  </div>
                  <h3>Status history</h3>
                  <Timeline items={detail.history?.items} />
                  <h3>Balanced journals</h3>
                  {detail.ledger?.items?.length ? (
                    detail.ledger.items.map((entry) => (
                      <div className="journal" key={entry.id}>
                        <strong>
                          {words(
                            entry.eventType ||
                              entry.financialEvent ||
                              entry.entryType ||
                              "Journal entry",
                          )}
                        </strong>
                        <div>
                          <span>
                            Debit ·{" "}
                            {entry.debitAccountId ||
                              entry.debitAccount ||
                              entry.debitAccountCode}
                          </span>
                          <b>{money(entry.amountMinor, entry.currency)}</b>
                        </div>
                        <div>
                          <span>
                            Credit ·{" "}
                            {entry.creditAccountId ||
                              entry.creditAccount ||
                              entry.creditAccountCode}
                          </span>
                          <b>{money(entry.amountMinor, entry.currency)}</b>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="muted">
                      No financial journals until capture. A journal always
                      contains equal debit and credit amounts.
                    </p>
                  )}
                </>
              )}
              {selected.type === "settlement" && (
                <>
                  <h3>Batch controls</h3>
                  <div className="button-row">
                    {{ OPEN: "ready", READY: "submit", SUBMITTED: "confirm" }[
                      selectedRow.status
                    ] && (
                      <button
                        className="button primary"
                        onClick={() =>
                          command(
                            `${words({ OPEN: "ready", READY: "submit", SUBMITTED: "confirm" }[selectedRow.status])} settlement`,
                            `/api/settlements/${selectedRow.id}/${{ OPEN: "ready", READY: "submit", SUBMITTED: "confirm" }[selectedRow.status]}`,
                            (reason) => ({
                              expectedVersion: selectedRow.version,
                              reason,
                            }),
                          )
                        }
                      >
                        {words(
                          {
                            OPEN: "ready",
                            READY: "submit",
                            SUBMITTED: "confirm",
                          }[selectedRow.status],
                        )}{" "}
                        batch
                      </button>
                    )}
                  </div>
                  <p className="form-note">
                    Reconciliation marks a confirmed batch reconciled only when
                    all of its items match.
                  </p>
                  <h3>Batch composition</h3>
                  <p>
                    {selectedRow.transactionCount} transactions · Gross debit{" "}
                    {money(selectedRow.grossDebitMinor, selectedRow.currency)} ·
                    Gross credit{" "}
                    {money(selectedRow.grossCreditMinor, selectedRow.currency)}
                  </p>
                  {detail.items?.items?.map((item) => (
                    <div className="simple-row" key={item.id}>
                      <button
                        className="text-button mono"
                        onClick={() =>
                          openDetail("transaction", { id: item.transactionId })
                        }
                      >
                        {shortId(item.transactionId)}
                      </button>
                      <span>
                        {words(item.direction)}{" "}
                        {money(item.amountMinor, selectedRow.currency)}
                      </span>
                    </div>
                  ))}
                  <h3>Batch history</h3>
                  <Timeline items={detail.history?.items} />
                </>
              )}
              {selected.type === "run" && (
                <>
                  <div className="variance-box">
                    <span>Internal minus external</span>
                    <strong>
                      {money(selectedRow.varianceMinor, selectedRow.currency)}
                    </strong>
                    <small>
                      {money(
                        selectedRow.totalInternalMinor,
                        selectedRow.currency,
                      )}{" "}
                      internal ·{" "}
                      {money(
                        selectedRow.totalExternalMinor,
                        selectedRow.currency,
                      )}{" "}
                      external
                    </small>
                  </div>
                  <div className="button-row">
                    <button
                      className="button subtle"
                      onClick={() =>
                        command(
                          "Rerun reconciliation",
                          `/api/reconciliation/runs/${selectedRow.id}/rerun`,
                        )
                      }
                    >
                      Create a new run
                    </button>
                  </div>
                  <h3>Mismatched references</h3>
                  {detail.mismatches?.items?.length ? (
                    detail.mismatches.items.map((item) => (
                      <div className="mismatch" key={item.id}>
                        <strong>{item.externalReference}</strong>
                        <p>{item.classifications.map(words).join(" · ")}</p>
                        <div>
                          <span>
                            Internal{" "}
                            {money(item.internalAmountMinor, item.currency)}
                          </span>
                          <span>
                            External{" "}
                            {money(item.externalAmountMinor, item.currency)}
                          </span>
                        </div>
                        {item.transactionId && (
                          <button
                            className="text-button"
                            onClick={() =>
                              openDetail("transaction", {
                                id: item.transactionId,
                              })
                            }
                          >
                            Inspect transaction <Icon name="arrow" size={14} />
                          </button>
                        )}
                      </div>
                    ))
                  ) : (
                    <p className="muted">No mismatches in this snapshot.</p>
                  )}
                </>
              )}
              {selected.type === "exception" && (
                <>
                  <h3>Observed discrepancy</h3>
                  <p>{selectedRow.reason}</p>
                  <p className="muted">
                    Assigned to {selectedRow.assignedTeam} ·{" "}
                    {words(selectedRow.severity)} priority
                  </p>
                  <div className="button-row wrap">
                    {selectedRow.status === "OPEN" && (
                      <button
                        className="button primary"
                        onClick={() =>
                          command(
                            "Start investigation",
                            `/api/exceptions/${selectedRow.id}`,
                            (reason) => ({
                              status: "INVESTIGATING",
                              assignedTeam: selectedRow.assignedTeam,
                              resolutionNotes: reason,
                              version: selectedRow.version,
                            }),
                            "PATCH",
                          )
                        }
                      >
                        Investigate
                      </button>
                    )}
                    {selectedRow.status === "INVESTIGATING" && (
                      <button
                        className="button primary"
                        onClick={() =>
                          command(
                            "Resolve exception",
                            `/api/exceptions/${selectedRow.id}`,
                            (reason) => ({
                              status: "RESOLVED",
                              assignedTeam: selectedRow.assignedTeam,
                              resolutionNotes: reason,
                              version: selectedRow.version,
                            }),
                            "PATCH",
                          )
                        }
                      >
                        Record resolution
                      </button>
                    )}
                    <button
                      className="button subtle"
                      onClick={() => explainException(selectedRow)}
                      disabled={searching}
                    >
                      Explain evidence
                    </button>
                  </div>
                  {selectedRow.resolutionNotes && (
                    <div className="info-strip">
                      {selectedRow.resolutionNotes}
                    </div>
                  )}
                  <h3>Audit history</h3>
                  <Timeline items={detail.history?.items} />
                  <button
                    className="text-button"
                    onClick={() =>
                      openDetail("run", { id: selectedRow.reconciliationRunId })
                    }
                  >
                    Inspect reconciliation snapshot{" "}
                    <Icon name="arrow" size={16} />
                  </button>
                </>
              )}
            </div>
          </aside>
        </div>
      )}
      {action && (
        <Modal
          title={action.title}
          subtitle="Confirm this operator action on synthetic financial records."
          close={() => !busy && setAction(null)}
        >
          <form className="form" onSubmit={performAction}>
            <p className="form-note">
              The server will validate the current state and record the
              resulting lifecycle change. Financial actions are audited.
            </p>
            {typeof action.body === "function" && (
              <label>
                Investigation notes / reason
                <textarea
                  rows={3}
                  maxLength={500}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  required
                  autoFocus
                />
              </label>
            )}
            <div className="button-row">
              <button
                type="button"
                className="button subtle"
                disabled={busy}
                onClick={() => setAction(null)}
              >
                Cancel
              </button>
              <button className="button primary" disabled={busy}>
                {busy ? "Processing…" : "Confirm action"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
