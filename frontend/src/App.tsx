import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { LANGS } from "./i18n";
import { api, hasToken, setToken } from "./api";
import Layout from "./Layout";
import Auth from "./pages/Auth";
import Emergency from "./pages/Emergency";
import PaymentComplete from "./pages/PaymentComplete";
import VerifyEmail from "./pages/VerifyEmail";
import ConsultRoom from "./pages/ConsultRoom";
import Assistant from "./pages/patient/Assistant";
import PatientHome from "./pages/patient/Home";
import { Appointments, Consult } from "./pages/patient/Care";
import { Labs, Medications, Monitoring, Records } from "./pages/patient/Health";
import { Billing, Drugs, Education, Facilities, Notifications, Settings } from "./pages/patient/More";
import * as P from "./pages/pro/Pro";
import * as A from "./pages/admin/Admin";

export type Me = { id: number; full_name: string; role: string; preferred_language: string; verification_status?: string };
const homeFor = (m: Me | null) => !m ? "/login" : m.role === "patient" ? "/app" : m.role === "admin" ? "/admin" : "/pro";

export default function App() {
  const { t, i18n } = useTranslation();
  const nav = useNavigate();
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(!hasToken());
  useEffect(() => { if (hasToken()) api<Me>("/auth/me").then(setMe).catch(() => setToken("")).finally(() => setReady(true)); }, []);
  const changeLang = (l: string) => { i18n.changeLanguage(l); localStorage.setItem("mc_lang", l); document.documentElement.lang = l; if (me) api("/auth/me", { method: "PATCH", body: { preferred_language: l } }).catch(() => {}); };
  const logout = () => { api("/auth/logout", { method: "POST" }).catch(() => {}).finally(() => { setToken(""); setMe(null); nav("/login"); }); };
  if (!ready) return null;
  const guard = (role: "patient" | "pro" | "admin") => !me ? <Navigate to="/login" /> :
    (role === "patient" ? me.role === "patient" : role === "admin" ? me.role === "admin" : !["patient", "admin"].includes(me.role)) ? <Layout me={me} /> : <Navigate to={homeFor(me)} />;
  return (
    <>
      <a href="#main" className="sr">Skip to content</a>
      <header>
        <Link to={homeFor(me)} className="brand" style={{ color: "#fff", textDecoration: "none" }}>⚕ {t("appName")}</Link>
        <label htmlFor="lang" style={{ fontWeight: 400 }}>{t("language")}</label>
        <select id="lang" style={{ width: "auto", margin: 0 }} value={i18n.language} onChange={e => changeLang(e.target.value)}>{LANGS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}</select>
        <Link to="/emergency">🚑 {t("emergency")}</Link>
        {me && <button onClick={logout}>{t("logout")}</button>}
      </header>
      <div className="banner" role="note">{t("emergencyBanner")}</div>
      <main id="main" style={{ maxWidth: 1200, margin: "0 auto" }}>
        <Routes>
          <Route path="/login" element={<div style={{ padding: 16 }}><Auth onLogin={m => { setMe(m); nav(homeFor(m)); }} /></div>} />
          <Route path="/verify" element={<div style={{ padding: 16 }}><VerifyEmail /></div>} />
          <Route path="/emergency" element={<div style={{ padding: 16 }}><Emergency /></div>} />
          <Route path="/payment/complete" element={me ? <div style={{ padding: 16 }}><PaymentComplete home={homeFor(me)} /></div> : <Navigate to="/login" />} />
          <Route path="/app" element={guard("patient")}>
            <Route index element={me && <PatientHome me={me} />} />
            <Route path="consult" element={<Consult />} /><Route path="consult/:id" element={me && <ConsultRoom me={me} />} />
            <Route path="appointments" element={<Appointments />} /><Route path="monitoring" element={me && <Monitoring me={me} />} />
            <Route path="records" element={me && <Records me={me} />} /><Route path="medications" element={<Medications />} /><Route path="labs" element={<Labs />} /><Route path="drugs" element={<Drugs />} />
            <Route path="facilities" element={<Facilities />} /><Route path="education" element={<Education />} /><Route path="assistant" element={<Assistant />} />
            <Route path="billing" element={<Billing />} /><Route path="notifications" element={<Notifications />} /><Route path="settings" element={<Settings onLang={changeLang} />} />
          </Route>
          <Route path="/pro" element={guard("pro")}>
            <Route index element={me && <P.Overview me={me} />} /><Route path="consultations" element={<P.Consultations />} /><Route path="consultations/:id" element={me && <ConsultRoom me={me} />} />
            <Route path="appointments" element={<P.ProAppointments />} /><Route path="patients" element={me && <P.Patients me={me} />} /><Route path="availability" element={<P.Availability />} />
            <Route path="profile" element={<P.Profile />} /><Route path="earnings" element={<P.Earnings />} /><Route path="contributions" element={<P.Contributions />} />
            <Route path="lab" element={<P.LabQueue />} /><Route path="facility" element={<P.FacilityPortal />} /><Route path="notifications" element={<Notifications />} />
          </Route>
          <Route path="/admin" element={guard("admin")}>
            <Route index element={<A.Overview />} /><Route path="verification" element={<A.Verification />} /><Route path="users" element={<A.Users />} /><Route path="moderation" element={<A.Moderation />} />
            <Route path="transactions" element={<A.Transactions />} /><Route path="subscriptions" element={<A.Subscriptions />} /><Route path="consultations" element={<A.Consultations />} />
            <Route path="appointments" element={<A.Appointments />} /><Route path="facilities" element={<A.Facilities />} /><Route path="labs" element={<A.Labs />} /><Route path="credits" element={<A.Credits />} />
            <Route path="complaints" element={<A.Complaints />} /><Route path="interpreters" element={<A.Interpreters />} /><Route path="languages" element={<A.Languages />} /><Route path="reports" element={<A.Reports />} /><Route path="audit" element={<A.Audit />} /><Route path="settings" element={<A.Settings />} />
          </Route>
          <Route path="*" element={<Navigate to={homeFor(me)} />} />
        </Routes>
      </main>
    </>
  );
}
