import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, setToken } from "../api";
import type { Me } from "../App";

export default function Auth({ onLogin }: { onLogin: (m: Me) => void }) {
  const { t, i18n } = useTranslation();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [f, setF] = useState({ email: "", password: "", full_name: "", phone: "", role: "patient", licence_issuer: "", licence_number: "", specialty: "" });
  const [err, setErr] = useState(""); const [info, setInfo] = useState("");
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  const isPro = f.role !== "patient";

  async function submit(e: FormEvent) {
    e.preventDefault(); setErr(""); setInfo("");
    try {
      if (mode === "register") {
        const body: any = { email: f.email, password: f.password, full_name: f.full_name, phone: f.phone || null, role: f.role, preferred_language: i18n.language };
        if (isPro) { body.specialty = f.specialty; body.credentials = [{ kind: "licence", issuer: f.licence_issuer, number: f.licence_number }]; }
        const r = await api("/auth/register", { body });
        setInfo(r.message); setMode("login"); return;
      }
      const r = await api("/auth/login", { body: { email: f.email, password: f.password } });
      setToken(r.access_token);
      onLogin(await api<Me>("/auth/me"));
    } catch (e: any) { setErr(e.message); }
  }
  return (
    <form className="card" onSubmit={submit} style={{ maxWidth: 460, margin: "0 auto" }}>
      <h1>{mode === "login" ? t("login") : t("register")}</h1>
      {mode === "register" && <>
        <label htmlFor="role">I am a</label>
        <select id="role" value={f.role} onChange={set("role")} style={{ width: "100%", marginBottom: 12 }}>
          {["patient", "doctor", "pharmacist", "nurse", "lab", "facility_admin"].map(r => <option key={r}>{r}</option>)}
        </select>
        <label htmlFor="fn">Full name</label><input id="fn" required value={f.full_name} onChange={set("full_name")} />
        <label htmlFor="ph">Phone</label><input id="ph" type="tel" value={f.phone} onChange={set("phone")} />
        {isPro && <>
          <p className="error">Your account stays pending until an administrator verifies your licence.</p>
          <label htmlFor="sp">Specialty</label><input id="sp" value={f.specialty} onChange={set("specialty")} />
          <label htmlFor="li">Licensing body (e.g. Medical &amp; Dental Council)</label><input id="li" required value={f.licence_issuer} onChange={set("licence_issuer")} />
          <label htmlFor="ln">Registration / licence number</label><input id="ln" required value={f.licence_number} onChange={set("licence_number")} />
        </>}
      </>}
      <label htmlFor="em">{t("email")}</label><input id="em" type="email" required value={f.email} onChange={set("email")} autoComplete="username" />
      <label htmlFor="pw">{t("password")}</label><input id="pw" type="password" required minLength={10} value={f.password} onChange={set("password")} autoComplete={mode === "login" ? "current-password" : "new-password"} />
      {err && <p className="error" role="alert">{err}</p>}{info && <p role="status">{info}</p>}
      <button className="primary" type="submit">{mode === "login" ? t("login") : t("register")}</button>{" "}
      <button type="button" onClick={() => setMode(mode === "login" ? "register" : "login")}>{mode === "login" ? t("register") : t("login")}</button>
    </form>
  );
}
