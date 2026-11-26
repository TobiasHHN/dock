// Suchfeld mit hybrider Suche (T 3.3, Endpunkt aus 5.2). Treffer verlinken auf Dokument (mit Block), Tabelle, Workflow.
// Strg/⌘ K fokussiert das Feld, Pfeiltasten wandern durch die Treffer, Escape schließt.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { type SearchHit, listApi } from "../api/client";
import { Icon, type IconName } from "../ui/icons";

const KIND_LABEL: Record<SearchHit["kind"], string> = { document: "Dokument", table: "Tabelle", workflow: "Workflow" };
const KIND_ICON: Record<SearchHit["kind"], IconName> = { document: "file", table: "table", workflow: "flow" };
const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

export function hitLink(hit: SearchHit): string {
  if (hit.kind === "document") return `/documents/${hit.id}${hit.block_ids[0] ? `#${hit.block_ids[0]}` : ""}`;
  if (hit.kind === "table") return `/tables/${hit.id}`;
  return `/workflows/${hit.id}`;
}

export function SearchBox() {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const shortcut = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        input.current?.focus();
        input.current?.select();
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", shortcut);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", shortcut);
    };
  }, []);

  const { data, isFetching, error } = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => listApi.search(debounced),
    enabled: debounced.length >= 2,
  });

  const moveFocus = (dir: 1 | -1) => {
    const links = Array.from(box.current?.querySelectorAll<HTMLAnchorElement>(".search-results a") ?? []);
    if (!links.length) return;
    const i = links.indexOf(document.activeElement as HTMLAnchorElement);
    const next = i === -1 ? (dir === 1 ? 0 : links.length - 1) : i + dir;
    if (next < 0) input.current?.focus();
    else links[Math.min(next, links.length - 1)].focus();
  };

  return (
    <div
      className="search"
      ref={box}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          setOpen(false);
          input.current?.blur();
        } else if (e.key === "ArrowDown") {
          e.preventDefault();
          moveFocus(1);
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          moveFocus(-1);
        }
      }}
    >
      <span className="search-icon"><Icon name="search" /></span>
      <input
        ref={input}
        type="search"
        name="q"
        aria-label="Dokumente, Tabellen und Workflows durchsuchen"
        autoComplete="off"
        spellCheck={false}
        placeholder="Suchen …"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
      />
      {!q && <kbd className="kbd" aria-hidden="true">{IS_MAC ? "⌘" : "Strg"}&nbsp;K</kbd>}
      {open && debounced.length >= 2 && (
        <div className="search-results" aria-live="polite">
          {error && <div className="search-empty error-text">{(error as Error).message}</div>}
          {!error && data?.hits.length === 0 && !isFetching && <div className="search-empty">Keine Treffer für „{debounced}“</div>}
          {!data && isFetching && <div className="search-empty">Suche läuft …</div>}
          {data?.hits.map((h) => (
            <Link key={`${h.kind}:${h.id}`} to={hitLink(h)} onClick={() => setOpen(false)}>
              <span className="hit-icon"><Icon name={KIND_ICON[h.kind]} /></span>
              <span className="hit-body">
                <span className="hit-title">{h.title}</span>
                <span className="hit-meta">{KIND_LABEL[h.kind]}{h.snippet ? ` · ${h.snippet}` : ""}</span>
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
