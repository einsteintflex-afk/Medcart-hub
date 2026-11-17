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
