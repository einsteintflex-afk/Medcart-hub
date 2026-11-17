import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api, ghs, startPayment } from "../../api";
import type { Me } from "../../App";
import { Badge, Err, Section, Stat, d, dt, useAction, useFetch } from "../../ui";

const LABEL: Record<string, string> = { bp: "Blood pressure", glucose: "Glucose", heart_rate: "Heart rate", temperature: "Temp", spo2: "SpO₂", weight: "Weight", resp_rate: "Resp. rate" };

export default function Home({ me }: { me: Me }) {
  const { t } = useTranslation();
  const { data: o } = useFetch<any>("/patients/me/overview");
  const pay = useAction();
  if (!o) return <p>Loading…</p>;
  const tiles: [string, string, string][] = [["/app/consult?role=pharmacist", "💊", t("talkPharmacist")], ["/app/consult?role=doctor", "🩺", t("consultDoctor")],
    ["/app/monitoring", "❤️", t("monitoring")], ["/app/assistant", "🤖", t("assistant")], ["/app/facilities", "🏥", t("facilities")], ["/app/records", "📁", t("records")]];
  return (<>
    <h1>{t("welcome", { name: me.full_name })}</h1>
    <div className="card"><b>{t("subscription")}:</b> <Badge warn={!o.subscription_active}>{o.subscription_active ? t("active") : t("inactive")}</Badge>
      {o.subscription_expires_at && <> · until {d(o.subscription_expires_at)}</>}
      <p>{t("doctorFee")}</p>
      {!o.subscription_active && <button className="primary" onClick={() => pay.run(async () => { const m = await startPayment({ purpose: "patient_subscription", method: "mtn_momo" }); if (m) alert(m); })}>{t("subscribe")}</button>}
      <Err msg={pay.err} /></div>
    <div className="grid" style={{ margin: "12px 0" }}>{tiles.map(([to, ico, label]) => <Link key={to} to={to} className="card tile"><span style={{ fontSize: "1.8rem" }}>{ico}</span><br />{label}</Link>)}</div>
    <div className="grid">
      <Stat label="Open consultations" value={o.open_consultations} /><Stat label="Active medications" value={o.active_medications} />
      <Stat label="Lab results" value={o.new_lab_results} /><Stat label="Unread notifications" value={o.unread_notifications} warn={o.unread_notifications > 0} />
    </div>
    <Section title="Latest readings"><div className="grid">{Object.entries(o.latest_vitals).map(([k, v]: any) =>
      <div className="card" key={k}><div className="muted">{LABEL[k] ?? k}</div><b style={{ fontSize: "1.4rem", color: v.abnormal ? "var(--danger)" : undefined }}>{v.value}{v.value2 ? `/${v.value2}` : ""}</b> {v.unit}{v.abnormal && <div className="error">{t("abnormal")}</div>}</div>)}
      {!Object.keys(o.latest_vitals).length && <Link to="/app/monitoring">Record your first reading →</Link>}</div></Section>
    <Section title={t("appointments")}>{o.upcoming_appointments.length ? o.upcoming_appointments.map((a: any) => <div className="card" key={a.id}>{dt(a.starts_at)} <Badge>{a.status}</Badge></div>) : <Link to="/app/appointments">Book an appointment →</Link>}</Section>
  </>);
}
