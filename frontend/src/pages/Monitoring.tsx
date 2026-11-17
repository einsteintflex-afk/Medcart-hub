import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api";

function Chart({ pts }: { pts: { v: number; ab: boolean }[] }) {
  if (pts.length < 2) return <p>—</p>;
  const w = 320, h = 90, min = Math.min(...pts.map(p => p.v)), max = Math.max(...pts.map(p => p.v)), span = max - min || 1;
  const xy = pts.map((p, i) => [i * (w / (pts.length - 1)), h - 8 - ((p.v - min) / span) * (h - 16)] as const);
  return <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`trend from ${pts[0].v} to ${pts[pts.length - 1].v}`} style={{ width: "100%", maxWidth: 400 }}>
    <polyline fill="none" stroke="#0e9aa7" strokeWidth="2" points={xy.map(p => p.join(",")).join(" ")} />
    {xy.map(([x, y], i) => <circle key={i} cx={x} cy={y} r="4" fill={pts[i].ab ? "#b42318" : "#0e9aa7"} />)}</svg>;
}

export default function Monitoring() {
  const { t } = useTranslation();
  const [kind, setKind] = useState("bp"); const [v, setV] = useState(""); const [v2, setV2] = useState(""); const [rows, setRows] = useState<any[]>([]); const [alert, setAlert] = useState(false);
  const load = () => api("/vitals/summary").then(() => {}).catch(() => {});
  useEffect(() => { api("/auth/me").then(m => api(`/patients/${m.id}/vitals?kind=${kind}`)).then(setRows); load(); }, [kind]);
  async function save() {
    const r = await api("/vitals", { body: { kind, value: parseFloat(v), value2: kind === "bp" ? parseFloat(v2) : null } });
    setAlert(r.abnormal); setV(""); setV2(""); const m = await api("/auth/me"); setRows(await api(`/patients/${m.id}/vitals?kind=${kind}`));
  }
  return (<>
    <h1>{t("monitoring")}</h1>
    <div className="card">
      <label htmlFor="k">Type</label>
      <select id="k" value={kind} onChange={e => setKind(e.target.value)}>{["bp", "glucose", "heart_rate", "temperature", "weight", "spo2", "resp_rate"].map(k => <option key={k} value={k}>{k}</option>)}</select>
      <label htmlFor="v">{kind === "bp" ? "Systolic" : "Value"}</label><input id="v" inputMode="decimal" value={v} onChange={e => setV(e.target.value)} />
      {kind === "bp" && <><label htmlFor="v2">Diastolic</label><input id="v2" inputMode="decimal" value={v2} onChange={e => setV2(e.target.value)} /></>}
      <button className="primary" onClick={save}>{t("save")}</button>
      {alert && <p className="error" role="alert">⚠ {t("abnormal")}. If you feel unwell contact a clinician; if severe, call 112.</p>}
    </div>
    <div className="card" style={{ marginTop: 12 }}><Chart pts={rows.map(r => ({ v: r.value, ab: r.abnormal }))} />
      <a href="/api/v1/vitals/report.csv" onClick={async e => { e.preventDefault(); const r = await fetch("/api/v1/vitals/report.csv", { headers: { Authorization: `Bearer ${sessionStorage.getItem("mc_token")}` } }); const b = await r.blob(); const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = "vitals.csv"; a.click(); }}>Download report (CSV)</a></div>
  </>);
}
