import React, { useEffect } from "react";
import { money, shortId, words, timestamp } from "./format.js";
const paths = {
  overview: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  transactions: "M4 7h16m-4-4 4 4-4 4M20 17H4m4-4-4 4 4 4",
  settlement: "M3 21h18M5 21V9m7 12V9m7 12V9M2 8l10-6 10 6H2z",
  reconciliation: "m4 12 5 5L20 6M4 4h5M4 20h5",
  exceptions: "m12 3 10 18H2L12 3zm0 6v5m0 3v.1",
  knowledge:
    "M12 5C8 2 4 3 2 4v15c4-2 7-1 10 1 3-2 6-3 10-1V4c-2-1-6-2-10 1zm0 0v15",
  plus: "M12 5v14M5 12h14",
  arrow: "M5 12h14m-5-5 5 5-5 5",
  refresh: "M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 2M5 16a8 8 0 0 0 13 2",
  close: "m6 6 12 12M6 18 18 6",
  shield: "m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6l9-4zm-4 10 3 3 5-6",
  chevron: "m9 5 7 7-7 7",
  upload: "M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6",
  search: "M21 21l-5-5m2-6a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
};
export function Icon({ name, size = 20 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name] || paths.overview} />
    </svg>
  );
}
export function Badge({ value }) {
  return (
    <span className={`badge ${String(value).toLowerCase()}`}>
      {words(value)}
    </span>
  );
}
export function Empty({
  title = "No records yet",
  text = "Records will appear here as synthetic payments move through the platform.",
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name="transactions" size={26} />
      </span>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}
export function Panel({ title, subtitle, action, children, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
export function Modal({ title, subtitle, close, children, wide = false }) {
  useEffect(() => {
    const fn = (e) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", fn);
    return () => document.removeEventListener("keydown", fn);
  }, [close]);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <section
        className={`modal ${wide ? "wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button
            className="icon-button"
            aria-label="Close dialog"
            onClick={close}
          >
            <Icon name="close" />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
export function Pager({ page, total, onChange, size = 10 }) {
  return (
    <div className="pager">
      <span>
        {total
          ? `${page * size + 1}–${Math.min((page + 1) * size, total)} of ${total} records`
          : "0 records"}
      </span>
      <div>
        <button
          className="button small subtle"
          disabled={!page}
          onClick={() => onChange(page - 1)}
        >
          Previous
        </button>
        <button
          className="button small subtle"
          disabled={(page + 1) * size >= total}
          onClick={() => onChange(page + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );
}
export function TransactionTable({ data, onOpen, compact = false }) {
  return data?.items?.length ? (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Transaction / reference</th>
            <th>Type</th>
            <th>Amount</th>
            <th>Status</th>
            {!compact && <th>Business date</th>}
            <th />
          </tr>
        </thead>
        <tbody>
          {data.items.map((tx) => (
            <tr
              key={tx.id}
              onClick={() => onOpen("transaction", tx)}
              tabIndex={0}
              onKeyDown={(e) => e.key === "Enter" && onOpen("transaction", tx)}
            >
              <td>
                <strong>{tx.externalReference}</strong>
                <span className="mono secondary">{shortId(tx.id)}</span>
              </td>
              <td>{words(tx.transactionType)}</td>
              <td className="amount">
                {money(tx.amountMinor, tx.currency)}
                <small>{tx.currency}</small>
              </td>
              <td>
                <Badge value={tx.status} />
              </td>
              {!compact && <td>{tx.businessDate}</td>}
              <td>
                <Icon name="chevron" size={16} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty />
  );
}
export function SummaryCard({
  label,
  value,
  description,
  icon,
  accent = false,
}) {
  return (
    <div className={`summary-card ${accent ? "accent" : ""}`}>
      <div className="metric-label">
        {label}
        <span>
          <Icon name={icon} />
        </span>
      </div>
      <strong className="metric-value">{value ?? "—"}</strong>
      <div className="metric-description">{description}</div>
    </div>
  );
}
export function Timeline({ items }) {
  return items?.length ? (
    <ol className="timeline">
      {items.map((item) => (
        <li key={item.id}>
          <span className="timeline-dot" />
          <div>
            <strong>{words(item.newStatus)}</strong>
            <small>
              {timestamp(item.changedAt || item.createdAt)} ·{" "}
              {item.actor || "system"}
            </small>
            <p>{item.reason || item.notes || "State transition recorded"}</p>
          </div>
        </li>
      ))}
    </ol>
  ) : (
    <p className="muted">No history available.</p>
  );
}
export function Citations({ citations = [] }) {
  return (
    <div className="citations">
      <h4>Supporting runbooks</h4>
      {citations.length ? (
        citations.map((item) => (
          <details key={item.chunkId}>
            <summary>
              <Icon name="knowledge" size={16} />
              <span>{item.source}</span>
              <small>{item.chunkId}</small>
            </summary>
            <p>{item.excerpt}</p>
          </details>
        ))
      ) : (
        <p className="muted">No relevant runbook evidence was retrieved.</p>
      )}
    </div>
  );
}
