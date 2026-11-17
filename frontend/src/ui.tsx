import { ReactNode, useCallback, useEffect, useState } from "react";
import { api } from "./api";

export function useFetch<T = any>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null); const [error, setError] = useState(""); const [loading, setLoading] = useState(!!path);
  const reload = useCallback(() => { if (!path) return; setLoading(true); api<T>(path).then(d => { setData(d); setError(""); }).catch(e => setError(e.message)).finally(() => setLoading(false)); }, [path]);
  useEffect(reload, [reload, ...deps]);
  return { data, error, loading, reload, setData };
}

export const Stat = ({ label, value, warn }: { label: string; value: ReactNode; warn?: boolean }) =>
  <div className="card"><div style={{ fontSize: ".85rem", opacity: .7 }}>{label}</div><div style={{ fontSize: "1.6rem", fontWeight: 700, color: warn ? "var(--danger)" : "var(--navy)" }}>{value}</div></div>;

export const Badge = ({ children, warn }: { children: ReactNode; warn?: boolean }) => <span className={`badge ${warn ? "warn" : ""}`}>{children}</span>;
export const Section = ({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) =>
  <section style={{ marginBottom: 20 }}><div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><h2>{title}</h2>{action}</div>{children}</section>;
export const Err = ({ msg }: { msg: string }) => msg ? <p className="error" role="alert">{msg}</p> : null;
export const Empty = ({ text = "Nothing here yet." }) => <p style={{ opacity: .7 }}>{text}</p>;
export const dt = (v?: string | null) => v ? new Date(v + (v.endsWith("Z") ? "" : "Z")).toLocaleString() : "—";
export const d = (v?: string | null) => v ? new Date(v + (v.endsWith("Z") ? "" : "Z")).toLocaleDateString() : "—";

export type Col<T> = { head: string; cell: (r: T) => ReactNode };
export function Table<T extends { id?: number | string } = any>({ rows, cols, empty }: { rows: T[] | null; cols: Col<T>[]; empty?: string }) {
  if (!rows) return <p>Loading…</p>;
  if (!rows.length) return <Empty text={empty} />;
  return <div className="card" style={{ overflowX: "auto" }}><table><thead><tr>{cols.map(c => <th key={c.head}>{c.head}</th>)}</tr></thead>
    <tbody>{rows.map((r, i) => <tr key={r.id ?? i}>{cols.map(c => <td key={c.head}>{c.cell(r)}</td>)}</tr>)}</tbody></table></div>;
}

/** Run an action, surface errors, then reload. */
export function useAction(after?: () => void) {
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>) => { setErr(""); setBusy(true); try { await fn(); after?.(); } catch (e: any) { setErr(e.message); } setBusy(false); };
  return { run, err, busy };
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label style={{ display: "block" }}>{label}{children}</label>;
}
