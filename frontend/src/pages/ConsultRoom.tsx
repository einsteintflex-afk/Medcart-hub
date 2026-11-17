import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ghs } from "../api";
import type { Me } from "../App";
import { Badge, Err, Section, dt, useAction, useFetch } from "../ui";

/** Shared consultation workspace: chat, patient rating, clinician notes / prescriptions / referral. */
export default function ConsultRoom({ me }: { me: Me }) {
  const { id } = useParams();
  const { data: c, reload } = useFetch<any>(`/consultations/${id}`);
  const [msgs, setMsgs] = useState<any[]>([]); const [text, setText] = useState(""); const end = useRef<HTMLDivElement>(null);
  const isPatient = me.role === "patient"; const open = c && ["accepted", "in_progress"].includes(c.status);
  const act = useAction(reload);
  const loadMsgs = () => api(`/consultations/${id}/messages`).then(m => { setMsgs(m); }).catch(() => {});
  useEffect(() => { loadMsgs(); const t = setInterval(loadMsgs, 5000); return () => clearInterval(t); }, [id]);
  useEffect(() => { end.current?.scrollIntoView(); }, [msgs.length]);

  const send = () => text.trim() && act.run(async () => { await api(`/consultations/${id}/messages`, { body: { body: text, language: me.preferred_language } }); setText(""); await loadMsgs(); });
  const [note, setNote] = useState(""); const [rec, setRec] = useState(""); const [fu, setFu] = useState("");
  const [rx, setRx] = useState({ drug: "", dose: "", frequency: "", duration: "", instructions: "" }); const [ref, setRef] = useState("");
  const [stars, setStars] = useState(5);
  if (!c) return <p>Loading…</p>;
  return (<>
    <h1>Consultation #{c.id} <Badge warn={c.status === "rejected" || c.status === "cancelled"}>{c.status}</Badge></h1>
    <p>With <b>{c.other_party}</b> · {c.channel} · {ghs(c.fee_pesewas)} {c.urgent && <Badge warn>urgent</Badge>}{c.interpretation_enabled && <Badge>translation on</Badge>}</p>
    <p className="muted">Reason: {c.concern}</p>
    {c.room_id && c.channel !== "text" && <div className="card">📹 {c.channel} room <code>{c.room_id}</code> — live audio/video infrastructure is not connected yet; use the chat below.</div>}
    <Section title="Messages"><div className="card" style={{ maxHeight: 360, overflow: "auto" }}>
      {msgs.map(m => <div key={m.id} className={`msg ${m.sender_id === me.id ? "user" : "bot"}`}>{m.body}
        {m.machine_translated && <div><small>🌐 {m.translation_notice}</small></div>}<div><small className="muted">{dt(m.created_at)}</small></div></div>)}
      <div ref={end} /></div>
      {open && <div className="row"><input style={{ flex: 1, margin: 0 }} aria-label="Message" value={text} onChange={e => setText(e.target.value)} onKeyDown={e => e.key === "Enter" && send()} /><button className="primary" onClick={send}>Send</button></div>}
      <Err msg={act.err} />
    </Section>
    {c.clinical_note && <Section title="Clinical summary"><div className="card"><b>Assessment</b><p>{c.clinical_note}</p><b>Recommendation</b><p>{c.recommendation}</p></div></Section>}
    {c.prescriptions.length > 0 && <Section title="Prescriptions">{c.prescriptions.map((p: any) => <div className="card" key={p.id}>{p.items.map((i: any, k: number) => <div key={k}><b>{i.drug}</b> {i.dose} · {i.frequency} · {i.duration} {i.instructions && `— ${i.instructions}`}</div>)}</div>)}</Section>}
    {!isPatient && open && <Section title="Document & conclude"><div className="card">
      <label htmlFor="n">Clinical assessment</label><textarea id="n" rows={4} value={note} onChange={e => setNote(e.target.value)} />
      <label htmlFor="r">Recommendation / next steps</label><textarea id="r" rows={3} value={rec} onChange={e => setRec(e.target.value)} />
      <label htmlFor="f">Schedule follow-up (optional)</label><input id="f" type="datetime-local" value={fu} onChange={e => setFu(e.target.value)} />
      <button className="primary" disabled={!note || !rec} onClick={() => act.run(() => api(`/consultations/${id}/complete`, { body: { clinical_note: note, recommendation: rec, follow_up_at: fu ? new Date(fu).toISOString().slice(0, 19) : null } }))}>Complete consultation</button></div>
      {me.role === "doctor" && <div className="card"><h3>Prescription</h3>
        {(["drug", "dose", "frequency", "duration", "instructions"] as const).map(k => <input key={k} aria-label={k} placeholder={k} value={rx[k]} onChange={e => setRx({ ...rx, [k]: e.target.value })} />)}
        <button onClick={() => act.run(() => api(`/consultations/${id}/prescriptions`, { body: { items: [rx] } }))}>Issue prescription</button> <small className="muted">Only available if an administrator has authorised you to prescribe.</small></div>}
      <div className="card"><h3>Refer</h3><input aria-label="Reason" placeholder="Reason for referral" value={ref} onChange={e => setRef(e.target.value)} />
        <button onClick={() => act.run(() => api(`/consultations/${id}/referrals`, { body: { reason: ref } }))}>Send referral</button></div></Section>}
    {isPatient && c.status === "completed" && <Section title="Rate this consultation"><div className="card"><select aria-label="Stars" value={stars} onChange={e => setStars(+e.target.value)}>{[5, 4, 3, 2, 1].map(n => <option key={n}>{n}</option>)}</select>
      <button onClick={() => act.run(() => api(`/consultations/${id}/rating`, { body: { stars } }))}>Submit rating</button></div></Section>}
  </>);
}
