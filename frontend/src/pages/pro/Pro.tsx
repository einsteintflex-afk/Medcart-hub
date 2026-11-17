import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ghs, startPayment } from "../../api";
import type { Me } from "../../App";
import { Badge, Err, Section, Stat, Table, d, dt, useAction, useFetch } from "../../ui";
import { FileLink, FileUpload } from "../../files";

export function Overview({ me }: { me: Me }) {
  const ver = me.verification_status;
  const { data: o, error } = useFetch<any>(ver === "approved" ? "/pro/overview" : null);
  if (ver !== "approved") return (<><h1>{me.full_name}</h1><div className="card" role="status"><Badge warn>{ver ?? "pending"}</Badge>
    <p>Your account is <b>{ver ?? "pending"}</b>. You can use the platform fully once an administrator has verified your identity, licence and registration number.</p>
    <Link className="primary" to="/pro/profile">Review my credentials</Link></div></>);
  if (!o) return <p>{error || "Loading…"}</p>;
  return (<>
    <h1>Welcome, {me.full_name}</h1>
    {!o.subscription_active && <div className="card banner">Your professional subscription is inactive. <Link to="/pro/earnings">Renew</Link> or earn a free month with <Link to="/pro/contributions">contribution credits</Link>.</div>}
    <div className="grid" style={{ marginTop: 12 }}>
      <Stat label="Pending requests" value={o.pending_requests} warn={o.pending_requests > 0} /><Stat label="Active consultations" value={o.active_consultations} /><Stat label="Completed" value={o.completed} />
      <Stat label="Appointments (next 24h)" value={o.todays_appointments} /><Stat label="Earnings pending" value={ghs(o.pending_earnings_pesewas)} /><Stat label="Earnings paid" value={ghs(o.paid_earnings_pesewas)} />
      <Stat label="Credit units" value={`${o.credit_balance_units} / 120`} /><Stat label="Unread notifications" value={o.unread_notifications} />
      {o.lab_queue !== null && <Stat label="Lab requests open" value={o.lab_queue} />}</div>
  </>);
}

export function Consultations() {
  const { data, reload } = useFetch<any[]>("/consultations"); const act = useAction(reload);
  const decide = (id: number, accept: boolean) => act.run(() => api(`/consultations/${id}/decision`, { body: { accept } }));
  const pending = data?.filter(c => c.status === "requested") ?? [];
  return (<>
    <h1>Consultations</h1><Err msg={act.err} />
    <Section title={`Requests (${pending.length})`}>{pending.map(c => <div className="card row" key={c.id}>#{c.id} · {c.channel} {c.urgent && <Badge warn>urgent</Badge>} · patient #{c.patient_id}
      <button className="primary" onClick={() => decide(c.id, true)}>Accept</button><button onClick={() => decide(c.id, false)}>Decline</button><Link to={`/pro/consultations/${c.id}`}>View</Link></div>)}
      {!pending.length && <p className="muted">No new requests. Unpaid requests are not shown until payment is confirmed.</p>}</Section>
    <Section title="All"><Table rows={data} cols={[{ head: "#", cell: r => <Link to={`/pro/consultations/${r.id}`}>#{r.id}</Link> }, { head: "Channel", cell: r => r.channel }, { head: "Status", cell: r => <Badge>{r.status}</Badge> }, { head: "Patient", cell: r => `#${r.patient_id}` }]} /></Section>
  </>);
}

export function ProAppointments() {
  const { data, reload } = useFetch<any[]>("/appointments"); const act = useAction(reload);
  const upd = (id: number, action: string) => act.run(() => api(`/appointments/${id}`, { method: "PATCH", body: { action } }));
  return (<><h1>Appointments</h1><Err msg={act.err} /><Table rows={data} cols={[{ head: "When", cell: r => dt(r.starts_at) }, { head: "Patient reason", cell: r => r.reason ?? "—" }, { head: "Status", cell: r => <Badge warn={r.status === "cancelled"}>{r.status}</Badge> },
    { head: "", cell: r => r.status === "pending" ? <><button className="primary" onClick={() => upd(r.id, "confirm")}>Confirm</button> <button onClick={() => upd(r.id, "cancel")}>Decline</button></> : r.status === "confirmed" ? <button onClick={() => upd(r.id, "cancel")}>Cancel</button> : null }]} /></>);
}

export function Patients({ me }: { me: Me }) {
  const { data: pts } = useFetch<any[]>("/pro/patients"); const [sel, setSel] = useState<number | null>(null);
  const { data: sum, error } = useFetch<any>(sel ? `/patients/${sel}/summary` : null, [sel]); const { data: recs } = useFetch<any[]>(sel ? `/patients/${sel}/records` : null, [sel]);
  const { data: vit } = useFetch<any[]>(sel ? `/patients/${sel}/vitals?days=30` : null, [sel]); const { data: meds } = useFetch<any[]>(sel ? `/patients/${sel}/medications` : null, [sel]); const [tests, setTests] = useState(""); const act = useAction();
  return (<>
    <h1>Patients</h1>
    <p className="muted">You can only open records a patient has shared with you. Every view is logged and visible to the patient.</p>
    <div className="row">{pts?.map(p => <button key={p.id} className={sel === p.id ? "primary" : ""} onClick={() => setSel(p.id)}>{p.name}</button>)}{pts?.length === 0 && <span className="muted">No patients yet.</span>}</div>
    {sel && <>{error ? <Err msg={error} /> : sum && <Section title={sum.name}><div className="card"><p>Sex: {sum.sex ?? "—"} · DOB: {d(sum.date_of_birth)}</p>
      <p><b>Allergies:</b> {sum.allergies?.join(", ") || "none recorded"}</p><p><b>Current medications:</b> {sum.current_medications?.join(", ") || "none recorded"}</p><p><b>History:</b> {sum.medical_history ?? "—"}</p></div></Section>}
      <Section title="Shared records"><Table rows={recs} cols={[{ head: "Date", cell: r => d(r.recorded_on) }, { head: "Type", cell: r => <Badge>{r.category}</Badge> }, { head: "Title", cell: r => <><b>{r.title}</b><div className="muted">{r.body}</div>{r.document_key && <FileLink fileKey={r.document_key} label="Open document" />}</> }]} /></Section>
      <Section title="Medication history"><Table rows={meds} cols={[{ head: "Medicine", cell: r => <b>{r.name}</b> }, { head: "Dose", cell: r => r.dose ?? "—" }, { head: "Times", cell: r => r.times_of_day.join(", ") || "—" }, { head: "", cell: r => <Badge warn={!r.active}>{r.active ? "current" : "stopped"}</Badge> }]} empty="No medications shared." /></Section>
      <Section title="Vitals (30 days)"><Table rows={vit} cols={[{ head: "When", cell: r => dt(r.measured_at) }, { head: "Type", cell: r => r.kind }, { head: "Value", cell: r => <span className={r.abnormal ? "error" : ""}>{r.value}{r.value2 ? `/${r.value2}` : ""} {r.unit}</span> }]} /></Section>
      {me.role === "doctor" && <Section title="Request laboratory tests"><div className="card"><input aria-label="Tests" placeholder="Comma separated tests" value={tests} onChange={e => setTests(e.target.value)} />
        <button onClick={() => act.run(async () => { await api(`/patients/${sel}/lab-requests`, { body: { tests: tests.split(",").map(s => s.trim()).filter(Boolean) } }); setTests(""); })}>Request</button><Err msg={act.err} /></div></Section>}</>}
  </>);
}

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; const hm = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`; const mins = (s: string) => +s.slice(0, 2) * 60 + +s.slice(3, 5);
export function Availability() {
  const { data } = useFetch<any>("/providers/me/profile"); const [slots, setSlots] = useState<any[] | null>(null); const act = useAction(); const [ok, setOk] = useState("");
  const cur = slots ?? data?.availability ?? [];
  return (<><h1>Availability</h1>
    <div className="card">{DAYS.map((n, wd) => <div key={n} className="row" style={{ marginBottom: 8 }}><b style={{ width: 44 }}>{n}</b>
      {cur.map((s: any, i: number) => s.weekday === wd && <span key={i} className="badge">{hm(s.start_minute)}–{hm(s.end_minute)} <button aria-label="Remove" onClick={() => setSlots(cur.filter((_: any, j: number) => j !== i))}>✕</button></span>)}
      <button onClick={() => { const a = prompt(`${n} start (HH:MM)`, "09:00"), b = prompt(`${n} end (HH:MM)`, "17:00"); if (a && b && mins(a) < mins(b)) setSlots([...cur, { weekday: wd, start_minute: mins(a), end_minute: mins(b) }]); }}>＋</button></div>)}
      <button className="primary" disabled={!slots} onClick={() => act.run(async () => { await api("/providers/me/availability", { method: "PUT", body: { slots: cur } }); setOk("Saved."); })}>Save availability</button> {ok}<Err msg={act.err} /></div></>);
}

export function Profile() {
  const { data: p, reload } = useFetch<any>("/providers/me/profile"); const { data: v } = useFetch<any>("/providers/me/verification");
  const [f, setF] = useState<any>({}); const act = useAction(reload); const [ok, setOk] = useState("");
  if (!p) return <p>Loading…</p>; const val = (k: string) => f[k] ?? p[k] ?? "";
  return (<><h1>Professional profile</h1>
    <Section title="Credential verification"><div className="card"><Badge warn={v?.status !== "approved"}>{v?.status}</Badge> {v?.note && <p>Reviewer note: {v.note}</p>}
      <ul>{v?.credentials.map((c: any, i: number) => <li key={i}>{c.kind} — {c.issuer} #{c.number} <Badge warn={c.status !== "approved"}>{c.status}</Badge></li>)}</ul>
      <p className="muted">Verification, prescribing authority and credits are separate: contributions never replace formal licensing.</p></div></Section>
    <Section title="Add / update a credential"><CredentialForm onDone={reload} /></Section>
    <Section title="Public profile (shown to patients)"><div className="card"><div className="grid">
      {([["specialty", "Specialty"], ["years_experience", "Years of experience"], ["city", "City"], ["photo_url", "Photo URL"]] as const).map(([k, l]) => <div key={k}><label htmlFor={k}>{l}</label><input id={k} value={val(k)} onChange={e => setF({ ...f, [k]: k === "years_experience" ? +e.target.value || 0 : e.target.value })} /></div>)}
      <div><label htmlFor="lg">Languages (codes, comma separated)</label><input id="lg" value={f.languages ?? p.languages.join(",")} onChange={e => setF({ ...f, languages: e.target.value })} /></div></div>
      <label htmlFor="q">Qualifications</label><textarea id="q" rows={2} value={val("qualifications")} onChange={e => setF({ ...f, qualifications: e.target.value })} />
      <label htmlFor="bio">Bio</label><textarea id="bio" rows={3} value={val("bio")} onChange={e => setF({ ...f, bio: e.target.value })} />
      <button className="primary" onClick={() => act.run(async () => { const b = { ...f }; if (typeof b.languages === "string") b.languages = b.languages.split(",").map((s: string) => s.trim()).filter(Boolean); await api("/providers/me/profile", { method: "PATCH", body: b }); setF({}); setOk("Saved."); })}>Save</button> {ok}<Err msg={act.err} /></div></Section></>);
}

function CredentialForm({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState({ kind: "licence", issuer: "", number: "" }); const [doc, setDoc] = useState<{ key: string; name: string } | null>(null); const act = useAction(onDone); const [ok, setOk] = useState("");
  return (<div className="card"><div className="grid"><div><label htmlFor="ck">Type</label><select id="ck" value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}>{["licence", "degree", "national_id", "certificate"].map(k => <option key={k}>{k}</option>)}</select></div>
    <div><label htmlFor="ci">Issuing body</label><input id="ci" value={f.issuer} onChange={e => setF({ ...f, issuer: e.target.value })} /></div>
    <div><label htmlFor="cn">Registration / ID number</label><input id="cn" value={f.number} onChange={e => setF({ ...f, number: e.target.value })} /></div></div>
    <FileUpload purpose="credential" label="Upload scan (PDF/photo)" onUploaded={setDoc} /> {doc && <Badge>{doc.name}</Badge>} <small className="muted">Only our verification team can open these files.</small><br /><br />
    <button className="primary" disabled={!f.issuer || !f.number} onClick={() => act.run(async () => { await api("/providers/me/credentials", { body: { ...f, document_key: doc?.key ?? null } }); setOk("Submitted for review."); setDoc(null); setF({ ...f, issuer: "", number: "" }); })}>Submit credential</button> {ok}<Err msg={act.err} /></div>);
}

export function Earnings() {
  const { data: e } = useFetch<any>("/payments/earnings"); const { data: sub } = useFetch<any>("/payments/subscription"); const { data: hist } = useFetch<any[]>("/payments/history"); const act = useAction();
  return (<><h1>Earnings & billing</h1>
    <div className="grid"><Stat label="Pending payout" value={ghs(e?.pending_net_pesewas ?? 0)} /><Stat label="Paid out" value={ghs(e?.paid_net_pesewas ?? 0)} /></div>
    <Section title="Per consultation"><Table<any> rows={e?.items ?? null} cols={[{ head: "Payment", cell: r => `#${r.payment_id}` }, { head: "Gross", cell: r => ghs(r.gross) }, { head: "Platform commission", cell: r => ghs(r.commission) }, { head: "Net to you", cell: r => <b>{ghs(r.net)}</b> }, { head: "Status", cell: r => <Badge>{r.status}</Badge> }]} /></Section>
    <Section title="Professional subscription"><div className="card"><Badge warn={!sub?.active}>{sub?.active ? "Active" : "Inactive"}</Badge> {sub?.expires_at && <>until {d(sub.expires_at)}</>}
      <p><button className="primary" onClick={() => act.run(async () => { const m = await startPayment({ purpose: "pro_subscription", method: "mtn_momo" }); if (m) alert(m); })}>Pay subscription</button> <Link to="/pro/contributions">Or earn a free month with credits</Link></p><Err msg={act.err} /></div></Section>
    <Section title="Payment history"><Table rows={hist} cols={[{ head: "Date", cell: r => dt(r.created_at) }, { head: "For", cell: r => r.purpose }, { head: "Amount", cell: r => ghs(r.amount_pesewas) }, { head: "Status", cell: r => <Badge>{r.status}</Badge> }]} /></Section></>);
}

export function Contributions() {
  const { data: cr, reload } = useFetch<any>("/credits/me"); const { data: mine, reload: r2 } = useFetch<any[]>("/contributions/mine");
  const [c, setC] = useState({ kind: "article", title: "", body: "", topic: "", language: "en" }); const act = useAction(() => { reload(); r2(); });
  const pct = cr ? Math.min(100, (cr.balance_units / cr.threshold_units) * 100) : 0;
  return (<><h1>Contributions & credits</h1>
    {cr && <div className="card"><b>{cr.balance_units}</b> of {cr.threshold_units} credit units <div role="progressbar" aria-label="Progress towards free renewal" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} style={{ background: "#e4e7ec", borderRadius: 99, height: 14, margin: "8px 0" }}><div style={{ width: `${pct}%`, background: "var(--teal)", height: 14, borderRadius: 99 }} /></div>
      Each approved contribution earns {cr.credit_per_contribution} units. {cr.eligible ? <b>You're eligible for a free renewal month!</b> : `${cr.contributions_needed} more approved contributions to go.`}
      {cr.eligible && <p><button className="primary" onClick={() => act.run(() => api("/credits/redeem-renewal", { method: "POST" }))}>Apply free renewal month</button></p>}
      <details><summary>Eligibility, expiry & restrictions</summary><p>{cr.terms}</p></details></div>}
    <Section title="Publish"><div className="card"><div className="grid"><div><label htmlFor="k">Type</label><select id="k" value={c.kind} onChange={e => setC({ ...c, kind: e.target.value })}>{["article", "research", "education", "answer", "campaign"].map(k => <option key={k}>{k}</option>)}</select></div>
      <div><label htmlFor="tp">Topic</label><input id="tp" value={c.topic} onChange={e => setC({ ...c, topic: e.target.value })} placeholder="e.g. nutrition" /></div>
      <div><label htmlFor="lg">Language</label><select id="lg" value={c.language} onChange={e => setC({ ...c, language: e.target.value })}>{["en", "tw", "ha", "fat", "fr", "es"].map(k => <option key={k}>{k}</option>)}</select></div></div>
      <label htmlFor="ti">Title</label><input id="ti" value={c.title} onChange={e => setC({ ...c, title: e.target.value })} />
      <label htmlFor="bd">Content (evidence-based; plagiarised or duplicate content earns no credit and can be reversed)</label><textarea id="bd" rows={8} value={c.body} onChange={e => setC({ ...c, body: e.target.value })} />
      <button className="primary" disabled={!c.title || !c.body} onClick={() => act.run(async () => { await api("/contributions", { body: c }); setC({ ...c, title: "", body: "" }); })}>Submit for review</button><Err msg={act.err} /></div></Section>
    <Section title="My submissions"><Table rows={mine} cols={[{ head: "Title", cell: r => r.title }, { head: "Type", cell: r => r.kind }, { head: "Status", cell: r => <Badge warn={r.status === "rejected"}>{r.status}</Badge> }, { head: "Reviewer note", cell: r => r.review_note ?? "—" },
      { head: "", cell: r => r.status !== "withdrawn" && <button onClick={() => act.run(() => api(`/contributions/${r.id}/withdraw`, { method: "POST" }))}>Withdraw</button> }]} /></Section>
    <Section title="Credit ledger"><Table<any> rows={cr?.ledger ?? null} cols={[{ head: "Date", cell: r => d(r.at) }, { head: "Type", cell: r => r.type }, { head: "Units", cell: r => <b style={{ color: r.units < 0 ? "var(--danger)" : "var(--ok)" }}>{r.units > 0 ? "+" : ""}{r.units}</b> }, { head: "Reason", cell: r => r.reason ?? "—" }]} /></Section></>);
}

export function LabQueue() {
  const { data, reload } = useFetch<any[]>("/lab-requests"); const [res, setRes] = useState<Record<number, string>>({}); const [files, setFiles] = useState<Record<number, { key: string; name: string }>>({}); const act = useAction(reload);
  return (<><h1>Laboratory queue</h1><Err msg={act.err} />
    {data?.map(r => <div className="card" key={r.id} style={{ marginBottom: 8 }}><b>#{r.id}</b> patient #{r.patient_id} · {r.tests.join(", ")} <Badge>{r.status}</Badge>
      <label htmlFor={`r${r.id}`}>Verified result</label><textarea id={`r${r.id}`} rows={3} value={res[r.id] ?? ""} onChange={e => setRes({ ...res, [r.id]: e.target.value })} />
      <FileUpload purpose="lab" extra={{ lab_request_id: r.id }} label="Attach result file" onUploaded={f => setFiles({ ...files, [r.id]: f })} /> {files[r.id] && <Badge>{files[r.id].name}</Badge>}<br /><br />
      <button className="primary" disabled={!res[r.id] && !files[r.id]} onClick={() => act.run(() => api(`/lab-requests/${r.id}/result`, { body: { result_text: res[r.id] || null, result_document_key: files[r.id]?.key ?? null } }))}>Publish result to patient</button></div>)}
    {data?.length === 0 && <p className="muted">No open requests.</p>}<p className="muted">Published results appear in the patient's record and they are notified.</p></>);
}

export function FacilityPortal() {
  const { data, reload } = useFetch<any[]>("/facilities/mine"); const { data: appts, reload: r2 } = useFetch<any[]>("/facilities/mine/appointments");
  const [f, setF] = useState({ name: "", kind: "clinic", address: "", city: "", phone: "", services: "", specialties: "" }); const act = useAction(() => { reload(); r2(); });
  const list = (s: string) => s.split(",").map(x => x.trim()).filter(Boolean);
  return (<><h1>My facility</h1>
    {data?.map(x => <div className="card" key={x.id} style={{ marginBottom: 8 }}><b>{x.name}</b> ({x.kind}) <Badge warn={!x.verified}>{x.verified ? "listed" : "awaiting admin verification"}</Badge><br />{x.address} · {x.phone}
      <div className="row"><button onClick={() => { const s = prompt("Services (comma separated)", x.services.join(", ")); if (s !== null) act.run(() => api(`/facilities/mine/${x.id}`, { method: "PATCH", body: { services: list(s) } })); }}>Edit services</button>
        <button onClick={() => { const s = prompt("Phone", x.phone ?? ""); if (s !== null) act.run(() => api(`/facilities/mine/${x.id}`, { method: "PATCH", body: { phone: s } })); }}>Edit phone</button></div></div>)}
    <Section title="Register a facility"><div className="card"><div className="grid">
      {([["name", "Name"], ["address", "Address"], ["city", "City"], ["phone", "Phone"], ["services", "Services (comma separated)"], ["specialties", "Specialties (comma separated)"]] as const).map(([k, l]) => <div key={k}><label htmlFor={k}>{l}</label><input id={k} value={(f as any)[k]} onChange={e => setF({ ...f, [k]: e.target.value })} /></div>)}
      <div><label htmlFor="fk">Type</label><select id="fk" value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}>{["hospital", "clinic", "pharmacy", "laboratory", "diagnostic", "specialist"].map(k => <option key={k}>{k}</option>)}</select></div></div>
      <button className="primary" disabled={!f.name || !f.address} onClick={() => act.run(() => api("/facilities/mine", { body: { ...f, services: list(f.services), specialties: list(f.specialties) } }))}>Submit for verification</button><Err msg={act.err} /></div></Section>
    <Section title="Booked appointments"><Table rows={appts} cols={[{ head: "When", cell: r => dt(r.starts_at) }, { head: "Reason", cell: r => r.reason ?? "—" }, { head: "Status", cell: r => <Badge>{r.status}</Badge> },
      { head: "", cell: r => <><button onClick={() => act.run(() => api(`/facilities/mine/appointments/${r.id}?action=confirm`, { method: "PATCH" }))}>Confirm</button> <button onClick={() => act.run(() => api(`/facilities/mine/appointments/${r.id}?action=cancel`, { method: "PATCH" }))}>Cancel</button></> }]} /></Section></>);
}
