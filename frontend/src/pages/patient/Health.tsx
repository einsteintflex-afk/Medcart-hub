import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api";
import type { Me } from "../../App";
import { Badge, Err, Section, Table, d, dt, useAction, useFetch } from "../../ui";
import { FileLink, FileUpload } from "../../files";

function Chart({ pts }: { pts: { v: number; v2?: number | null; ab: boolean }[] }) {
  if (pts.length < 2) return <p className="muted">Add at least two readings to see a chart.</p>;
  const w = 480, h = 140, all = pts.flatMap(p => [p.v, ...(p.v2 ? [p.v2] : [])]), min = Math.min(...all), max = Math.max(...all), span = max - min || 1;
  const X = (i: number) => 10 + i * ((w - 20) / (pts.length - 1)), Y = (v: number) => h - 12 - ((v - min) / span) * (h - 24);
  return <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`Trend from ${pts[0].v} to ${pts[pts.length - 1].v}`} style={{ width: "100%" }}>
    <polyline fill="none" stroke="#0e9aa7" strokeWidth="2" points={pts.map((p, i) => `${X(i)},${Y(p.v)}`).join(" ")} />
    {pts[0].v2 && <polyline fill="none" stroke="#0b2545" strokeWidth="2" strokeDasharray="4" points={pts.map((p, i) => `${X(i)},${Y(p.v2!)}`).join(" ")} />}
    {pts.map((p, i) => <circle key={i} cx={X(i)} cy={Y(p.v)} r="4" fill={p.ab ? "#b42318" : "#0e9aa7"} />)}</svg>;
}

export function Monitoring({ me }: { me: Me }) {
  const { t } = useTranslation();
  const [kind, setKind] = useState("bp"); const [days, setDays] = useState(30); const [v, setV] = useState(""); const [v2, setV2] = useState(""); const [alert, setAlert] = useState(false);
  const { data: rows, reload } = useFetch<any[]>(`/patients/${me.id}/vitals?kind=${kind}&days=${days}`, [kind, days]);
  const { data: wk, reload: r2 } = useFetch<any>("/vitals/summary?period=week"); const { data: mo, reload: r3 } = useFetch<any>("/vitals/summary?period=month");
  const act = useAction(() => { reload(); r2(); r3(); });
  const save = () => act.run(async () => { const r = await api("/vitals", { body: { kind, value: parseFloat(v), value2: kind === "bp" ? parseFloat(v2) : null } }); setAlert(r.abnormal); setV(""); setV2(""); });
  const download = async () => { const r = await fetch(`/api/v1/vitals/report.csv?days=${days}`, { headers: { Authorization: `Bearer ${sessionStorage.getItem("mc_token")}` } }); const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = "vitals.csv"; a.click(); };
  const Sum = ({ s, title }: { s: any; title: string }) => <div className="card"><b>{title}</b>{s && Object.keys(s).length ? <table><tbody>{Object.entries(s).map(([k, x]: any) => <tr key={k}><td>{k}</td><td>avg {x.avg}</td><td>{x.min}–{x.max} {x.unit}</td><td>{x.trend}</td><td>{x.abnormal_count > 0 && <Badge warn>{x.abnormal_count} abnormal</Badge>}</td></tr>)}</tbody></table> : <p className="muted">No readings.</p>}</div>;
  return (<>
    <h1>{t("monitoring")}</h1>
    <div className="card">
      <div className="grid"><div><label htmlFor="k">Type</label><select id="k" value={kind} onChange={e => setKind(e.target.value)}>{["bp", "glucose", "heart_rate", "temperature", "weight", "spo2", "resp_rate", "bmi"].map(k => <option key={k} value={k}>{k}</option>)}</select></div>
        <div><label htmlFor="v">{kind === "bp" ? "Systolic" : "Value"}</label><input id="v" inputMode="decimal" value={v} onChange={e => setV(e.target.value)} /></div>
        {kind === "bp" && <div><label htmlFor="v2">Diastolic</label><input id="v2" inputMode="decimal" value={v2} onChange={e => setV2(e.target.value)} /></div>}</div>
      <button className="primary" onClick={save} disabled={!v}>{t("save")}</button> <small className="muted">Bluetooth devices: coming soon (readings carry a source field).</small>
      {alert && <p className="error" role="alert">⚠ {t("abnormal")}. If you feel unwell contact a clinician; if severe, call 112.</p>}<Err msg={act.err} /></div>
    <Section title="Trend" action={<span><select aria-label="Range" style={{ width: "auto" }} value={days} onChange={e => setDays(+e.target.value)}><option value={7}>7 days</option><option value={30}>30 days</option><option value={90}>90 days</option></select> <button onClick={download}>⬇ CSV report</button></span>}>
      <div className="card"><Chart pts={(rows ?? []).map(r => ({ v: r.value, v2: r.value2, ab: r.abnormal }))} /></div></Section>
    <div className="grid"><Sum s={wk} title="Weekly summary" /><Sum s={mo} title="Monthly report" /></div>
  </>);
}

const CATS = ["history", "diagnosis", "medication", "allergy", "consultation", "prescription", "lab", "imaging", "admission", "surgery", "immunization", "note", "document"];
export function Records({ me }: { me: Me }) {
  const [cat, setCat] = useState(""); const { data: recs, reload } = useFetch<any[]>(`/patients/${me.id}/records${cat ? `?category=${cat}` : ""}`, [cat]);
  const { data: grants, reload: rg } = useFetch<any[]>("/access-grants"); const { data: log } = useFetch<any[]>("/access-log"); const { data: provs } = useFetch<any[]>("/providers");
  const [f, setF] = useState({ category: "diagnosis", title: "", body: "" }); const [doc, setDoc] = useState<{ key: string; name: string } | null>(null); const [g, setG] = useState({ provider_id: "", days: "30" }); const act = useAction(() => { reload(); rg(); });
  return (<>
    <h1>My health record</h1>
    <Section title="Add an entry"><div className="card"><div className="grid"><div><label htmlFor="c">Category</label><select id="c" value={f.category} onChange={e => setF({ ...f, category: e.target.value })}>{CATS.map(c => <option key={c}>{c}</option>)}</select></div>
      <div><label htmlFor="t">Title</label><input id="t" value={f.title} onChange={e => setF({ ...f, title: e.target.value })} /></div></div>
      <label htmlFor="b">Details</label><textarea id="b" rows={3} value={f.body} onChange={e => setF({ ...f, body: e.target.value })} />
      <FileUpload purpose="record" label="Attach document or photo" onUploaded={setDoc} /> {doc && <Badge>{doc.name}</Badge>}<br /><br />
      <button className="primary" disabled={!f.title} onClick={() => act.run(async () => { await api("/records", { body: { ...f, document_key: doc?.key ?? null } }); setF({ ...f, title: "", body: "" }); setDoc(null); })}>Save</button>
      <p className="muted">PDF, PNG or JPEG up to 10 MB. Files are encrypted at rest and only shared with professionals you approve.</p><Err msg={act.err} /></div></Section>
    <Section title="Records" action={<select aria-label="Filter" style={{ width: "auto" }} value={cat} onChange={e => setCat(e.target.value)}><option value="">All</option>{CATS.map(c => <option key={c}>{c}</option>)}</select>}>
      <Table rows={recs} cols={[{ head: "Date", cell: r => d(r.recorded_on) }, { head: "Type", cell: r => <Badge>{r.category}</Badge> }, { head: "Title", cell: r => <><b>{r.title}</b><div className="muted">{r.body}</div>{r.document_key && <FileLink fileKey={r.document_key} label="Open document" />}</> }]} /></Section>
    <Section title="Who can see my records"><div className="card">
      <div className="row"><select aria-label="Professional" style={{ flex: 1, margin: 0 }} value={g.provider_id} onChange={e => setG({ ...g, provider_id: e.target.value })}><option value="">Choose a professional…</option>{provs?.map(p => <option key={p.id} value={p.id}>{p.name} ({p.role})</option>)}</select>
        <select aria-label="Duration" style={{ width: "auto", margin: 0 }} value={g.days} onChange={e => setG({ ...g, days: e.target.value })}><option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option></select>
        <button className="primary" disabled={!g.provider_id} onClick={() => act.run(() => api("/access-grants", { body: { provider_id: +g.provider_id, categories: ["*"], days: +g.days } }))}>Share</button></div>
      {grants?.map(x => <div key={x.id} className="row" style={{ marginTop: 8 }}>👤 {x.provider_name} · until {x.expires_at ? d(x.expires_at) : "revoked only"} <button onClick={() => act.run(() => api(`/access-grants/${x.id}`, { method: "DELETE" }))}>Revoke</button></div>)}</div></Section>
    <Section title="Access history"><Table rows={log} cols={[{ head: "When", cell: r => dt(r.at) }, { head: "Action", cell: r => r.action }, { head: "By user", cell: r => r.actor_id === me.id ? "You" : `#${r.actor_id}` }]} /></Section>
  </>);
}

export function Medications() {
  const { data: meds, reload } = useFetch<any[]>("/medications"); const [f, setF] = useState({ name: "", dose: "", times: "08:00", remaining: "" });
  const [warn, setWarn] = useState<any[]>([]); const [chk, setChk] = useState(""); const [res, setRes] = useState<any>(null); const act = useAction(reload);
  const add = () => act.run(async () => { const r = await api("/medications", { body: { name: f.name, dose: f.dose, times_of_day: f.times.split(",").map(s => s.trim()), remaining_doses: f.remaining ? +f.remaining : null } }); setWarn(r.interaction_warnings); setF({ name: "", dose: "", times: "08:00", remaining: "" }); });
  return (<>
    <h1>My medications</h1>
    <Section title="Add medication"><div className="card"><div className="grid">
      <div><label htmlFor="mn">Name</label><input id="mn" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></div>
      <div><label htmlFor="md">Dose</label><input id="md" value={f.dose} onChange={e => setF({ ...f, dose: e.target.value })} /></div>
      <div><label htmlFor="mt">Reminder times (comma separated)</label><input id="mt" value={f.times} onChange={e => setF({ ...f, times: e.target.value })} /></div>
      <div><label htmlFor="mr">Doses remaining</label><input id="mr" inputMode="numeric" value={f.remaining} onChange={e => setF({ ...f, remaining: e.target.value })} /></div></div>
      <button className="primary" disabled={!f.name} onClick={add}>Add</button>
      {warn.map((w, i) => <p key={i} className="error" role="alert">⚠ {w.severity}: {w.drugs.join(" + ")} — {w.note}. Ask a pharmacist before taking both.</p>)}<Err msg={act.err} /></div></Section>
    <Section title="Current & past"><Table rows={meds} cols={[{ head: "Medicine", cell: r => <b>{r.name}</b> }, { head: "Dose", cell: r => r.dose ?? "—" }, { head: "Reminders", cell: r => r.times_of_day.join(", ") || "—" },
      { head: "Left", cell: r => <>{r.remaining_doses ?? "—"} {r.refill_soon && <Badge warn>refill soon</Badge>}</> },
      { head: "", cell: r => <button onClick={() => act.run(() => api(`/medications/${r.id}`, { method: "PATCH", body: { active: !r.active } }))}>{r.active ? "Stop" : "Resume"}</button> }]} /></Section>
    <Section title="Check interactions"><div className="card"><input aria-label="Drugs" placeholder="e.g. warfarin, aspirin" value={chk} onChange={e => setChk(e.target.value)} />
      <button onClick={() => api(`/medications/interactions?drugs=${encodeURIComponent(chk)}`).then(setRes)}>Check</button>
      {res && <>{res.results.length ? res.results.map((r: any, i: number) => <p key={i}><Badge warn>{r.severity}</Badge> {r.drugs.join(" + ")}: {r.note}</p>) : <p>No known interaction in our limited list.</p>}<small className="muted">{res.disclaimer}</small></>}</div></Section>
  </>);
}

export function Labs() {
  const { data: labs, reload } = useFetch<any[]>("/lab-requests"); const { data: facs } = useFetch<any[]>("/facilities?kind=laboratory");
  const [tests, setTests] = useState(""); const [fac, setFac] = useState(""); const act = useAction(reload);
  return (<>
    <h1>Laboratory</h1>
    <Section title="Request tests"><div className="card"><label htmlFor="lt">Tests (comma separated)</label><input id="lt" value={tests} onChange={e => setTests(e.target.value)} placeholder="Full blood count, Malaria RDT" />
      <label htmlFor="lf">Laboratory / diagnostic centre</label><select id="lf" value={fac} onChange={e => setFac(e.target.value)}><option value="">Any</option>{facs?.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}</select>
      <button className="primary" disabled={!tests} onClick={() => act.run(async () => { await api("/lab-requests", { body: { tests: tests.split(",").map(s => s.trim()).filter(Boolean), facility_id: fac ? +fac : null } }); setTests(""); })}>Request</button><Err msg={act.err} /></div></Section>
    <Section title="My requests & results"><Table rows={labs} cols={[{ head: "Tests", cell: r => r.tests.join(", ") }, { head: "Status", cell: r => <Badge>{r.status}</Badge> }, { head: "Result", cell: r => <>{r.result_text ?? "—"}{r.result_document_key && <FileLink fileKey={r.result_document_key} label="Open result file" />}</> }]} />
      <p className="muted">Results are saved to your health record. Ask your clinician or the AI assistant to explain them.</p></Section>
  </>);
}
