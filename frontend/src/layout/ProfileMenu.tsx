// Profil in der Kopfzeile: Klick öffnet ein Menü mit Rundgang, MCP-Hinweis und Abmelden.
import { useEffect, useRef, useState } from "react";
import { useAuth } from "../api/client";
import { openMcpInfo } from "../onboarding/McpInfo";
import { openTour } from "../onboarding/Tour";
import { initials } from "../ui/actors";
import { Icon, type IconName } from "../ui/icons";
import { ROLE_LABEL } from "./AppShell";

export function ProfileMenu() {
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpen(false); btnRef.current?.focus(); }
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    wrapRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;

  const item = (icon: IconName, label: string, action: () => void, danger = false) => (
    <button role="menuitem" className={`menu-item ${danger ? "danger" : ""}`} onClick={() => { setOpen(false); action(); }}>
      <Icon name={icon} size={16} strokeWidth={1.8} />{label}
    </button>
  );

  const onMenuKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'));
    const i = items.indexOf(document.activeElement as HTMLElement);
    items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus();
  };

  return (
    <div className="profile-wrap" ref={wrapRef}>
      <button
        ref={btnRef} type="button" className="profile" aria-haspopup="menu" aria-expanded={open}
        aria-label={`Profilmenü von ${user.name}`} onClick={() => setOpen((o) => !o)}
      >
        <span className="avatar" aria-hidden="true">{initials(user.name)}</span>
        <span className="profile-name">{user.name}</span>
        {user.roles.map((r) => (
          <span key={r} className="role-chip">{ROLE_LABEL[r] ?? r}</span>
        ))}
        <span className={`profile-caret ${open ? "open" : ""}`}><Icon name="chevronDown" size={14} /></span>
      </button>
      {open && (
        <div className="menu-popover" role="menu" aria-label="Profil" onKeyDown={onMenuKey}>
          <div className="menu-head">
            <strong>{user.name}</strong>
            <span className="muted small">{user.roles.map((r) => ROLE_LABEL[r] ?? r).join(", ")}</span>
          </div>
          {item("help", "Rundgang starten", openTour)}
          {item("plug", "Mit KI-Assistent arbeiten (MCP)", openMcpInfo)}
          <div className="menu-sep" role="separator" />
          {item("logout", "Abmelden", logout, true)}
        </div>
      )}
    </div>
  );
}
