import i18n from "i18next";
import { initReactI18next } from "react-i18next";

// NOTE: Twi (tw), Fante (fat) and Hausa (ha) strings below are first-pass drafts and MUST be reviewed by
// native-speaking clinicians/translators before launch. Missing keys fall back to English.
const en = {
  appName: "MedCart", login: "Log in", register: "Create account", email: "Email", password: "Password", logout: "Log out",
  welcome: "Welcome, {{name}}", language: "Language", subscription: "Subscription", active: "Active", inactive: "Not active",
  subscribe: "Subscribe — GH₵60/month", talkPharmacist: "Talk to a pharmacist", consultDoctor: "Consult a doctor",
  doctorFee: "Doctor consultations are GH₵200 each and are paid separately from the subscription.",
  monitoring: "Health monitoring", assistant: "AI health assistant", facilities: "Nearby facilities", emergency: "Emergency",
  records: "My records", medications: "My medications", labs: "Lab results", appointments: "Appointments",
  send: "Send", askHealth: "Describe how you feel…", listen: "Listen", translated: "Automatically translated — confirm important information with your clinician.",
  emergencyBanner: "Not a substitute for emergency services. In an emergency call 112.", save: "Save",
  bp: "Blood pressure", glucose: "Blood glucose", heart_rate: "Heart rate", abnormal: "Outside usual range",
  verified: "Verified", pending: "Pending verification", credits: "Contribution credits", ledger: "Credit ledger",
};
const fr: typeof en = { ...en, login: "Se connecter", register: "Créer un compte", email: "E-mail", password: "Mot de passe", logout: "Déconnexion",
  welcome: "Bienvenue, {{name}}", language: "Langue", subscription: "Abonnement", active: "Actif", inactive: "Inactif",
  subscribe: "S'abonner — 60 GH₵/mois", talkPharmacist: "Parler à un pharmacien", consultDoctor: "Consulter un médecin",
  doctorFee: "Les consultations médicales coûtent 200 GH₵ chacune, payées séparément de l'abonnement.",
  monitoring: "Suivi de santé", assistant: "Assistant santé IA", facilities: "Établissements proches", emergency: "Urgence",
  records: "Mon dossier", medications: "Mes médicaments", labs: "Résultats d'analyses", appointments: "Rendez-vous", send: "Envoyer",
  askHealth: "Décrivez comment vous vous sentez…", listen: "Écouter", translated: "Traduit automatiquement — confirmez les informations importantes avec votre soignant.",
  emergencyBanner: "Ne remplace pas les services d'urgence. En cas d'urgence, appelez le 112.", save: "Enregistrer",
  bp: "Tension artérielle", glucose: "Glycémie", heart_rate: "Fréquence cardiaque", abnormal: "Hors de la plage habituelle" };
const es: typeof en = { ...en, login: "Iniciar sesión", register: "Crear cuenta", email: "Correo", password: "Contraseña", logout: "Salir",
  welcome: "Bienvenido, {{name}}", language: "Idioma", subscription: "Suscripción", active: "Activa", inactive: "Inactiva",
  subscribe: "Suscribirse — GH₵60/mes", talkPharmacist: "Hablar con un farmacéutico", consultDoctor: "Consultar a un médico",
  doctorFee: "Las consultas médicas cuestan GH₵200 cada una y se pagan aparte de la suscripción.",
  monitoring: "Control de salud", assistant: "Asistente de salud IA", facilities: "Centros cercanos", emergency: "Emergencia",
  records: "Mi historial", medications: "Mis medicamentos", labs: "Resultados de laboratorio", appointments: "Citas", send: "Enviar",
  askHealth: "Describa cómo se siente…", listen: "Escuchar", translated: "Traducido automáticamente: confirme la información importante con su profesional.",
  emergencyBanner: "No sustituye a los servicios de emergencia. En una emergencia llame al 112.", save: "Guardar",
  bp: "Presión arterial", glucose: "Glucosa en sangre", heart_rate: "Frecuencia cardíaca", abnormal: "Fuera del rango habitual" };
const tw: Partial<typeof en> = { login: "Hyɛ mu", register: "Yɛ akɔnt", email: "Email", password: "Password", logout: "Fi mu", language: "Kasa",
  talkPharmacist: "Kasa kyerɛ ɔduruyɛfoɔ", consultDoctor: "Hu ɔdɔkota", emergency: "Ɔhaw ntɛm", send: "Soma", save: "Kora" };
const fat: Partial<typeof en> = { login: "Hyɛ mu", register: "Yɛ akɔnt", logout: "Fi mu", language: "Kasa", emergency: "Ɔhaw ntsiir", send: "Tsie", save: "Kora" };
const ha: Partial<typeof en> = { login: "Shiga", register: "Ƙirƙiri asusu", email: "Imel", password: "Kalmar sirri", logout: "Fita",
  language: "Harshe", talkPharmacist: "Yi magana da likitan magunguna", consultDoctor: "Ga likita", emergency: "Gaggawa", send: "Aika", save: "Ajiye" };

export const LANGS = [["en", "English"], ["tw", "Twi"], ["ha", "Hausa"], ["fat", "Fante"], ["fr", "Français"], ["es", "Español"]] as const;
i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, fr: { translation: fr }, es: { translation: es }, tw: { translation: tw }, fat: { translation: fat }, ha: { translation: ha } },
  lng: localStorage.getItem("mc_lang") || "en", fallbackLng: "en", interpolation: { escapeValue: false },
});
export default i18n;
