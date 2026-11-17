import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, ghs, startPayment } from "../../api";
import { LANGS } from "../../i18n";
import { Badge, Err, Section, Table, d, dt, useAction, useFetch } from "../../ui";

export function Facilities() {
  const [kind, setKind] = useState(""); const [city, setCity] = useState(""); const [pos, setPos] = useState<[number, number] | null>(null);
  const q = new URLSearchParams(); if (kind) q.set("kind", kind); if (city) q.set("city", city); if (pos) { q.set("lat", String(pos[0])); q.set("lon", String(pos[1])); }
  const { data } = useFetch<any[]>(`/facilities?${q}`, [q.toString()]);
  return (<>
    <h1>Nearby facilities</h1>
    <div className="grid"><div><label htmlFor="k">Type</label><select id="k" value={kind} onChange={e => setKind(e.target.value)}><option value="">All</option>{["hospital", "clinic", "pharmacy", "laboratory", "diagnostic", "specialist"].map(k => <option key={k}>{k}</option>)}</select></div>
      <div><label htmlFor="c">City</label><input id="c" value={city} onChange={e => setCity(e.target.value)} /></div></div>
    <button onClick={() => navigator.geolocation.getCurrentPosition(p => setPos([p.coords.latitude, p.coords.longitude]))}>📍 Use my location (this search only, not stored)</button>
    <div className="grid" style={{ marginTop: 12 }}>{data?.map(f => <article className="card" key={f.id}><h3 style={{ margin: 0 }}>{f.name}</h3><Badge>{f.kind}</Badge> {f.has_emergency && <Badge warn>24h emergency</Badge>}
      <p>{f.address}{f.distance_km !== undefined && ` · ${f.distance_km} km`}<br />📞 {f.phone ?? "—"}</p>
      {f.services?.length > 0 && <p><b>Services:</b> {f.services.join(", ")}</p>}{f.specialties?.length > 0 && <p><b>Specialties:</b> {f.specialties.join(", ")}</p>}
      {f.hours && Object.keys(f.hours).length > 0 && <p><b>Hours:</b> {Object.entries(f.hours).map(([k, v]) => `${k} ${v}`).join(" · ")}</p>}
      {f.directions_url && <a className="primary" href={f.directions_url} target="_blank" rel="noreferrer">Directions</a>}</article>)}</div>
    {data?.length === 0 && <p className="muted">No facilities found.</p>}
  </>);
}

const TOPICS = ["disease", "prevention", "nutrition", "maternal", "child", "mental", "medication-safety", "chronic", "healthy-living", "research", "public-health"];
export function Education() {
  const { i18n } = useTranslation(); const [topic, setTopic] = useState(""); const [lang, setLang] = useState(i18n.language);
  const { data } = useFetch<any[]>(`/articles?${topic ? `topic=${topic}&` : ""}${lang ? `language=${lang}` : ""}`, [topic, lang]); const [open, setOpen] = useState<number | null>(null);
  return (<>
    <h1>Health education</h1>
    <div className="grid"><div><label htmlFor="t">Topic</label><select id="t" value={topic} onChange={e => setTopic(e.target.value)}><option value="">All</option>{TOPICS.map(t => <option key={t}>{t}</option>)}</select></div>
      <div><label htmlFor="l">Language</label><select id="l" value={lang} onChange={e => setLang(e.target.value)}><option value="">Any</option>{LANGS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}</select></div></div>
    {data?.map(a => <article className="card" key={a.id} style={{ marginBottom: 12 }}><h3 style={{ margin: 0 }}>{a.title}</h3>
      <p className="muted"><Badge>{a.kind}</Badge> {a.author.verified && <Badge>✔ verified professional</Badge>} {a.author.name} · {a.author.role}{a.author.specialty && ` · ${a.author.specialty}`}{a.author.qualifications && ` · ${a.author.qualifications}`} · {a.language} · {d(a.published_at)}</p>
      <p style={{ whiteSpace: "pre-wrap" }}>{open === a.id ? a.body : a.body.slice(0, 280) + (a.body.length > 280 ? "…" : "")}</p>
      {a.body.length > 280 && <button onClick={() => setOpen(open === a.id ? null : a.id)}>{open === a.id ? "Show less" : "Read more"}</button>}
      <p><small className="muted">General information reviewed by moderators; not personal medical advice.</small></p></article>)}
    {data?.length === 0 && <p className="muted">No published articles yet.</p>}
  </>);
}

export function Billing() {
  const { data: sub } = useFetch<any>("/payments/subscription"); const { data: hist, reload } = useFetch<any[]>("/payments/history"); const act = useAction(reload);
  const [method, setMethod] = useState("mtn_momo");
  return (<>
    <h1>Subscription & payments</h1>
    <div className="card"><b>Monthly subscription (GH₵60)</b>: <Badge warn={!sub?.active}>{sub?.active ? "Active" : "Not active"}</Badge> {sub?.expires_at && <>until {d(sub.expires_at)}</>}
      <p className="muted">{sub?.note}</p>
      <label htmlFor="m">Pay with</label><select id="m" value={method} onChange={e => setMethod(e.target.value)}><option value="mtn_momo">MTN Mobile Money</option><option value="telecel_cash">Telecel Cash</option><option value="at_money">AT Money</option><option value="card">Visa / Mastercard</option></select>
      <button className="primary" onClick={() => act.run(async () => { const m = await startPayment({ purpose: "patient_subscription", method }); if (m) alert(m); })}>{sub?.active ? "Renew early" : "Subscribe"}</button><Err msg={act.err} /></div>
    <Section title="Payment history & receipts"><Table rows={hist} cols={[{ head: "Date", cell: r => dt(r.created_at) }, { head: "For", cell: r => r.purpose.replace("_", " ") }, { head: "Amount", cell: r => ghs(r.amount_pesewas) },
      { head: "Status", cell: r => <Badge warn={r.status !== "succeeded"}>{r.status}</Badge> }, { head: "Receipt #", cell: r => <code>{r.reference}</code> }]} /></Section>
  </>);
}

export function Settings({ onLang }: { onLang: (l: string) => void }) {
  const { t, i18n } = useTranslation(); const { data: langs } = useFetch<any[]>("/languages");
  const [p, setP] = useState({ full_name: "", phone: "", city: "", region: "", emergency_contact_name: "", emergency_contact_phone: "", medical_history: "", allergies: "", preferred_channel: "email" });
  const [cmp, setCmp] = useState(""); const act = useAction(); const [ok, setOk] = useState("");
  const set = (k: string) => (e: any) => setP({ ...p, [k]: e.target.value });
  const save = () => act.run(async () => { const b: any = Object.fromEntries(Object.entries(p).filter(([, v]) => v)); if (b.allergies) b.allergies = b.allergies.split(",").map((s: string) => s.trim()); await api("/auth/me", { method: "PATCH", body: b }); setOk("Saved."); });
  return (<>
    <h1>{t("settings")}</h1>
    <Section title="Language & audio"><div className="card"><label htmlFor="lg">Interface language</label>
      <select id="lg" value={i18n.language} onChange={e => onLang(e.target.value)}>{LANGS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}</select>
      <table><thead><tr><th>Language</th><th>Speech-to-text</th><th>Spoken replies</th><th>Human interpreter</th></tr></thead><tbody>{langs?.map(l => <tr key={l.code}><td>{l.name}</td><td>{l.stt ? "✔" : "soon"}</td><td>{l.tts ? "✔" : "soon"}</td><td>{l.human_interpreter ? "✔" : "—"}</td></tr>)}</tbody></table>
      <small className="muted">Translations are automated and labelled. Never rely on them alone for dosage or emergency decisions.</small></div></Section>
    <Section title="Profile"><div className="card"><div className="grid">
      {([["full_name", "Full name"], ["phone", "Phone"], ["city", "City"], ["region", "Region"], ["emergency_contact_name", "Emergency contact name"], ["emergency_contact_phone", "Emergency contact phone"], ["allergies", "Allergies (comma separated)"]] as const)
        .map(([k, l]) => <div key={k}><label htmlFor={k}>{l}</label><input id={k} value={(p as any)[k]} onChange={set(k)} /></div>)}
      <div><label htmlFor="pc">Preferred communication</label><select id="pc" value={p.preferred_channel} onChange={set("preferred_channel")}><option value="email">Email</option><option value="sms">SMS</option></select></div></div>
      <label htmlFor="mh">Medical history</label><textarea id="mh" rows={3} value={p.medical_history} onChange={set("medical_history")} />
      <small className="muted">Only filled-in fields are updated.</small><br /><button className="primary" onClick={save}>{t("save")}</button> {ok}<Err msg={act.err} /></div></Section>
    <Section title="Report a problem"><div className="card"><textarea aria-label="Complaint" rows={3} value={cmp} onChange={e => setCmp(e.target.value)} />
      <button disabled={cmp.length < 10} onClick={() => act.run(async () => { await api("/complaints", { body: { body: cmp } }); setCmp(""); setOk("Complaint sent to our team."); })}>Send</button></div></Section>
  </>);
}

export function Notifications() {
  const { data, reload } = useFetch<any[]>("/notifications"); const act = useAction(reload);
  return (<>
    <h1>Notifications</h1><button onClick={() => act.run(() => api("/notifications/read-all", { method: "POST" }))}>Mark all read</button>
    {data?.map(n => <div className="card" key={n.id} style={{ marginTop: 8, borderLeft: n.read ? undefined : "5px solid var(--teal)" }}><b>{n.title}</b> <small className="muted">{dt(n.created_at)}</small><div>{n.body}</div>
      {!n.read && <button onClick={() => act.run(() => api(`/notifications/${n.id}/read`, { method: "POST" }))}>Mark read</button>}</div>)}
    {data?.length === 0 && <p className="muted">No notifications.</p>}
  </>);
}
