import { useEffect, useState } from "react";
import { api } from "../api";

export default function Emergency() {
  const [info, setInfo] = useState<any>(null); const [sent, setSent] = useState("");
  const load = (lat?: number, lon?: number) => api(`/emergency/info${lat !== undefined ? `?lat=${lat}&lon=${lon}` : ""}`).then(setInfo);
  useEffect(() => { load(); }, []);
  const share = () => navigator.geolocation.getCurrentPosition(p => load(p.coords.latitude, p.coords.longitude));  // voluntary, per request
  return (<>
    <h1>🚑 Emergency</h1>
    {info && <>
      <a className="primary" href={`tel:${info.emergency_number}`} style={{ fontSize: "1.5rem" }}>Call {info.emergency_number}</a>
      <p><b>{info.disclaimer}</b></p>
      <h2>Warning signs — get help now</h2><ul>{info.warning_signs.map((s: string) => <li key={s}>{s}</li>)}</ul>
      <button onClick={share}>📍 Share my location to find the nearest emergency facility</button>
      <button onClick={() => api("/emergency/notify-contact", { body: {} }).then(() => setSent("Your emergency contact was notified.")).catch(e => setSent(e.message))}>Notify my emergency contact</button> {sent}
      <h2>Nearby emergency facilities</h2>
      {info.nearby_emergency_facilities.map((f: any) => <div className="card" key={f.id}><b>{f.name}</b> {f.distance_km !== undefined && `· ${f.distance_km} km`}<br />{f.address} · {f.phone} {f.directions_url && <a href={f.directions_url}>Directions</a>}</div>)}
    </>}
  </>);
}
