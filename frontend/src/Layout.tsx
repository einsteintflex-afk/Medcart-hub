import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { Me } from "./App";
import { useFetch } from "./ui";

type Item = [string, string];
export function navFor(role: string, t: (k: string) => string, status?: string): Item[] {
  if (role === "patient") return [["/app", "🏠 " + t("home")], ["/app/consult", "🩺 " + t("consultations")], ["/app/appointments", "📅 " + t("appointments")],
    ["/app/monitoring", "❤️ " + t("monitoring")], ["/app/records", "📁 " + t("records")], ["/app/medications", "💊 " + t("medications")], ["/app/labs", "🧪 " + t("labs")], ["/app/drugs", "💊 Drug information"],
    ["/app/facilities", "🏥 " + t("facilities")], ["/app/education", "📚 " + t("education")], ["/app/assistant", "🤖 " + t("assistant")],
    ["/app/billing", "💳 " + t("billing")], ["/app/notifications", "🔔 " + t("notifications")], ["/app/settings", "⚙️ " + t("settings")]];
  if (role === "admin") return [["/admin", "📊 Overview"], ["/admin/verification", "✅ Verification"], ["/admin/users", "👥 Users"], ["/admin/moderation", "📝 Moderation"],
    ["/admin/transactions", "💰 Transactions"], ["/admin/subscriptions", "🔁 Subscriptions"], ["/admin/consultations", "🩺 Consultations"], ["/admin/appointments", "📅 Appointments"],
    ["/admin/facilities", "🏥 Facilities"], ["/admin/labs", "🧪 Labs"], ["/admin/credits", "⭐ Credits"], ["/admin/complaints", "📣 Complaints"],
    ["/admin/interpreters", "🧑‍🤝‍🧑 Interpreters"], ["/admin/languages", "🌍 Languages"], ["/admin/reports", "📈 Reports"], ["/admin/audit", "🔍 Audit log"], ["/admin/settings", "⚙️ Settings"]];
  if (status && status !== "approved")  // unverified professionals can only manage their application
    return [["/pro", "🏠 Overview"], ["/pro/profile", "🪪 Profile & verification"], ["/pro/notifications", "🔔 Notifications"]];
  const base: Item[] = [["/pro", "🏠 Overview"]];
  if (role === "doctor" || role === "pharmacist") base.push(["/pro/consultations", "🩺 Consultations"]);
  if (role === "lab") base.push(["/pro/lab", "🧪 Lab queue"]);
  if (role === "facility_admin") base.push(["/pro/facility", "🏥 My facility"]);
  base.push(["/pro/appointments", "📅 Appointments"]);
  if (role !== "lab" && role !== "facility_admin") base.push(["/pro/patients", "👥 Patients"]);
  base.push(["/pro/availability", "🕒 Availability"], ["/pro/profile", "🪪 Profile & verification"], ["/pro/earnings", "💰 Earnings & billing"],
    ["/pro/contributions", "✍️ Contributions & credits"], ["/pro/notifications", "🔔 Notifications"]);
  return base;
}

export default function Layout({ me }: { me: Me }) {
  const { t } = useTranslation(); const [open, setOpen] = useState(false);
  const { data: notes } = useFetch<any[]>("/notifications");
  const unread = notes?.filter(n => !n.read).length ?? 0;
  return (
    <div className="shell">
      <button className="menu" aria-expanded={open} aria-controls="nav" onClick={() => setOpen(!open)}>☰ Menu {unread > 0 && <span className="badge warn">{unread}</span>}</button>
      <nav id="nav" className={open ? "open" : ""} aria-label="Main" onClick={() => setOpen(false)}>
        <div className="who">{me.full_name}<br /><small>{me.role}{me.verification_status && me.verification_status !== "approved" ? ` · ${me.verification_status}` : ""}</small></div>
        {navFor(me.role, t, me.verification_status).map(([to, label]) => <NavLink key={to} to={to} end={to === "/app" || to === "/pro" || to === "/admin"}>{label}</NavLink>)}
      </nav>
      <div className="content"><Outlet /></div>
    </div>
  );
}
