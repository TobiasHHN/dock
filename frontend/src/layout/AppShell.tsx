// Rahmen nach dem Login (Task 2.1): Kopfzeile mit Name, Rolle, Suche, Zählern und Verbindungsstatus.
// Verbindet den Sync-Store und abonniert dauerhaft `user:<id>` (T 5.7) und `workspace` (Listen, L 7.2).
import { useEffect } from "react";
import { Link, Navigate, Outlet, useLocation } from "react-router-dom";
import { authApi, useAuth } from "../api/client";
import { SearchBox } from "../search/SearchBox";
import { sync, useChannel, useSync } from "../sync/store";
import { toast } from "../ui/toasts";

const ROLE_LABEL: Record<string, string> = { einkauf: "Einkauf", mitarbeiter: "Mitarbeiter", chef: "Chef" };

/** Offene Aufgaben und ungelesene Benachrichtigungen aus dem Kanal `user:<id>`. */
export function useInboxCounts() {
  const user = useAuth((s) => s.user);
  const ch = useChannel(user ? `user:${user.id}` : null);
  const data = ch?.view;
  const tasks: { status?: string }[] = data?.tasks ?? [];
  const notes: { read_at?: string | null }[] = data?.notifications ?? [];
  return { tasks: tasks.filter((t) => !t.status || t.status === "open").length, unread: notes.filter((n) => !n.read_at).length };
}

export function RequireAuth() {
  const token = useAuth((s) => s.token);
  const location = useLocation();
  if (!token) return <Navigate to="/login" replace state={{ from: location.pathname + location.hash }} />;
  return <AppShell />;
}

function AppShell() {
  const token = useAuth((s) => s.token)!;
  const user = useAuth((s) => s.user);
  const { setUser, logout } = useAuth();
  const status = useSync((s) => s.status);

  useEffect(() => {
    sync.onRejected((e) => toast(`Änderung abgelehnt: ${e.error.message}`, "error"));
    sync.onUnauthorized(() => {
      toast("Anmeldung abgelaufen, bitte neu anmelden", "error");
      logout();
    });
    sync.connect(token);
    return () => sync.disconnect();
  }, [token, logout]);

  useEffect(() => {
    authApi.me().then(setUser).catch(() => undefined); // Rollen könnten sich geändert haben
  }, [setUser]);

  useChannel("workspace");
  const counts = useInboxCounts();

  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">dock</Link>
        <nav>
          <Link to="/">Home</Link>
          <Link to="/inbox/tasks" className="counter">
            Aufgaben {counts.tasks > 0 && <b>{counts.tasks}</b>}
          </Link>
          <Link to="/inbox/requests">Meine Anträge</Link>
          <span className="counter" title="Ungelesene Benachrichtigungen">
            🔔 {counts.unread > 0 && <b>{counts.unread}</b>}
          </span>
        </nav>
        <SearchBox />
        <span className="spacer" />
        <span className={`conn ${status}`} title={status === "open" ? "Live verbunden" : "Verbindung wird aufgebaut …"} />
        {user && (
          <span className="who">
            <span>{user.name}</span>
            {user.roles.map((r) => (
              <span key={r} className="role-chip">{ROLE_LABEL[r] ?? r}</span>
            ))}
          </span>
        )}
        <button className="ghost" onClick={logout}>Abmelden</button>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </>
  );
}
