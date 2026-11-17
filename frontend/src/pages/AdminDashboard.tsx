import { useEffect, useState } from "react";
import { api, ghs } from "../api";

export default function AdminDashboard() {
  const [pros, setPros] = useState<any[]>([]); const [contribs, setContribs] = useState<any[]>([]); const [fin, setFin] = useState<any>(null); const [ops, setOps] = useState<any>(null); const [recon, setRecon] = useState<any>(null);
  const load = () => { api("/admin/providers/pending").then(setPros); api("/admin/contributions/pending").then(setContribs); api("/admin/reports/financial").then(setFin); api("/admin/reports/operational").then(setOps); };
  useEffect(load, []);
  return (<>
    <h1>Administration</h1>
    {ops && <div className="grid"><div className="card">Users<br /><b>{ops.users}</b></div><div className="card">Consultations<br /><b>{ops.consultations}</b></div><div className="card">Pending providers<br /><b>{ops.providers_pending}</b></div><div className="card">Open complaints<br /><b>{ops.open_complaints}</b></div></div>}
    {fin && <p className="card">Commission earned {ghs(fin.platform_commission_pesewas)} · Payouts pending {ghs(fin.provider_payouts_pending_pesewas)} <button onClick={() => api("/payments/admin/reconciliation").then(setRecon)}>Run reconciliation</button>{recon && <pre>{JSON.stringify(recon, null, 1)}</pre>}</p>}
    <h2>Credential verification queue</h2>
    {pros.map(p => <div className="card" key={p.id}><b>{p.name}</b> ({p.role}) {p.email}
      <ul>{p.credentials.map((c: any) => <li key={c.id}>{c.kind}: {c.issuer} #{c.number}</li>)}</ul>
      <small>Verify each number against the issuing council's register before approving.</small><br />
      <button className="primary" onClick={() => api(`/admin/providers/${p.id}/review`, { body: { approve: true, can_prescribe: p.role === "doctor" } }).then(load)}>Approve</button>{" "}
      <button onClick={() => api(`/admin/providers/${p.id}/review`, { body: { approve: false, note: "Could not verify credentials" } }).then(load)}>Reject</button></div>)}
    <h2>Contribution moderation</h2>
    {contribs.map(c => <div className="card" key={c.id}><b>{c.title}</b> ({c.kind})<p>{c.body.slice(0, 400)}</p>
      <button className="primary" onClick={() => api(`/admin/contributions/${c.id}/moderate`, { body: { approve: true } }).then(load)}>Approve</button>{" "}
      <button onClick={() => api(`/admin/contributions/${c.id}/moderate`, { body: { approve: false, note: "Does not meet clinical standards" } }).then(load)}>Reject</button></div>)}
  </>);
}
