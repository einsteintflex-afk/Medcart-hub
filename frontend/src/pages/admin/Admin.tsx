import { useState } from "react";
import { api, ghs } from "../../api";
import { Badge, Err, Section, Stat, Table, d, dt, useAction, useFetch } from "../../ui";
import { FileLink } from "../../files";

export function Overview() {
  const { data: ops } = useFetch<any>("/admin/reports/operational"); const { data: fin } = useFetch<any>("/admin/reports/financial"); const act = useAction(); const [r, setR] = useState<any>(null);
  return (<><h1>Administration</h1>
    <div className="grid">{ops && <><Stat label="Users" value={ops.users} /><Stat label="Consultations" value={ops.consultations} /><Stat label="Providers awaiting verification" value={ops.providers_pending} warn={ops.providers_pending > 0} /><Stat label="Open complaints" value={ops.open_complaints} warn={ops.open_complaints > 0} /></>}
      {fin && <><Stat label="Platform commission" value={ghs(fin.platform_commission_pesewas)} /><Stat label="Provider payouts due" value={ghs(fin.provider_payouts_pending_pesewas)} /></>}</div>
    <Section title="Scheduled jobs"><div className="card"><button onClick={() => act.run(async () => setR(await api("/admin/jobs/send-reminders", { method: "POST" })))}>Run reminders now</button> {r && <code>{JSON.stringify(r)}</code>}<Err msg={act.err} />
      <p className="muted">In production run this every 15 minutes from a scheduler.</p></div></Section></>);
}

export function Verification() {
  const { data, reload } = useFetch<any[]>("/admin/providers/pending"); const { data: all, reload: r2 } = useFetch<any[]>("/admin/providers"); const act = useAction(() => { reload(); r2(); });
  return (<><h1>Professional verification</h1><Err msg={act.err} />
    <Section title={`Pending (${data?.length ?? 0})`}>{data?.map(p => <div className="card" key={p.id} style={{ marginBottom: 8 }}><b>{p.name}</b> <Badge>{p.role}</Badge> {p.email}
      <ul>{p.credentials.map((c: any) => <li key={c.id}>{c.kind}: {c.issuer} #{c.number} {c.document_key ? <FileLink fileKey={c.document_key} label="View document" /> : <Badge warn>no document</Badge>}</li>)}</ul>
      <small className="muted">Check each number against the issuing council's public register and the person's ID before approving.</small>
      <div className="row"><button className="primary" onClick={() => act.run(() => api(`/admin/providers/${p.id}/review`, { body: { approve: true, can_prescribe: false } }))}>Approve</button>
        {p.role === "doctor" && <button onClick={() => act.run(() => api(`/admin/providers/${p.id}/review`, { body: { approve: true, can_prescribe: true } }))}>Approve + allow prescribing</button>}
        <button className="danger" onClick={() => { const n = prompt("Reason for rejection (sent to applicant)"); if (n) act.run(() => api(`/admin/providers/${p.id}/review`, { body: { approve: false, note: n } })); }}>Reject</button></div></div>)}
      {!data?.length && <p className="muted">Queue is clear.</p>}</Section>
    <Section title="All professionals"><Table rows={all} cols={[{ head: "Name", cell: r => r.name }, { head: "Role", cell: r => r.role }, { head: "Status", cell: r => <Badge warn={r.status !== "approved"}>{r.status}</Badge> }, { head: "Prescribes", cell: r => r.can_prescribe ? "yes" : "—" }, { head: "Credits", cell: r => r.credit_units },
      { head: "", cell: r => r.status === "approved" && <button className="danger" onClick={() => { const n = prompt("Reason for suspension"); if (n) act.run(() => api(`/admin/providers/${r.id}/suspend?reason=${encodeURIComponent(n)}`, { method: "POST" })); }}>Suspend</button> }]} /></Section></>);
}

export function Users() {
  const [q, setQ] = useState(""); const [role, setRole] = useState(""); const qs = new URLSearchParams(); if (q) qs.set("q", q); if (role) qs.set("role", role);
  const { data, reload } = useFetch<any[]>(`/admin/users?${qs}`, [qs.toString()]); const act = useAction(reload);
  return (<><h1>Users</h1><div className="grid"><input aria-label="Search" placeholder="Search name or email" value={q} onChange={e => setQ(e.target.value)} />
    <select aria-label="Role" value={role} onChange={e => setRole(e.target.value)}><option value="">All roles</option>{["patient", "doctor", "pharmacist", "nurse", "lab", "facility_admin", "admin"].map(r => <option key={r}>{r}</option>)}</select></div><Err msg={act.err} />
    <Table rows={data} cols={[{ head: "ID", cell: r => r.id }, { head: "Name", cell: r => r.name }, { head: "Email", cell: r => r.email }, { head: "Role", cell: r => r.role }, { head: "Joined", cell: r => d(r.created_at) },
      { head: "Status", cell: r => <Badge warn={!r.active}>{r.active ? "active" : "disabled"}</Badge> }, { head: "", cell: r => <button onClick={() => act.run(() => api(`/admin/users/${r.id}/active?active=${!r.active}`, { method: "PUT" }))}>{r.active ? "Disable" : "Enable"}</button> }]} /></>);
}

export function Moderation() {
  const { data, reload } = useFetch<any[]>("/admin/contributions/pending"); const { data: all, reload: r2 } = useFetch<any[]>("/admin/contributions"); const act = useAction(() => { reload(); r2(); }); const [res, setRes] = useState("");
  return (<><h1>Content moderation</h1><Err msg={act.err} />{res && <p role="status">{res}</p>}
    <Section title={`Awaiting review (${data?.length ?? 0})`}>{data?.map(c => <div className="card" key={c.id} style={{ marginBottom: 8 }}><b>{c.title}</b> <Badge>{c.kind}</Badge> by #{c.author_id}<p style={{ whiteSpace: "pre-wrap" }}>{c.body}</p>
      <div className="row"><button className="primary" onClick={() => act.run(async () => { const r = await api(`/admin/contributions/${c.id}/moderate`, { body: { approve: true } }); setRes(r.credited ? "Approved and 0.8 credit awarded." : `Approved. ${r.credit_note ?? ""}`); })}>Approve & publish</button>
        <button onClick={() => { const n = prompt("Edit title", c.title); if (n) act.run(() => api(`/admin/contributions/${c.id}`, { method: "PATCH", body: { title: n } })); }}>Edit title</button>
        <button className="danger" onClick={() => { const n = prompt("Reason (sent to author)"); if (n) act.run(() => api(`/admin/contributions/${c.id}/moderate`, { body: { approve: false, note: n } })); }}>Reject</button></div></div>)}
      {!data?.length && <p className="muted">Nothing to review.</p>}</Section>
    <Section title="All content"><Table rows={all} cols={[{ head: "Title", cell: r => r.title }, { head: "Author", cell: r => `#${r.author_id}` }, { head: "Status", cell: r => <Badge warn={r.status === "rejected" || r.status === "withdrawn"}>{r.status}</Badge> }, { head: "Published", cell: r => d(r.published_at) },
      { head: "", cell: r => r.status === "approved" && <button className="danger" onClick={() => { const n = prompt("Reason for withdrawal (credit will be reversed)"); if (n) act.run(() => api(`/admin/contributions/${r.id}/withdraw?reason=${encodeURIComponent(n)}`, { method: "POST" })); }}>Withdraw</button> }]} /></Section></>);
}

export function Transactions() {
  const [st, setSt] = useState(""); const { data, reload } = useFetch<any[]>(`/admin/payments${st ? `?status=${st}` : ""}`, [st]); const { data: setl, reload: r2 } = useFetch<any[]>("/admin/settlements");
  const act = useAction(() => { reload(); r2(); }); const [rec, setRec] = useState<any>(null);
  return (<><h1>Transactions</h1><Err msg={act.err} />
    <div className="row"><select aria-label="Status" style={{ width: "auto" }} value={st} onChange={e => setSt(e.target.value)}><option value="">All</option>{["pending", "succeeded", "failed", "refunded"].map(s => <option key={s}>{s}</option>)}</select>
      <button onClick={() => act.run(async () => setRec(await api("/payments/admin/reconciliation")))}>Run reconciliation</button></div>
    {rec && <div className="card"><b>Succeeded gross:</b> {ghs(rec.succeeded_gross_pesewas)} · <b>Discrepancies:</b> {rec.discrepancies.length}{rec.discrepancies.map((x: any, i: number) => <div key={i} className="error">{x.reference}: {x.issue}</div>)}</div>}
    <Table rows={data} cols={[{ head: "Date", cell: r => dt(r.created_at) }, { head: "Ref", cell: r => <code>{r.reference}</code> }, { head: "User", cell: r => `#${r.user_id}` }, { head: "For", cell: r => r.purpose }, { head: "Amount", cell: r => ghs(r.amount_pesewas) },
      { head: "Status", cell: r => <Badge warn={r.status === "failed"}>{r.status}</Badge> }, { head: "", cell: r => r.status === "succeeded" && <button className="danger" onClick={() => { const n = prompt("Refund reason"); if (n) act.run(() => api(`/payments/admin/${r.id}/refund?reason=${encodeURIComponent(n)}`, { method: "POST" })); }}>Refund</button> }]} />
    <Section title="Provider settlements"><Table rows={setl} cols={[{ head: "Provider", cell: r => `#${r.provider_id}` }, { head: "Gross", cell: r => ghs(r.gross) }, { head: "Commission", cell: r => ghs(r.commission) }, { head: "Net", cell: r => ghs(r.net) }, { head: "Status", cell: r => <Badge>{r.status}</Badge> },
      { head: "", cell: r => r.status === "pending" && <button onClick={() => act.run(() => api(`/admin/settlements/${r.id}/mark-paid`, { method: "POST" }))}>Mark paid</button> }]} />
      <p className="muted">Mark as paid after you transfer the funds to the provider.</p></Section></>);
}

export function Subscriptions() {
  const { data, reload } = useFetch<any[]>("/admin/subscriptions"); const [f, setF] = useState({ user_id: "", plan: "patient", days: "30", reason: "" }); const act = useAction(reload);
  return (<><h1>Subscriptions</h1><Section title="Grant complimentary access"><div className="card row"><input aria-label="User ID" placeholder="User ID" style={{ width: 110 }} value={f.user_id} onChange={e => setF({ ...f, user_id: e.target.value })} />
    <select aria-label="Plan" style={{ width: "auto" }} value={f.plan} onChange={e => setF({ ...f, plan: e.target.value })}><option>patient</option><option>professional</option></select>
    <input aria-label="Days" style={{ width: 80 }} value={f.days} onChange={e => setF({ ...f, days: e.target.value })} /><input aria-label="Reason" placeholder="Reason (audited)" style={{ flex: 1 }} value={f.reason} onChange={e => setF({ ...f, reason: e.target.value })} />
    <button className="primary" disabled={!f.user_id || !f.reason} onClick={() => act.run(() => api("/admin/subscriptions/grant", { body: { user_id: +f.user_id, plan: f.plan, days: +f.days, reason: f.reason } }))}>Grant</button></div><Err msg={act.err} /></Section>
    <Table rows={data} cols={[{ head: "User", cell: r => `#${r.user_id}` }, { head: "Plan", cell: r => r.plan }, { head: "Source", cell: r => r.source }, { head: "Starts", cell: r => d(r.starts_at) }, { head: "Expires", cell: r => d(r.expires_at) }, { head: "", cell: r => <Badge warn={!r.active}>{r.active ? "active" : "expired"}</Badge> }]} /></>);
}

export const Consultations = () => { const { data } = useFetch<any[]>("/admin/consultations"); return <><h1>Consultations</h1><Table rows={data} cols={[{ head: "#", cell: r => r.id }, { head: "Date", cell: r => dt(r.created_at) }, { head: "Patient", cell: r => `#${r.patient_id}` }, { head: "Provider", cell: r => `#${r.provider_id} (${r.role})` }, { head: "Channel", cell: r => r.channel }, { head: "Fee", cell: r => ghs(r.fee_pesewas) }, { head: "Status", cell: r => <Badge>{r.status}</Badge> }]} /></>; };
export const Appointments = () => { const { data } = useFetch<any[]>("/admin/appointments"); return <><h1>Appointments</h1><Table rows={data} cols={[{ head: "When", cell: r => dt(r.starts_at) }, { head: "Patient", cell: r => `#${r.patient_id}` }, { head: "Provider/Facility", cell: r => r.provider_id ? `provider #${r.provider_id}` : `facility #${r.facility_id}` }, { head: "Status", cell: r => <Badge>{r.status}</Badge> }]} /></>; };
export const Labs = () => { const { data } = useFetch<any[]>("/admin/labs"); return <><h1>Laboratory requests</h1><Table rows={data} cols={[{ head: "#", cell: r => r.id }, { head: "Patient", cell: r => `#${r.patient_id}` }, { head: "Tests", cell: r => r.tests.join(", ") }, { head: "Status", cell: r => <Badge>{r.status}</Badge> }, { head: "Requested", cell: r => dt(r.created_at) }]} /></>; };

export function Facilities() {
  const { data, reload } = useFetch<any[]>("/admin/facilities"); const act = useAction(reload);
  const [f, setF] = useState({ name: "", kind: "hospital", address: "", city: "", phone: "", latitude: "", longitude: "", has_emergency: false });
  return (<><h1>Healthcare facilities</h1><Err msg={act.err} />
    <Table rows={data} cols={[{ head: "Name", cell: r => r.name }, { head: "Type", cell: r => r.kind }, { head: "City", cell: r => r.city ?? "—" }, { head: "Emergency", cell: r => r.has_emergency ? "✔" : "—" }, { head: "Listing", cell: r => <Badge warn={!r.verified}>{r.verified ? "verified" : "pending"}</Badge> },
      { head: "", cell: r => <button onClick={() => act.run(() => api(`/admin/facilities/${r.id}/verified?verified=${!r.verified}`, { method: "PUT" }))}>{r.verified ? "Unlist" : "Verify & list"}</button> }]} />
    <Section title="Add facility"><div className="card"><div className="grid">{(["name", "address", "city", "phone", "latitude", "longitude"] as const).map(k => <div key={k}><label htmlFor={k}>{k}</label><input id={k} value={(f as any)[k]} onChange={e => setF({ ...f, [k]: e.target.value })} /></div>)}
      <div><label htmlFor="k">type</label><select id="k" value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}>{["hospital", "clinic", "pharmacy", "laboratory", "diagnostic", "specialist"].map(k => <option key={k}>{k}</option>)}</select></div></div>
      <label><input type="checkbox" style={{ width: "auto" }} checked={f.has_emergency} onChange={e => setF({ ...f, has_emergency: e.target.checked })} /> Emergency services</label><br />
      <button className="primary" disabled={!f.name || !f.address} onClick={() => act.run(() => api("/admin/facilities", { body: { ...f, latitude: f.latitude ? +f.latitude : null, longitude: f.longitude ? +f.longitude : null } }))}>Add</button></div></Section></>);
}

export function Credits() {
  const [pid, setPid] = useState(""); const { data, reload } = useFetch<any[]>(`/admin/credits/ledger${pid ? `?provider_id=${pid}` : ""}`, [pid]); const act = useAction(reload); const [adj, setAdj] = useState({ id: "", units: "", reason: "" });
  return (<><h1>Contribution credits</h1><p className="muted">Append-only ledger. Corrections are made by reversal or adjustment entries, each with a reason and an audit-log record.</p>
    <Section title="Adjust a balance"><div className="card row"><input aria-label="Provider ID" placeholder="Provider ID" style={{ width: 120 }} value={adj.id} onChange={e => setAdj({ ...adj, id: e.target.value })} />
      <input aria-label="Units" placeholder="Units (e.g. -0.8)" style={{ width: 150 }} value={adj.units} onChange={e => setAdj({ ...adj, units: e.target.value })} /><input aria-label="Reason" placeholder="Reason (required)" style={{ flex: 1 }} value={adj.reason} onChange={e => setAdj({ ...adj, reason: e.target.value })} />
      <button className="primary" disabled={!adj.id || !adj.units || !adj.reason.trim()} onClick={() => act.run(() => api(`/admin/credits/${adj.id}/adjust`, { body: { units_tenths: Math.round(parseFloat(adj.units) * 10), reason: adj.reason } }))}>Apply</button></div><Err msg={act.err} /></Section>
    <div className="row"><label htmlFor="p">Filter by provider ID</label><input id="p" style={{ width: 120 }} value={pid} onChange={e => setPid(e.target.value)} /></div>
    <Table rows={data} cols={[{ head: "Date", cell: r => dt(r.at) }, { head: "Provider", cell: r => `#${r.provider_id}` }, { head: "Type", cell: r => r.type }, { head: "Units", cell: r => <b style={{ color: r.units < 0 ? "var(--danger)" : "var(--ok)" }}>{r.units}</b> }, { head: "Contribution", cell: r => r.contribution_id ? `#${r.contribution_id}` : "—" }, { head: "By", cell: r => r.actor_id ? `#${r.actor_id}` : "system" }, { head: "Reason", cell: r => r.reason ?? "—" }]} /></>);
}

export function Complaints() {
  const { data, reload } = useFetch<any[]>("/admin/complaints"); const act = useAction(reload);
  return (<><h1>Complaints</h1><Err msg={act.err} /><Table rows={data} cols={[{ head: "Date", cell: r => dt(r.created_at) }, { head: "From", cell: r => `#${r.user_id}` }, { head: "About", cell: r => r.about_user_id ? `#${r.about_user_id}` : "—" }, { head: "Complaint", cell: r => r.body }, { head: "Status", cell: r => <Badge warn={r.status === "open"}>{r.status}</Badge> },
    { head: "", cell: r => r.status === "open" && <button className="primary" onClick={() => { const n = prompt("Resolution note"); if (n) act.run(() => api(`/admin/complaints/${r.id}/resolve?note=${encodeURIComponent(n)}`, { method: "POST" })); }}>Resolve</button> }]} /></>);
}

export function Interpreters() {
  const { data, reload } = useFetch<any[]>("/admin/interpreter-requests"); const act = useAction(reload);
  return (<><h1>Human interpreter requests</h1><Err msg={act.err} /><Table rows={data} cols={[{ head: "Date", cell: r => dt(r.created_at) }, { head: "Consultation", cell: r => `#${r.consultation_id}` }, { head: "Language", cell: r => r.language }, { head: "Reason", cell: r => r.reason ?? "—" }, { head: "Status", cell: r => <Badge warn={r.status === "open"}>{r.status}</Badge> },
    { head: "", cell: r => r.status === "open" && <button className="primary" onClick={() => { const n = prompt("Message to the requester (e.g. interpreter name/time)"); if (n !== null) act.run(() => api(`/admin/interpreter-requests/${r.id}/close?note=${encodeURIComponent(n)}`, { method: "POST" })); }}>Mark handled</button> }]} /></>);
}

export function Languages() {
  const { data, reload } = useFetch<any[]>("/admin/languages"); const act = useAction(reload);
  const save = (l: any, patch: any) => act.run(() => api("/admin/languages", { method: "PUT", body: { code: l.code, name: l.name, enabled: l.enabled, stt_supported: l.stt, tts_supported: l.tts, human_interpreter_available: l.human_interpreter, ...patch } }));
  return (<><h1>Languages & translation support</h1><p className="muted">Only mark speech or interpreter support as available once a vendor/interpreter has been validated for that language.</p><Err msg={act.err} />
    <Table rows={data} cols={[{ head: "Language", cell: r => `${r.name} (${r.code})` }, { head: "Enabled", cell: r => <input type="checkbox" style={{ width: "auto" }} aria-label="Enabled" checked={r.enabled} onChange={e => save(r, { enabled: e.target.checked })} /> },
      { head: "STT", cell: r => <input type="checkbox" style={{ width: "auto" }} aria-label="Speech to text" checked={r.stt} onChange={e => save(r, { stt_supported: e.target.checked })} /> }, { head: "TTS", cell: r => <input type="checkbox" style={{ width: "auto" }} aria-label="Text to speech" checked={r.tts} onChange={e => save(r, { tts_supported: e.target.checked })} /> },
      { head: "Human interpreter", cell: r => <input type="checkbox" style={{ width: "auto" }} aria-label="Human interpreter" checked={r.human_interpreter} onChange={e => save(r, { human_interpreter_available: e.target.checked })} /> }]} /></>);
}

function Bars({ data, fmt }: { data: Record<string, number>; fmt: (n: number) => string }) {
  const e = Object.entries(data).sort(); const max = Math.max(1, ...e.map(([, v]) => v));
  if (!e.length) return <p className="muted">No data in this period.</p>;
  return <div className="card">{e.map(([k, v]) => <div key={k} className="row" style={{ marginBottom: 4 }}><span style={{ width: 90 }}>{k.slice(5)}</span><div style={{ background: "var(--teal)", height: 14, borderRadius: 4, width: `${(v / max) * 60}%`, minWidth: 4 }} /><span>{fmt(v)}</span></div>)}</div>;
}
export function Reports() {
  const [days, setDays] = useState(30); const { data: t } = useFetch<any>(`/admin/reports/trends?days=${days}`, [days]); const { data: fin } = useFetch<any>("/admin/reports/financial");
  return (<><h1>Reports</h1><select aria-label="Period" style={{ width: "auto" }} value={days} onChange={e => setDays(+e.target.value)}><option value={7}>7 days</option><option value={30}>30 days</option><option value={90}>90 days</option></select>
    {fin && <Section title="Revenue by purpose (all time)"><div className="grid">{Object.entries(fin.revenue_by_purpose_pesewas).map(([k, v]: any) => <Stat key={k} label={k.replace("_", " ")} value={ghs(v)} />)}</div></Section>}
    <Section title="Revenue per day"><Bars data={t?.revenue_by_day_pesewas ?? {}} fmt={ghs} /></Section><Section title="Sign-ups per day"><Bars data={t?.signups_by_day ?? {}} fmt={String} /></Section></>);
}

export function Audit() {
  const [a, setA] = useState(""); const { data } = useFetch<any[]>(`/admin/audit-logs${a ? `?action=${a}` : ""}`, [a]);
  return (<><h1>Audit log</h1><input aria-label="Filter by action" placeholder="Filter by action, e.g. payment.refund" value={a} onChange={e => setA(e.target.value)} />
    <Table rows={data} cols={[{ head: "When", cell: r => dt(r.at) }, { head: "Actor", cell: r => r.actor_id ? `#${r.actor_id}` : "system" }, { head: "Action", cell: r => <code>{r.action}</code> }, { head: "Entity", cell: r => `${r.entity} ${r.entity_id ?? ""}` }, { head: "Patient", cell: r => r.patient_id ? `#${r.patient_id}` : "—" }, { head: "Detail", cell: r => <small>{JSON.stringify(r.detail)}</small> }]} /></>);
}

export function Settings() {
  const { data } = useFetch<any>("/admin/settings");
  if (!data) return <p>Loading…</p>;
  return (<><h1>Platform settings</h1><p className="muted">Read-only view of effective, non-secret settings. Change them via deployment configuration (MEDCART_* variables); secrets are never shown here.</p>
    <div className="card"><table><tbody>{Object.entries(data).map(([k, v]) => <tr key={k}><td>{k}</td><td>{typeof v === "object" ? JSON.stringify(v) : String(v)}</td></tr>)}</tbody></table></div></>);
}
