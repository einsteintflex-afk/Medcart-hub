import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ghs, startPayment } from "../../api";
import { Badge, Err, Section, Table, dt, useAction, useFetch } from "../../ui";

export function Consult() {
  const [sp] = useSearchParams();
  const [f, setF] = useState({ role: sp.get("role") || "", language: "", specialty: "", min_experience: "", min_rating: "", sort: "experience" });
  const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v) as [string, string][]);
  const { data: list } = useFetch<any[]>(`/providers?${q}`, [q.toString()]);
  const { data: mine, reload } = useFetch<any[]>("/consultations");
  const [sel, setSel] = useState<any>(null); const [form, setForm] = useState({ channel: "text", concern: "", urgent: false, share_records: false, interpretation_enabled: false, language: "en" });
  const act = useAction(reload); const [msg, setMsg] = useState("");
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  const book = () => act.run(async () => {
    const c = await api("/consultations", { body: { provider_id: sel.id, ...form } });
    if (c.next === "pay") setMsg(await startPayment({ purpose: "consultation", method: "mtn_momo", consultation_id: c.id })); else setMsg("Request sent.");
    setSel(null);
  });
  return (<>
    <h1>Consultations</h1>
    <Section title="My consultations"><Table rows={mine} cols={[{ head: "#", cell: r => <Link to={`/app/consult/${r.id}`}>#{r.id}</Link> }, { head: "Channel", cell: r => r.channel },
      { head: "Status", cell: r => <Badge>{r.status}</Badge> }, { head: "Fee", cell: r => ghs(r.fee_pesewas) },
      { head: "", cell: r => r.status === "awaiting_payment" && <button onClick={() => act.run(async () => { setMsg(await startPayment({ purpose: "consultation", method: "mtn_momo", consultation_id: r.id })); })}>Pay now</button> }]} /></Section>
    {msg && <p role="status">{msg}</p>}<Err msg={act.err} />
    <Section title="Find a professional">
      <div className="grid">
        <div><label htmlFor="fr">Type</label><select id="fr" value={f.role} onChange={set("role")}><option value="">All</option><option>doctor</option><option>pharmacist</option><option>nurse</option></select></div>
        <div><label htmlFor="fl">Language</label><select id="fl" value={f.language} onChange={set("language")}><option value="">Any</option>{["en", "tw", "ha", "fat", "fr", "es"].map(l => <option key={l}>{l}</option>)}</select></div>
        <div><label htmlFor="fs">Specialty</label><input id="fs" value={f.specialty} onChange={set("specialty")} /></div>
        <div><label htmlFor="fe">Min. years experience</label><input id="fe" inputMode="numeric" value={f.min_experience} onChange={set("min_experience")} /></div>
        <div><label htmlFor="fm">Min. rating</label><select id="fm" value={f.min_rating} onChange={set("min_rating")}><option value="">Any</option>{[3, 4, 4.5].map(n => <option key={n}>{n}</option>)}</select></div>
        <div><label htmlFor="so">Sort by</label><select id="so" value={f.sort} onChange={set("sort")}><option value="experience">Experience</option><option value="rating">Rating</option></select></div>
      </div>
      <div className="grid">{list?.map(p => <article className="card" key={p.id}>
        <h3 style={{ margin: 0 }}>{p.name}</h3><Badge>✔ Registration verified</Badge>
        <p>{p.role} · {p.specialty || "General"} · {p.years_experience} yrs<br />🗣 {p.languages.join(", ")} · ★ {p.rating || "–"} ({p.rating_count})<br />📝 {p.approved_contributions} approved contributions</p>
        <p><b>{ghs(p.fee_pesewas)}</b> per consultation</p><button className="primary" onClick={() => setSel(p)}>Request</button></article>)}</div>
      {list?.length === 0 && <p className="muted">No verified professionals match these filters.</p>}
    </Section>
    {sel && <div className="card" role="dialog" aria-label="Request consultation"><h3>Request: {sel.name}</h3>
      <label htmlFor="ch">Channel</label><select id="ch" value={form.channel} onChange={e => setForm({ ...form, channel: e.target.value })}><option value="text">Text</option><option value="audio">Audio</option><option value="video">Video</option></select>
      <label htmlFor="cc">Describe your concern</label><textarea id="cc" rows={4} value={form.concern} onChange={e => setForm({ ...form, concern: e.target.value })} />
      <label><input type="checkbox" style={{ width: "auto" }} checked={form.urgent} onChange={e => setForm({ ...form, urgent: e.target.checked })} /> Urgent (not for emergencies — call 112)</label><br />
      <label><input type="checkbox" style={{ width: "auto" }} checked={form.share_records} onChange={e => setForm({ ...form, share_records: e.target.checked })} /> Share my health record with this professional</label><br />
      <label><input type="checkbox" style={{ width: "auto" }} checked={form.interpretation_enabled} onChange={e => setForm({ ...form, interpretation_enabled: e.target.checked })} /> Enable translation support (automated; labelled in chat)</label>
      <p>Fee: <b>{ghs(sel.fee_pesewas)}</b>{sel.fee_pesewas > 0 && " — paid separately from your subscription."}</p>
      <button className="primary" disabled={form.concern.length < 5} onClick={book}>{sel.fee_pesewas > 0 ? "Continue to payment" : "Send request"}</button> <button onClick={() => setSel(null)}>Cancel</button></div>}
  </>);
}

export function Appointments() {
  const { data: appts, reload } = useFetch<any[]>("/appointments"); const { data: provs } = useFetch<any[]>("/providers"); const { data: facs } = useFetch<any[]>("/facilities");
  const [f, setF] = useState({ target: "", starts_at: "", reason: "" }); const act = useAction(reload);
  const book = () => act.run(async () => {
    const [kind, id] = f.target.split(":");
    await api("/appointments", { body: { [kind === "p" ? "provider_id" : "facility_id"]: +id, starts_at: new Date(f.starts_at).toISOString().slice(0, 19), reason: f.reason } });
    setF({ target: "", starts_at: "", reason: "" });
  });
  return (<>
    <h1>Appointments</h1>
    <Section title="Book"><div className="card">
      <label htmlFor="tg">With</label><select id="tg" value={f.target} onChange={e => setF({ ...f, target: e.target.value })}><option value="">Choose…</option>
        <optgroup label="Professionals">{provs?.map(p => <option key={p.id} value={`p:${p.id}`}>{p.name} ({p.role}, {p.specialty})</option>)}</optgroup>
        <optgroup label="Clinics, hospitals & diagnostic centres">{facs?.map(x => <option key={x.id} value={`f:${x.id}`}>{x.name} ({x.kind})</option>)}</optgroup></select>
      <label htmlFor="dt">Date & time</label><input id="dt" type="datetime-local" value={f.starts_at} onChange={e => setF({ ...f, starts_at: e.target.value })} />
      <label htmlFor="rs">Reason</label><input id="rs" value={f.reason} onChange={e => setF({ ...f, reason: e.target.value })} />
      <button className="primary" disabled={!f.target || !f.starts_at} onClick={book}>Book appointment</button><Err msg={act.err} /></div></Section>
    <Section title="My appointments"><Table rows={appts} cols={[{ head: "When", cell: r => dt(r.starts_at) }, { head: "Reason", cell: r => r.reason ?? "—" }, { head: "Status", cell: r => <Badge warn={r.status === "cancelled"}>{r.status}</Badge> },
      { head: "", cell: r => r.status !== "cancelled" && <><button onClick={() => { const n = prompt("New date & time (YYYY-MM-DD HH:MM)"); if (n) act.run(() => api(`/appointments/${r.id}`, { method: "PATCH", body: { action: "reschedule", starts_at: new Date(n).toISOString().slice(0, 19) } })); }}>Reschedule</button>{" "}
        <button onClick={() => act.run(() => api(`/appointments/${r.id}`, { method: "PATCH", body: { action: "cancel" } }))}>Cancel</button></> }]} /></Section>
  </>);
}
