// Login und Sign-up mit Rollenwahl (Task 2.2, L 5.8). Anmeldung liefert ein JWT, danach geht es auf Home.
import { type FormEvent, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { type SignupRequest, authApi, useAuth } from "../api/client";

const ROLES: { key: SignupRequest["role"]; label: string }[] = [
  { key: "mitarbeiter", label: "Mitarbeiter" },
  { key: "chef", label: "Chef" },
  { key: "einkauf", label: "Einkauf" },
];

// Demo-Konten aus demo/seed.py (siehe demo/prompts.md)
const DEMO = [
  { label: "Anna (Einkauf)", email: "anna@demo.local" },
  { label: "Ben (Mitarbeiter)", email: "ben@demo.local" },
  { label: "Chef", email: "chef@demo.local" },
];
const DEMO_PASSWORD = "demo"; // PASSWORD in demo/seed.py

function useAfterLogin() {
  const navigate = useNavigate();
  const location = useLocation();
  const setAuth = useAuth((s) => s.setAuth);
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  return (r: Parameters<typeof setAuth>[0]) => {
    setAuth(r);
    navigate(from, { replace: true });
  };
}

export function LoginPage() {
  const token = useAuth((s) => s.token);
  const done = useAfterLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (token) return <Navigate to="/" replace />;

  async function login(e: string, p: string) {
    setBusy(true);
    setError(null);
    try {
      done(await authApi.login(e, p));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const onSubmit = (ev: FormEvent) => {
    ev.preventDefault();
    void login(email, password);
  };

  return (
    <div className="auth-card">
      <h1>Anmelden</h1>
      <form onSubmit={onSubmit}>
        <label>
          E-Mail
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required autoFocus />
        </label>
        <label>
          Passwort
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        {error && <div className="error-text">{error}</div>}
        <button className="primary" disabled={busy}>
          {busy ? "Anmelden …" : "Anmelden"}
        </button>
      </form>
      <p className="small muted">
        Noch kein Konto? <Link to="/signup">Registrieren</Link>
      </p>
      <div className="small muted">Demo-Konten:</div>
      <div className="demo-logins">
        {DEMO.map((d) => (
          <button key={d.email} type="button" disabled={busy} onClick={() => void login(d.email, DEMO_PASSWORD)}>
            {d.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function SignupPage() {
  const token = useAuth((s) => s.token);
  const done = useAfterLogin();
  const [form, setForm] = useState<SignupRequest>({ name: "", email: "", password: "", role: "mitarbeiter" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (token) return <Navigate to="/" replace />;

  const set = (k: keyof SignupRequest) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    if (form.password.length < 8) {
      setError("Das Passwort braucht mindestens 8 Zeichen");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      done(await authApi.signup(form));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-card">
      <h1>Registrieren</h1>
      <form onSubmit={onSubmit}>
        <label>
          Name
          <input value={form.name} onChange={set("name")} required autoFocus />
        </label>
        <label>
          E-Mail
          <input type="email" value={form.email} onChange={set("email")} autoComplete="username" required />
        </label>
        <label>
          Passwort (mindestens 8 Zeichen)
          <input type="password" value={form.password} onChange={set("password")} autoComplete="new-password" required />
        </label>
        <label>
          Rolle
          <select value={form.role} onChange={set("role")}>
            {ROLES.map((r) => (
              <option key={r.key} value={r.key}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        {error && <div className="error-text">{error}</div>}
        <button className="primary" disabled={busy}>
          {busy ? "Registrieren …" : "Registrieren"}
        </button>
      </form>
      <p className="small muted">
        Schon registriert? <Link to="/login">Anmelden</Link>
      </p>
    </div>
  );
}
