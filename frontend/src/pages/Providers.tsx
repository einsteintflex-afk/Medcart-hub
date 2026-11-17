import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ghs } from "../api";

export default function Providers() {
  const [sp] = useSearchParams();
  const [role, setRole] = useState(sp.get("role") || ""); const [language, setLanguage] = useState(""); const [specialty, setSpecialty] = useState("");
  const [list, setList] = useState<any[]>([]); const [msg, setMsg] = useState("");
  useEffect(() => { const q = new URLSearchParams(Object.entries({ role, language, specialty }).filter(([, v]) => v)); api(`/providers?${q}`).then(setList); }, [role, language, specialty]);

  async function book(p: any) {
    setMsg("");
    try {
      const c = await api("/consultations", { body: { provider_id: p.id, channel: "text", concern: "Consultation request" } });
      if (c.next === "pay") {
        const pay = await api("/payments/checkout", { body: { purpose: "consultation", method: "mtn_momo", consultation_id: c.id }, headers: { "Idempotency-Key": crypto.randomUUID() } });
        setMsg(`Approve the ${ghs(pay.amount_pesewas)} payment on your phone. The doctor is notified once payment is verified.`);
      } else setMsg("Request sent.");
    } catch (e: any) { setMsg(e.message); }
  }
  return (<>
    <h1>Find a professional</h1>
    <div className="grid">
      <div><label htmlFor="r">Role</label><select id="r" value={role} onChange={e => setRole(e.target.value)} style={{ width: "100%" }}><option value="">All</option><option>doctor</option><option>pharmacist</option><option>nurse</option></select></div>
      <div><label htmlFor="l">Language</label><select id="l" value={language} onChange={e => setLanguage(e.target.value)} style={{ width: "100%" }}><option value="">Any</option>{["en", "tw", "ha", "fat", "fr", "es"].map(l => <option key={l}>{l}</option>)}</select></div>
      <div><label htmlFor="s">Specialty</label><input id="s" value={specialty} onChange={e => setSpecialty(e.target.value)} /></div>
    </div>
    {msg && <p role="status">{msg}</p>}
    <div className="grid">{list.map(p => <article className="card" key={p.id}>
      <h2 style={{ margin: 0 }}>{p.name}</h2><span className="badge">✔ Registration verified</span>
      <p>{p.role} · {p.specialty} · {p.years_experience} yrs · {p.languages.join(", ")}</p>
      <p>★ {p.rating || "–"} ({p.rating_count}) · {p.approved_contributions} approved contributions</p>
      <p><b>{ghs(p.fee_pesewas)}</b> per consultation</p><button className="primary" onClick={() => book(p)}>Book</button></article>)}</div>
  </>);
}
