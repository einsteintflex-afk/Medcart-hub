import { useRef, useState } from "react";
import { fileUrl, uploadFile } from "./api";

/** File picker that uploads immediately and reports the stored key. Accepts PDF/images (and audio if `audio`). */
export function FileUpload({ purpose, extra, label = "Attach file", audio = false, onUploaded }:
  { purpose: string; extra?: Record<string, string | number>; label?: string; audio?: boolean; onUploaded: (f: { key: string; name: string }) => void }) {
  const ref = useRef<HTMLInputElement>(null); const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const accept = ".pdf,.png,.jpg,.jpeg" + (audio ? ",.mp3,.wav,.ogg,.webm,.m4a" : "");
  return (<span>
    <input ref={ref} type="file" accept={accept} aria-label={label} style={{ display: "none" }} onChange={async e => {
      const f = e.target.files?.[0]; if (!f) return; setErr(""); setBusy(true);
      try { onUploaded(await uploadFile(f, purpose, extra)); } catch (x: any) { setErr(x.message); }
      setBusy(false); if (ref.current) ref.current.value = "";
    }} />
    <button type="button" disabled={busy} onClick={() => ref.current?.click()}>📎 {busy ? "Uploading…" : label}</button>
    {err && <span className="error" role="alert"> {err}</span>}
  </span>);
}

/** Opens an access-controlled file in a new tab (or shows an image inline when `inline`). */
export function FileLink({ fileKey, label = "View attachment", inline = false }: { fileKey: string; label?: string; inline?: boolean }) {
  const [url, setUrl] = useState<string | null>(null); const [err, setErr] = useState("");
  const load = async () => { try { const u = await fileUrl(fileKey); if (inline) setUrl(u); else window.open(u, "_blank", "noopener"); } catch (e: any) { setErr(e.message); } };
  if (url) return <img src={url} alt="Attachment" style={{ maxWidth: "100%", borderRadius: 8 }} />;
  return <span><button type="button" onClick={load}>📄 {label}</button>{err && <span className="error"> {err}</span>}</span>;
}
