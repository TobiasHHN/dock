// Login und Sign-up mit Rollenwahl (Task 2.2, L 5.8). Anmeldung liefert ein JWT, danach geht es auf Home.
import { type FormEvent, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { type SignupRequest, authApi, useAuth } from "../api/client";
import { Icon } from "../ui/icons";

const ROLES: { key: SignupRequest["role"]; label: string }[] = [
  { key: "mitarbeiter", label: "Mitarbeiter" },
  { key: "chef", label: "Chef" },
  { key: "einkauf", label: "Einkauf" },
];

// Demo-Konten aus demo/seed.py (siehe demo/prompts.md)
const DEMO = [
  { name: "Anna", role: "Einkauf", email: "anna@demo.local" },
  { name: "Ben", role: "Mitarbeiter", email: "ben@demo.local" },
  { name: "Chef", role: "Chef", email: "chef@demo.local" },
];

/** Gemeinsamer Rahmen: Marke, Karte, Link darunter. */
function AuthLayout({ title, subtitle, children, footer }: {
  title: string; subtitle: string; children: React.ReactNode; footer: React.ReactNode;
}) {
  return (
    <div className="auth-wrap">
      <div className="auth-brand brand" translate="no">dock</div>
      <main className="auth-card">
        <div className="auth-head">
          <h1>{title}</h1>
          <p className="muted">{subtitle}</p>
        </div>
        {children}
      </main>
      <p className="auth-foot muted">{footer}</p>
    </div>
  );
}

function FormError({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="form-error" role="alert">
      <Icon name="alert" />
      <span>{error}</span>
    </div>
  );
}
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
    <AuthLayout
      title="Anmelden"
      subtitle="Willkommen zurück. Melde dich mit deinem Konto an."
      footer={<>Noch kein Konto? <Link to="/signup">Registrieren</Link></>}
    >
      <form onSubmit={onSubmit}>
        <label>
          E-Mail
          <input type="email" name="email" placeholder="name@firma.de" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" spellCheck={false} required autoFocus />
        </label>
        <label>
          Passwort
          <input type="password" name="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        <FormError error={error} />
        <button className="primary block" disabled={busy}>
          {busy ? "Anmelden …" : "Anmelden"}
        </button>
      </form>
      <div className="demo">
        <span className="eyebrow" id="demo-label">Demo-Konten</span>
        <div className="demo-grid" role="group" aria-labelledby="demo-label">
          {DEMO.map((d) => (
            <button
              key={d.email}
              type="button"
              className="demo-card"
              disabled={busy}
              onClick={() => void login(d.email, DEMO_PASSWORD)}
              aria-label={`Als ${d.name} (${d.role}) anmelden`}
            >
              <span className="avatar" aria-hidden="true">{d.name[0]}</span>
              <span className="demo-name">{d.name}</span>
              <span className="demo-role">{d.role}</span>
            </button>
          ))}
        </div>
      </div>
    </AuthLayout>
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
    <AuthLayout
      title="Registrieren"
      subtitle="Lege ein Konto an und wähle deine Rolle."
      footer={<>Schon registriert? <Link to="/login">Anmelden</Link></>}
    >
      <form onSubmit={onSubmit}>
        <label>
          Name
          <input name="name" value={form.name} onChange={set("name")} autoComplete="name" required autoFocus />
        </label>
        <label>
          E-Mail
          <input type="email" name="email" placeholder="name@firma.de" value={form.email} onChange={set("email")} autoComplete="username" spellCheck={false} required />
        </label>
        <label>
          Passwort
          <input type="password" name="password" value={form.password} onChange={set("password")} autoComplete="new-password" aria-describedby="pw-hint" required />
          <span className="hint" id="pw-hint">Mindestens 8 Zeichen</span>
        </label>
        <label>
          Rolle
          <select name="role" value={form.role} onChange={set("role")}>
            {ROLES.map((r) => (
              <option key={r.key} value={r.key}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <FormError error={error} />
        <button className="primary block" disabled={busy}>
          {busy ? "Registrieren …" : "Registrieren"}
        </button>
      </form>
    </AuthLayout>
  );
}
