import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ghs } from "../api";
import type { Me } from "../App";
import { Badge, Err, Section, dt, useAction, useFetch } from "../ui";
import Call from "./Call";
import { FileLink, FileUpload } from "../files";

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

  const send = () => (text.trim() || att) && act.run(async () => { await api(`/consultations/${id}/messages`, { body: { body: text || "(attachment)", language: me.preferred_language, attachment_key: att?.key ?? null } }); setText(""); setAtt(null); await loadMsgs(); });
  const [note, setNote] = useState(""); const [rec, setRec] = useState(""); const [fu, setFu] = useState("");
  const [rx, setRx] = useState({ drug: "", dose: "", frequency: "", duration: "", instructions: "" }); const [ref, setRef] = useState("");
  const [stars, setStars] = useState(5); const [att, setAtt] = useState<{ key: string; name: string } | null>(null); const [tr, setTr] = useState<Record<number, any>>({}); const [tlang, setTlang] = useState(me.preferred_language || "en"); const [iMsg, setIMsg] = useState("");
  if (!c) return <p>Loading…</p>;
  return (<>
    <h1>Consultation #{c.id} <Badge warn={c.status === "rejected" || c.status === "cancelled"}>{c.status}</Badge></h1>
    <p>With <b>{c.other_party}</b> · {c.channel} · {ghs(c.fee_pesewas)} {c.urgent && <Badge warn>urgent</Badge>}{c.interpretation_enabled && <Badge>translation on</Badge>}</p>
    <p className="muted">Reason: {c.concern}</p>
    {open && c.channel !== "text" && <Call cid={c.id} video={c.channel === "video"} />}
    <Section title="Messages"><div className="card" style={{ maxHeight: 360, overflow: "auto" }}>
      {msgs.map(m => <div key={m.id} className={`msg ${m.sender_id === me.id ? "user" : "bot"}`}>{m.body}
        {m.attachment_key && <div><FileLink fileKey={m.attachment_key} inline={false} label="Open attachment" /></div>}
        {m.machine_translated && <div><small>🌐 {m.translation_notice}</small></div>}
        {c.interpretation_enabled && m.sender_id !== me.id && m.language !== tlang && <div><button onClick={() => api(`/consultations/${id}/messages/${m.id}/translate?target=${tlang}`, { method: "POST" }).then(r => setTr({ ...tr, [m.id]: r })).catch(e => setTr({ ...tr, [m.id]: { text: "", notice: e.message } }))}>🌐 Translate to {tlang}</button>{tr[m.id] && <div className="card" role="note" style={{ marginTop: 6, background: tr[m.id].needs_human_review ? "#fff4ed" : undefined }}>{tr[m.id].text}<br /><small>{tr[m.id].notice}</small></div>}</div>}<div><small className="muted">{dt(m.created_at)}</small></div></div>)}
      <div ref={end} /></div>
      {open && <div className="row"><input style={{ flex: 1, margin: 0 }} aria-label="Message" value={text} onChange={e => setText(e.target.value)} onKeyDown={e => e.key === "Enter" && send()} />
        <FileUpload purpose={isPatient ? "symptom_photo" : "consult"} extra={{ consultation_id: c.id }} label="Attach" audio onUploaded={setAtt} /> {att && <Badge>{att.name}</Badge>}<button className="primary" onClick={send}>Send</button></div>}
      {c.interpretation_enabled && <p><label>Translate incoming messages to <select style={{ width: "auto" }} aria-label="Translate to" value={tlang} onChange={e => setTlang(e.target.value)}>{["en", "tw", "ha", "fat", "fr", "es"].map(l => <option key={l}>{l}</option>)}</select></label> <small className="muted">Automated translation is labelled and never replaces an interpreter for dosages or emergencies.</small></p>}
      <p><button onClick={() => act.run(async () => { await api(`/consultations/${id}/interpreter`, { body: { language: tlang, reason: "Human interpreter requested" } }); setIMsg("Interpreter request sent. We will notify you."); })}>🧑‍🤝‍🧑 Request a human interpreter</button> {iMsg}</p>
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
