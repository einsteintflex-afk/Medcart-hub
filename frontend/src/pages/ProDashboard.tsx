import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, ghs } from "../api";
import type { Me } from "../App";

export default function ProDashboard({ me }: { me: Me }) {
  const { t } = useTranslation();
  const [ver, setVer] = useState<any>(null); const [cr, setCr] = useState<any>(null); const [consults, setConsults] = useState<any[]>([]); const [earn, setEarn] = useState<any>(null);
  const [c, setC] = useState({ title: "", body: "", kind: "article" }); const [msg, setMsg] = useState("");
  const load = () => {
    api("/providers/me/verification").then(setVer).catch(() => {});
    api("/consultations").then(setConsults); api("/payments/earnings").then(setEarn);
    api("/credits/me").then(setCr).catch(() => setCr(null));
  };
  useEffect(load, []);
  const verified = ver?.status === "approved";
  return (<>
    <h1>{me.full_name}</h1>
    <p>{t("verified")}: <span className={`badge ${verified ? "" : "warn"}`}>{ver?.status ?? "…"}</span> {!verified && "You can use the dashboard fully once an administrator approves your credentials."}</p>
    {verified && <>
      <h2>Consultation requests</h2>
      <div className="card">{consults.filter(x => x.status === "requested").map(x => <div key={x.id}>#{x.id} ({x.channel}){" "}
        <button onClick={() => api(`/consultations/${x.id}/decision`, { body: { accept: true } }).then(load)}>Accept</button>{" "}
        <button onClick={() => api(`/consultations/${x.id}/decision`, { body: { accept: false } }).then(load)}>Decline</button></div>)}</div>
      {earn && <><h2>Earnings</h2><div className="card">Pending: {ghs(earn.pending_net_pesewas)} · Paid: {ghs(earn.paid_net_pesewas)}</div></>}
      {cr && <><h2>{t("credits")}</h2><div className="card">
        <b>{cr.balance_units}</b> / {cr.threshold_units} units · each approved contribution earns {cr.credit_per_contribution}.
        {cr.eligible ? <p><button className="primary" onClick={() => api("/credits/redeem-renewal", { method: "POST" }).then(load)}>Apply free renewal month</button></p> : <p>{cr.contributions_needed} more approved contributions needed.</p>}
        <small>{cr.terms}</small>
        <h3>{t("ledger")}</h3><table><tbody>{cr.ledger.map((e: any) => <tr key={e.id}><td>{new Date(e.at).toLocaleDateString()}</td><td>{e.type}</td><td>{e.units > 0 ? "+" : ""}{e.units}</td><td>{e.reason}</td></tr>)}</tbody></table></div></>}
      <h2>Publish a contribution</h2>
      <div className="card">
        <label htmlFor="ct">Title</label><input id="ct" value={c.title} onChange={e => setC({ ...c, title: e.target.value })} />
        <label htmlFor="cb">Content (reviewed by moderators before publication)</label><textarea id="cb" rows={6} value={c.body} onChange={e => setC({ ...c, body: e.target.value })} />
        <button className="primary" onClick={() => api("/contributions", { body: c }).then(() => { setMsg("Submitted for review."); setC({ ...c, title: "", body: "" }); })}>Submit</button> {msg}
      </div></>}
  </>);
}
