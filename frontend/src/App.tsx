import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { LANGS } from "./i18n";
import { api, hasToken, setToken } from "./api";
import Auth from "./pages/Auth";
import PatientHome from "./pages/PatientHome";
import Assistant from "./pages/Assistant";
import Monitoring from "./pages/Monitoring";
import Providers from "./pages/Providers";
import ProDashboard from "./pages/ProDashboard";
import AdminDashboard from "./pages/AdminDashboard";
import Emergency from "./pages/Emergency";

export type Me = { id: number; full_name: string; role: string; preferred_language: string; verification_status?: string };

export default function App() {
  const { t, i18n } = useTranslation();
  const nav = useNavigate();
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(!hasToken());

  useEffect(() => { if (hasToken()) api<Me>("/auth/me").then(setMe).catch(() => setToken("")).finally(() => setReady(true)); }, []);
  const changeLang = (l: string) => { i18n.changeLanguage(l); localStorage.setItem("mc_lang", l); document.documentElement.lang = l; if (me) api("/auth/me", { method: "PATCH", body: { preferred_language: l } }).catch(() => {}); };
  const logout = () => { setToken(""); setMe(null); nav("/"); };
  if (!ready) return null;

  const home = !me ? "/login" : me.role === "patient" ? "/app" : me.role === "admin" ? "/admin" : "/pro";
  return (
    <>
      <a href="#main" style={{ position: "absolute", left: -999 }}>Skip to content</a>
      <header>
        <Link to={home} className="brand" style={{ color: "#fff", textDecoration: "none" }}>⚕ {t("appName")}</Link>
        <label htmlFor="lang" style={{ fontWeight: 400 }}>{t("language")}</label>
        <select id="lang" value={i18n.language} onChange={e => changeLang(e.target.value)}>{LANGS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}</select>
        <Link to="/emergency">🚑 {t("emergency")}</Link>
        {me && <button onClick={logout}>{t("logout")}</button>}
      </header>
      <div className="banner" role="note">{t("emergencyBanner")}</div>
      <main id="main">
        <Routes>
          <Route path="/login" element={<Auth onLogin={m => { setMe(m); nav(m.role === "patient" ? "/app" : m.role === "admin" ? "/admin" : "/pro"); }} />} />
          <Route path="/emergency" element={<Emergency />} />
          <Route path="/app" element={me ? <PatientHome me={me} /> : <Navigate to="/login" />} />
          <Route path="/assistant" element={me ? <Assistant /> : <Navigate to="/login" />} />
          <Route path="/monitoring" element={me ? <Monitoring /> : <Navigate to="/login" />} />
          <Route path="/providers" element={me ? <Providers /> : <Navigate to="/login" />} />
          <Route path="/pro" element={me ? <ProDashboard me={me} /> : <Navigate to="/login" />} />
          <Route path="/admin" element={me?.role === "admin" ? <AdminDashboard /> : <Navigate to="/login" />} />
          <Route path="*" element={<Navigate to={home} />} />
        </Routes>
      </main>
    </>
  );
}
