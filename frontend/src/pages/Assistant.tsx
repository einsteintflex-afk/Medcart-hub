import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api";

type Msg = { role: "user" | "assistant"; content: string; emergency?: boolean };
export default function Assistant() {
  const { t, i18n } = useTranslation();
  const [msgs, setMsgs] = useState<Msg[]>([]); const [text, setText] = useState(""); const [busy, setBusy] = useState(false); const end = useRef<HTMLDivElement>(null);

  async function send() {
    if (!text.trim()) return;
    const next: Msg[] = [...msgs, { role: "user", content: text }]; setMsgs(next); setText(""); setBusy(true);
    try {
      const r = await api("/ai/chat", { body: { messages: next.map(({ role, content }) => ({ role, content })), language: i18n.language } });
      setMsgs([...next, { role: "assistant", content: r.reply, emergency: r.emergency }]);
    } catch (e: any) { setMsgs([...next, { role: "assistant", content: e.message }]); }
    setBusy(false); setTimeout(() => end.current?.scrollIntoView(), 50);
  }
  // Browser TTS is a stop-gap; production uses a validated TTS vendor for Twi/Fante/Hausa.
  const speak = (s: string) => { const u = new SpeechSynthesisUtterance(s); u.lang = i18n.language === "fat" ? "tw" : i18n.language; speechSynthesis.speak(u); };
  return (<>
    <h1>{t("assistant")}</h1>
    {msgs.map((m, i) => <div key={i} className={`msg ${m.role === "user" ? "user" : m.emergency ? "emergency" : "bot"}`} role={m.emergency ? "alert" : undefined}>
      {m.content}{m.role === "assistant" && <div><button onClick={() => speak(m.content)} aria-label={t("listen")}>🔊 {t("listen")}</button></div>}</div>)}
    <div ref={end} />
    <label htmlFor="q" className="sr">{t("askHealth")}</label>
    <textarea id="q" rows={3} value={text} placeholder={t("askHealth")} onChange={e => setText(e.target.value)} />
    <button className="primary" disabled={busy} onClick={send}>{t("send")}</button>
    <p><small>This assistant gives general information only. It is not a doctor and cannot diagnose or prescribe.</small></p>
  </>);
}
