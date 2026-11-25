// Anzeige von Akteuren (L 5.8): Mensch, Agent „im Auftrag von …“, Workflow.
import { useQuery } from "@tanstack/react-query";
import type { Actor } from "../api";
import { type UserOut, authApi, useAuth } from "../api/client";

export function useUsers(): Record<string, UserOut> {
  const token = useAuth((s) => s.token);
  const { data } = useQuery({ queryKey: ["users"], queryFn: authApi.users, enabled: !!token, staleTime: 60_000 });
  return Object.fromEntries((data ?? []).map((u) => [u.id, u]));
}

export function actorLabel(actor: Actor, users: Record<string, UserOut>): string {
  if (actor.type === "system") return actor.id === "scheduler" ? "Zeitplan" : "Workflow";
  const name = actor.name ?? users[actor.id]?.name ?? actor.id;
  if (actor.type === "agent") {
    const behalf = actor.on_behalf_of ? users[actor.on_behalf_of]?.name ?? actor.on_behalf_of : null;
    return behalf ? `${name} im Auftrag von ${behalf}` : `${name} (Agent)`;
  }
  return name;
}

export function initials(label: string): string {
  return label
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");
}

export function Avatar({ actor, users }: { actor: Actor; users: Record<string, UserOut> }) {
  const label = actorLabel(actor, users);
  return (
    <span className={`avatar ${actor.type === "agent" ? "agent" : ""}`} title={label}>
      {actor.type === "agent" ? "🤖" : initials(actor.name ?? users[actor.id]?.name ?? "?")}
    </span>
  );
}
