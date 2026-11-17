import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";

/** Landing page after Paystack checkout. The URL is NOT proof of payment: we ask our server, which asks Paystack. */
export default function PaymentComplete({ home }: { home: string }) {
  const [sp] = useSearchParams();
  const ref = sp.get("reference") || sp.get("trxref");
  const [status, setStatus] = useState("checking");
  useEffect(() => {
    if (!ref) { setStatus("missing"); return; }
    let tries = 0;
    const tick = async () => {
      try { const r = await api(`/payments/${ref}/verify`, { method: "POST" }); setStatus(r.status); if (r.status !== "pending" || ++tries > 10) return; }
      catch { setStatus("error"); return; }
      setTimeout(tick, 3000);
    };
    tick();
  }, [ref]);
  const msg: Record<string, string> = { checking: "Confirming your payment…", pending: "Still waiting for confirmation. You will be notified once it clears.",
    succeeded: "Payment confirmed. Thank you!", failed: "The payment did not go through. You have not been charged for this service.", missing: "No payment reference found.", error: "Could not confirm payment. Please check your payment history." };
  return <div className="card" role="status"><h1>Payment</h1><p>{msg[status] ?? status}</p><Link className="primary" to={home}>Back to dashboard</Link></div>;
}
