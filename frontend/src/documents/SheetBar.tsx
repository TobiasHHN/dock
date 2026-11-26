// Blatt-Leiste am unteren Rand der Dokument-Ansicht (Task 3.F5, B8).
import { useEffect, useRef, useState } from "react";
import { Icon } from "../ui/icons";
import { EMBED_TYPES, type EmbedKind } from "./embedModel";
import type { Sheet } from "./workbookModel";

export type SheetLabel = { sheet: Sheet; label: string };

/** Blätter wie in Excel: Blatt 1 = Dokument, dann Tabellen und Workflows; „+“ bettet neue ein (nur mit Schreibrecht). */
export function SheetBar({ docLabel, sheets, active, onSelect, onEmbed }: {
  docLabel: string;
  sheets: SheetLabel[];
  active: Sheet | null;
  onSelect: (s: Sheet | null) => void;
  onEmbed?: (kind: EmbedKind) => void;
}) {
  const [menu, setMenu] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setMenu(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setMenu(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [menu]);

  return (
    <nav className="sheet-bar" aria-label="Blätter">
      <div className="sheet-tabs">
        <button className={`sheet-tab ${active ? "" : "active"}`} aria-current={active ? undefined : "page"} onClick={() => onSelect(null)}>
          <Icon name="file" size={14} /><span>{docLabel}</span>
        </button>
        {sheets.map(({ sheet, label }) => (
          <button
            key={sheet.id}
            className={`sheet-tab ${active?.id === sheet.id ? "active" : ""}`}
            aria-current={active?.id === sheet.id ? "page" : undefined}
            onClick={() => onSelect(sheet)}
          >
            <Icon name={sheet.kind === "table" ? "table" : "flow"} size={14} /><span>{label}</span>
          </button>
        ))}
      </div>
      {onEmbed && (
        <div className="sheet-add" ref={ref}>
          <button className="ghost" aria-label="Blatt hinzufügen" title="Tabelle oder Workflow hinzufügen" aria-expanded={menu} onClick={() => setMenu(!menu)}>
            <Icon name="plus" size={14} />
          </button>
          {menu && (
            <div className="insert-menu sheet-menu" role="menu">
              {EMBED_TYPES.map((t) => (
                <button key={t.kind} role="menuitem" onClick={() => { setMenu(false); onEmbed(t.kind); }}>
                  <Icon name={t.icon} size={14} />{t.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </nav>
  );
}
