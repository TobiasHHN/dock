// Benachrichtigungen (Task 4.5, L 5.10, T 5.7): Live-Toast bei neuer Benachrichtigung + Glocke mit Popover.
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Notification } from "../api";
import { useAuth, workflowApi } from "../api/client";
import { useInboxCounts } from "../layout/AppShell";
import { sync } from "../sync/store";
import { Icon, relativeTime } from "../ui/icons";
import { toast } from "../ui/toasts";
import { formatNotification, useChannelInvalidate } from "./inboxModel";

/** Zeigt beim Eintreffen einer Live-Benachrichtigung auf `user:<id>` sofort einen Toast und aktualisiert Listen. */
export function useNotificationToasts(userId: string | undefined) {
  const qc = useQueryClient();
  useEffect(() => {
    if (!userId) return;
    return sync.listen(`user:${userId}`, (ev) => {
      if (ev.type === "notification") {
        const { title, detail } = formatNotification(ev.notification);
        toast(detail ? `${title} · ${detail}` : title);
        qc.invalidateQueries({ queryKey: ["notifications"] });
        qc.invalidateQueries({ queryKey: ["tasks"] });
        qc.invalidateQueries({ queryKey: ["runs"] });
      }
    });
  }, [userId, qc]);
}

export function NotificationBell() {
  const me = useAuth((s) => s.user);
  const counts = useInboxCounts();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useChannelInvalidate(me ? `user:${me.id}` : null, [["notifications"]]);

  const { data: items, isLoading } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => workflowApi.notifications(),
    enabled: !!me && open,
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const unreadCount = items ? items.filter((n) => !n.read_at).length : counts.unread;

  async function markOne(n: Notification) {
    setOpen(false);
    if (!n.read_at) {
      try {
        await workflowApi.markNotificationRead(n.id);
        qc.invalidateQueries({ queryKey: ["notifications"] });
        if (me) sync.requestSnapshot(`user:${me.id}`);
      } catch {
        /* Navigation trotzdem zulassen */
      }
    }
    navigate(n.run_id ? `/runs/${n.run_id}` : "/inbox/tasks");
  }

  async function remove(n: Notification) {
    try {
      await workflowApi.deleteNotification(n.id);
      qc.setQueryData<Notification[]>(["notifications"], (old) => old?.filter((x) => x.id !== n.id));
      if (me) sync.requestSnapshot(`user:${me.id}`);
    } catch (e) {
      toast(`Konnte nicht entfernt werden: ${(e as Error).message}`, "error");
    }
  }

  async function markAllRead() {
    if (!items || markingAll) return;
    const unread = items.filter((n) => !n.read_at);
    if (unread.length === 0) return;
    setMarkingAll(true);
    try {
      await Promise.all(unread.map((n) => workflowApi.markNotificationRead(n.id)));
      await qc.invalidateQueries({ queryKey: ["notifications"] });
      if (me) sync.requestSnapshot(`user:${me.id}`);
    } catch (e) {
      toast(`Konnte nicht als gelesen markiert werden: ${(e as Error).message}`, "error");
    } finally {
      setMarkingAll(false);
    }
  }

  return (
    <div className="notif-wrap" ref={wrapRef}>
      <button
        type="button"
        className="icon-button bell"
        aria-label={unreadCount > 0 ? `Benachrichtigungen, ${unreadCount} ungelesen` : "Benachrichtigungen"}
        aria-expanded={open}
        aria-haspopup="dialog"
        title="Benachrichtigungen"
        onClick={() => setOpen((o) => !o)}
      >
        <Icon name="bell" size={20} strokeWidth={1.8} />
        {unreadCount > 0 && <span className="dot" aria-hidden="true" />}
      </button>

      {open && (
        <div className="notif-popover" role="dialog" aria-label="Benachrichtigungen">
          <div className="notif-head">
            <strong>Benachrichtigungen</strong>
            {unreadCount > 0 && (
              <button type="button" className="ghost small" disabled={markingAll} onClick={markAllRead}>
                Als gelesen markieren
              </button>
            )}
          </div>
          {isLoading ? (
            <div className="skeleton-list" style={{ padding: "8px 12px" }}>
              <span /><span />
            </div>
          ) : !items || items.length === 0 ? (
            <p className="empty" style={{ padding: "16px 12px" }}>Keine Benachrichtigungen.</p>
          ) : (
            <ul className="notif-list">
              {items.slice(0, 20).map((n) => {
                const { title, detail } = formatNotification(n);
                return (
                  <li key={n.id} className={`notif-row ${!n.read_at ? "unread" : ""}`}>
                    <button type="button" className="notif-item" onClick={() => markOne(n)}>
                      <span className="notif-item-title">{title}</span>
                      {detail && <span className="notif-item-detail">{detail}</span>}
                      <span className="notif-item-time">{relativeTime(n.created_at) ?? "gerade eben"}</span>
                    </button>
                    <button
                      type="button"
                      className="notif-remove"
                      aria-label={`Benachrichtigung „${title}“ entfernen`}
                      title="Entfernen"
                      onClick={() => void remove(n)}
                    >
                      <Icon name="close" size={14} />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
