import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";

export default function VerifyEmail() {
  const [sp] = useSearchParams(); const [token, setToken] = useState(sp.get("token") || ""); const [msg, setMsg] = useState(""); const [ok, setOk] = useState(false);
  const run = (t: string) => api("/auth/verify-email", { body: { token: t } }).then(() => { setOk(true); setMsg("Your email is verified. You can now log in."); }).catch(e => setMsg(e.message));
  const once = useRef(false);  // StrictMode runs effects twice in dev; the token is single-use
  useEffect(() => { if (sp.get("token") && !once.current) { once.current = true; run(sp.get("token")!); } }, []);
  return <div className="card" style={{ maxWidth: 460, margin: "0 auto" }}><h1>Verify your email</h1>
    <label htmlFor="t">Verification code</label><input id="t" value={token} onChange={e => setToken(e.target.value)} /><button className="primary" onClick={() => run(token)}>Verify</button>
    {msg && <p role="status" className={ok ? "" : "error"}>{msg}</p>}{ok && <Link className="primary" to="/login">Log in</Link>}</div>;
}
