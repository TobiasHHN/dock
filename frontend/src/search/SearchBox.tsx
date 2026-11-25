// Suchfeld mit hybrider Suche (T 3.3, Endpunkt aus 5.2). Treffer verlinken auf Dokument (mit Block), Tabelle, Workflow.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { type SearchHit, listApi } from "../api/client";

const KIND_LABEL: Record<SearchHit["kind"], string> = { document: "Dokument", table: "Tabelle", workflow: "Workflow" };

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

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const { data, isFetching, error } = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => listApi.search(debounced),
    enabled: debounced.length >= 2,
  });

  return (
    <div className="search" ref={box}>
      <input
        type="search"
        placeholder="Suchen …"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
      />
      {open && debounced.length >= 2 && (
        <div className="search-results">
          {error && <div className="small error-text" style={{ padding: 8 }}>{(error as Error).message}</div>}
          {!error && data?.hits.length === 0 && !isFetching && <div className="small muted" style={{ padding: 8 }}>Keine Treffer</div>}
          {data?.hits.map((h) => (
            <Link key={`${h.kind}:${h.id}`} to={hitLink(h)} onClick={() => setOpen(false)}>
              <div>
                <span className="small muted">{KIND_LABEL[h.kind]} · </span>
                <b>{h.title}</b>
              </div>
              {h.snippet && <div className="small muted">{h.snippet}</div>}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
