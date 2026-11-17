import { useEffect, useRef, useState } from "react";
import { api } from "../api";

/** Peer-to-peer audio/video call. Media is encrypted end to end (DTLS-SRTP); our server only relays signalling. */
export default function Call({ cid, video }: { cid: number; video: boolean }) {
  const [state, setState] = useState<"idle" | "connecting" | "waiting" | "live" | "ended">("idle"); const [err, setErr] = useState("");
  const [muted, setMuted] = useState(false); const [camOff, setCamOff] = useState(false);
  const local = useRef<HTMLVideoElement>(null); const remote = useRef<HTMLVideoElement>(null);
  const pc = useRef<RTCPeerConnection | null>(null); const ws = useRef<WebSocket | null>(null); const stream = useRef<MediaStream | null>(null); const pending = useRef<RTCIceCandidateInit[]>([]);

  const cleanup = () => { ws.current?.close(); pc.current?.close(); stream.current?.getTracks().forEach(t => t.stop()); ws.current = null; pc.current = null; stream.current = null; };
  useEffect(() => cleanup, []);

  async function start() {
    setErr(""); setState("connecting");
    try {
      const t = await api(`/consultations/${cid}/call-ticket`, { method: "POST" });
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true, video });
      if (local.current) local.current.srcObject = stream.current;
      const conn = new RTCPeerConnection({ iceServers: t.ice_servers }); pc.current = conn;
      stream.current.getTracks().forEach(tr => conn.addTrack(tr, stream.current!));
      conn.ontrack = e => { if (remote.current) remote.current.srcObject = e.streams[0]; };
      const sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${t.ws_path}?ticket=${encodeURIComponent(t.ticket)}`); ws.current = sock;
      const send = (type: string, data?: unknown) => sock.readyState === 1 && sock.send(JSON.stringify({ type, data }));
      conn.onicecandidate = e => e.candidate && send("ice", e.candidate);
      conn.onconnectionstatechange = () => { if (conn.connectionState === "connected") setState("live"); if (["failed", "disconnected"].includes(conn.connectionState)) { setErr("Connection lost."); setState("ended"); } };
      sock.onclose = ev => { if (ev.code >= 4400) setErr("The call is not available (consultation closed or session expired)."); };
      sock.onmessage = async ev => {
        const m = JSON.parse(ev.data);
        if (m.type === "joined") setState(m.peers > 0 ? "connecting" : "waiting");
        else if (m.type === "peer-joined") { const offer = await conn.createOffer(); await conn.setLocalDescription(offer); send("offer", offer); }
        else if (m.type === "offer") { await conn.setRemoteDescription(m.data); for (const c of pending.current) await conn.addIceCandidate(c); pending.current = []; const ans = await conn.createAnswer(); await conn.setLocalDescription(ans); send("answer", ans); }
        else if (m.type === "answer") { await conn.setRemoteDescription(m.data); for (const c of pending.current) await conn.addIceCandidate(c); pending.current = []; }
        else if (m.type === "ice") { if (conn.remoteDescription) await conn.addIceCandidate(m.data); else pending.current.push(m.data); }
        else if (m.type === "peer-left") { setState("waiting"); }
      };
    } catch (e: any) { setErr(e.name === "NotAllowedError" ? "Please allow microphone" + (video ? " and camera" : "") + " access to join the call." : e.message); cleanup(); setState("idle"); }
  }
  const hangup = () => { cleanup(); setState("ended"); };
  const toggle = (kind: "audio" | "video") => { stream.current?.getTracks().filter(t => t.kind === kind).forEach(t => (t.enabled = !t.enabled)); kind === "audio" ? setMuted(!muted) : setCamOff(!camOff); };

  return (<div className="card" aria-label="Call">
    <b>{video ? "📹 Video call" : "📞 Audio call"}</b> <span className="muted" data-testid="call-state">{state}</span>
    {state === "idle" || state === "ended" ? <p><button className="primary" onClick={start}>{state === "ended" ? "Rejoin call" : "Join call"}</button></p> :
      <p><button onClick={() => toggle("audio")}>{muted ? "🔇 Unmute" : "🎤 Mute"}</button> {video && <button onClick={() => toggle("video")}>{camOff ? "📷 Camera on" : "📷 Camera off"}</button>} <button className="danger" onClick={hangup}>Hang up</button></p>}
    {state === "waiting" && <p role="status">Waiting for the other person to join…</p>}
    <div className="row" style={{ alignItems: "flex-start" }}>
      <video ref={remote} autoPlay playsInline data-testid="remote-video" style={{ width: video ? 360 : 1, maxWidth: "100%", background: "#0b2545", borderRadius: 10 }} />
      <video ref={local} autoPlay playsInline muted data-testid="local-video" style={{ width: video ? 140 : 1, background: "#222", borderRadius: 10 }} />
    </div>
    {err && <p className="error" role="alert">{err}</p>}
    <small className="muted">Calls connect directly between you and the other person. If you are on a restricted network the call may not connect.</small>
  </div>);
}
