const BASE = "/api/v1";
let access = sessionStorage.getItem("mc_token") || "";
export const setToken = (t: string) => { access = t; t ? sessionStorage.setItem("mc_token", t) : sessionStorage.removeItem("mc_token"); };
export const hasToken = () => !!access;

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; headers?: Record<string, string> } = {}): Promise<T> {
  const res = await fetch(BASE + path, {
    method: opts.method ?? (opts.body ? "POST" : "GET"),
    headers: { "Content-Type": "application/json", ...(access ? { Authorization: `Bearer ${access}` } : {}), ...opts.headers },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) setToken("");
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed");
  return data;
}
/** Multipart upload (browser sets the boundary, so no JSON content-type). */
export async function uploadFile(file: Blob, purpose: string, extra: Record<string, string | number> = {}, name = "upload"): Promise<{ key: string; name: string; content_type: string }> {
  const fd = new FormData();
  fd.append("file", file, (file as File).name || name); fd.append("purpose", purpose);
  Object.entries(extra).forEach(([k, v]) => fd.append(k, String(v)));
  const res = await fetch(BASE + "/files", { method: "POST", headers: access ? { Authorization: `Bearer ${access}` } : {}, body: fd });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Upload failed");
  return data;
}

/** Authenticated download -> blob URL (files are access-controlled, so plain <a href> can't be used). */
export async function fileUrl(key: string): Promise<string> {
  const res = await fetch(`${BASE}/files/${key}`, { headers: access ? { Authorization: `Bearer ${access}` } : {} });
  if (!res.ok) throw new Error("File not available");
  return URL.createObjectURL(await res.blob());
}

export async function postForm<T = any>(path: string, fd: FormData): Promise<T> {
  const res = await fetch(BASE + path, { method: "POST", headers: access ? { Authorization: `Bearer ${access}` } : {}, body: fd });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed");
  return data;
}

export async function speakText(text: string, language: string): Promise<string> {
  const res = await fetch(`${BASE}/ai/speak`, { method: "POST", headers: { "Content-Type": "application/json", ...(access ? { Authorization: `Bearer ${access}` } : {}) }, body: JSON.stringify({ text, language }) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Speech unavailable");
  return URL.createObjectURL(await res.blob());
}

export const ghs = (pesewas: number) => `GH₵${(pesewas / 100).toFixed(2)}`;

/** Start a Paystack hosted checkout (MoMo/card). Returns a message when no redirect is possible (dev simulator). */
export async function startPayment(body: Record<string, unknown>): Promise<string> {
  const p = await api("/payments/checkout", { body, headers: { "Idempotency-Key": crypto.randomUUID() } });
  if (p.checkout_url?.startsWith("https://")) { window.location.href = p.checkout_url; return ""; }
  if (p.checkout_url?.startsWith("/simulator/")) {  // dev simulator only
    if (confirm(`DEV SIMULATOR: approve payment of ${ghs(p.amount_pesewas)}?`)) { await api(`/payments/dev/simulate/${p.reference}`, { method: "POST" }); window.location.reload(); }
    return "";
  }
  return `Payment ${p.reference} created for ${ghs(p.amount_pesewas)} (simulator mode: no checkout page).`;
}
