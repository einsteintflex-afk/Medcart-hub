import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api, startPayment } from "../api";
import type { Me } from "../App";

export default function PatientHome({ me }: { me: Me }) {
  const { t } = useTranslation();
  const [sub, setSub] = useState<any>(null); const [notes, setNotes] = useState<any[]>([]); const [appts, setAppts] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const load = () => { api("/payments/subscription").then(setSub); api("/notifications").then(setNotes); api("/appointments").then(setAppts); };
  useEffect(load, []);

  async function subscribe() {
    setMsg("");
    try { setMsg(await startPayment({ purpose: "patient_subscription", method: "mtn_momo" })); } catch (e: any) { setMsg(e.message); }
  }
  const tiles: [string, string][] = [["/providers?role=pharmacist", t("talkPharmacist")], ["/providers?role=doctor", t("consultDoctor")], ["/monitoring", t("monitoring")],
    ["/assistant", t("assistant")], ["/emergency", t("emergency")]];
  return (<>
    <h1>{t("welcome", { name: me.full_name })}</h1>
    <section className="card" aria-label={t("subscription")}>
      <b>{t("subscription")}:</b> <span className={`badge ${sub?.active ? "" : "warn"}`}>{sub?.active ? t("active") : t("inactive")}</span>
      {sub?.expires_at && <> · {new Date(sub.expires_at).toLocaleDateString()}</>}
      <p>{t("doctorFee")}</p>
      {!sub?.active && <button className="primary" onClick={subscribe}>{t("subscribe")}</button>}
      {msg && <p role="status">{msg}</p>}
    </section>
    <div className="grid" style={{ marginTop: 12 }}>{tiles.map(([to, label]) => <Link key={to} to={to} className="card tile">{label}</Link>)}</div>
    <h2>{t("appointments")}</h2>
    <div className="card">{appts.length ? appts.map(a => <div key={a.id}>{new Date(a.starts_at).toLocaleString()} — {a.status}</div>) : "—"}</div>
    <h2>🔔</h2>
    <div className="card">{notes.slice(0, 8).map(n => <div key={n.id}><b>{n.title}</b> {n.body}</div>)}</div>
  </>);
}
