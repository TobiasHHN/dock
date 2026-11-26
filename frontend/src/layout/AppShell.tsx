// Rahmen nach dem Login (Task 2.1): Kopfzeile mit Name, Rolle, Suche, Zählern.
// Verbindet den Sync-Store und abonniert dauerhaft `user:<id>` (T 5.7) und `workspace` (Listen, L 7.2).
// Auf schmalen Bildschirmen wandert die Navigation in eine Tab-Leiste am unteren Rand.
import { useEffect } from "react";
import { Link, Navigate, NavLink, Outlet, useLocation } from "react-router-dom";
import { authApi, useAuth } from "../api/client";
import { McpInfoHost } from "../onboarding/McpInfo";
import { TourHost } from "../onboarding/Tour";
import { ProfileMenu } from "./ProfileMenu";
import { NotificationBell, useNotificationToasts } from "../inbox/Notifications";
import { SearchBox } from "../search/SearchBox";
import { sync, useChannel } from "../sync/store";
import { Icon } from "../ui/icons";
import { toast } from "../ui/toasts";

export const ROLE_LABEL: Record<string, string> = { einkauf: "Einkauf", mitarbeiter: "Mitarbeiter", chef: "Chef" };

export type InboxTask = {
  id: string;
  step?: string;
  status?: string;
  created_at?: string;
  due_at?: string | null;
  run_id?: string;
};

/** Daten aus dem Kanal `user:<id>`: offene Aufgaben und ungelesene Benachrichtigungen. */
export function useInbox() {
  const user = useAuth((s) => s.user);
  const ch = useChannel(user ? `user:${user.id}` : null);
  const data = ch?.view;
  const tasks: InboxTask[] = data?.tasks ?? [];
  const notes: { read_at?: string | null }[] = data?.notifications ?? [];
  return {
    loading: !ch || ch.status === "loading",
    openTasks: tasks.filter((t) => !t.status || t.status === "open"),
    unread: notes.filter((n) => !n.read_at).length,
  };
}

/** Offene Aufgaben und ungelesene Benachrichtigungen als Zahlen. */
export function useInboxCounts() {
  const { openTasks, unread } = useInbox();
  return { tasks: openTasks.length, unread };
}

export function RequireAuth() {
  const token = useAuth((s) => s.token);
  const location = useLocation();
  if (!token) return <Navigate to="/login" replace state={{ from: location.pathname + location.hash }} />;
  return <AppShell />;
}

function Badge({ n, label }: { n: number; label: string }) {
  if (n <= 0) return null;
  return (
    <span className="badge" aria-label={`${n} ${label}`}>
      {n > 99 ? "99+" : n}
    </span>
  );
}

function AppShell() {
  const token = useAuth((s) => s.token)!;
  const user = useAuth((s) => s.user);
  const { setUser, logout } = useAuth();

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
  useNotificationToasts(user?.id);
  const counts = useInboxCounts();

  return (
    <>
      <a href="#main" className="skip-link">Zum Inhalt springen</a>
      <header className="topbar">
        <Link to="/" className="brand" translate="no" aria-label="Dock, zur Startseite">Dock</Link>
        <nav className="topnav" aria-label="Hauptnavigation">
          <NavLink to="/inbox/tasks">
            Zu erledigen <Badge n={counts.tasks} label="offen" />
          </NavLink>
          <NavLink to="/inbox/requests">Meine Vorgänge</NavLink>
        </nav>
        <SearchBox />
        <span className="spacer" />
        <NotificationBell />
        <ProfileMenu />
      </header>
      <TourHost />
      <McpInfoHost />
      <main className="page" id="main" tabIndex={-1}>
        <div key={location.pathname} className="page-enter">
          <Outlet />
        </div>
      </main>
      <nav className="tabbar" aria-label="Hauptnavigation mobil">
        <NavLink to="/" end>
          <Icon name="home" size={22} />
          <span>Home</span>
        </NavLink>
        <NavLink to="/inbox/tasks">
          <Icon name="tasks" size={22} />
          <span>Zu erledigen</span>
          <Badge n={counts.tasks} label="offen" />
        </NavLink>
        <NavLink to="/inbox/requests">
          <Icon name="inbox" size={22} />
          <span>Vorgänge</span>
        </NavLink>
      </nav>
    </>
  );
}
