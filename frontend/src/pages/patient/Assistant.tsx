import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, postForm, speakText } from "../../api";
import { Err, useFetch } from "../../ui";

type Msg = { role: "user" | "assistant"; content: string; emergency?: boolean };
export default function Assistant() {
  const { t, i18n } = useTranslation();
  const [msgs, setMsgs] = useState<Msg[]>([]); const [text, setText] = useState(""); const [busy, setBusy] = useState(false); const [err, setErr] = useState(""); const end = useRef<HTMLDivElement>(null);
  const { data: caps } = useFetch<any>("/language/capabilities"); const lang = i18n.language; const c = caps?.languages?.[lang];
  const [rec, setRec] = useState<MediaRecorder | null>(null); const [note, setNote] = useState("");

  async function send(override?: string) {
    const content = (override ?? text).trim(); if (!content) return;
    const next: Msg[] = [...msgs, { role: "user", content }]; setMsgs(next); setText(""); setBusy(true); setErr("");
    try {
      const r = await api("/ai/chat", { body: { messages: next.map(({ role, content }) => ({ role, content })), language: lang } });
      setMsgs([...next, { role: "assistant", content: r.reply, emergency: r.emergency }]);
    } catch (e: any) { setErr(e.message); }
    setBusy(false); setTimeout(() => end.current?.scrollIntoView(), 50);
  }

  async function toggleRecord() {
    if (rec) { rec.stop(); return; }
    setErr(""); setNote("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream); const chunks: Blob[] = [];
      mr.ondataavailable = e => chunks.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach(tr => tr.stop()); setRec(null);
        const fd = new FormData(); fd.append("audio", new Blob(chunks, { type: mr.mimeType.split(";")[0] }), "voice.webm"); fd.append("lang", lang);
        try {
          const r = await postForm("/ai/transcribe", fd);
          if (r.low_confidence) setNote("I may not have heard you clearly. Please check the text below before sending.");
          if (r.emergency) setMsgs(m => [...m, { role: "assistant", content: r.emergency_message, emergency: true }]);
          setText(r.text);
        } catch (e: any) { setErr(e.message); }
      };
      mr.start(); setRec(mr);
    } catch { setErr("Please allow microphone access to speak your question."); }
  }

  async function speak(s: string) {
    try { const u = await speakText(s, lang); await new Audio(u).play(); }
    catch { // server speech unavailable for this language -> browser voice as a clearly-labelled fallback
      if ("speechSynthesis" in window) { const u = new SpeechSynthesisUtterance(s); u.lang = lang === "fat" ? "tw" : lang; speechSynthesis.speak(u); setNote("Using your device's voice. It may not pronounce this language well."); }
      else setErr("Spoken replies are not available in this language yet.");
    }
  }
  return (<>
    <h1>{t("assistant")}</h1>
    <p className="muted">General health information only — not a doctor. For emergencies call 112.</p>
    {msgs.map((m, i) => <div key={i} className={`msg ${m.role === "user" ? "user" : m.emergency ? "emergency" : "bot"}`} role={m.emergency ? "alert" : undefined}>
      {m.content}{m.role === "assistant" && <div><button onClick={() => speak(m.content)} aria-label={t("listen")}>🔊 {t("listen")}</button></div>}</div>)}
    <div ref={end} />
    <label htmlFor="q" className="sr">{t("askHealth")}</label>
    <textarea id="q" rows={3} value={text} placeholder={t("askHealth")} onChange={e => setText(e.target.value)} />
    <div className="row">
      <button className="primary" disabled={busy} onClick={() => send()}>{t("send")}</button>
      <button onClick={toggleRecord} disabled={!c?.stt} aria-pressed={!!rec} title={c?.stt ? "" : "Voice input is not yet available in this language"}>{rec ? "⏹ Stop recording" : "🎤 Speak"}</button>
      {caps && !c?.stt && <small className="muted">Voice input is not yet available in this language — please type.</small>}
    </div>
    {note && <p role="status" className="muted">{note}</p>}<Err msg={err} />
  </>);
}
