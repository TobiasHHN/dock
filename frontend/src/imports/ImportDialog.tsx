// Import im Browser (Task 3.8, L 8.3, T 2.9): Datei wählen oder ablegen, Vorschau mit Warnungen und den
// zu erzeugenden Tabellen/Dokumenten, „Übernehmen“ führt `import.include` als Batch über den Sync-Store aus.
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiRequestError, api } from "../api/client";
import type { WorkspaceData } from "../sync/core";
import { submit, useChannel } from "../sync/store";
import { Icon } from "../ui/icons";
import { toast } from "../ui/toasts";
import {
  type ImportKind, type ImportParams, type ImportPlan, buildFormData, checkFile, emptyPlanMessage, importErrorText,
  includeOp, summarizePlan, targetPath,
} from "./importModel";

export function ImportDialog({ initialFile, onClose }: { initialFile?: File | null; onClose: () => void }) {
  const navigate = useNavigate();
  const ws = useChannel("workspace");
  const existingTables = ((ws?.view as WorkspaceData | undefined)?.tables ?? []) as { id: string; key?: string; name?: string }[];

  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<ImportKind | null>(null);
  const [params, setParams] = useState<ImportParams>({});
  const [allSheets, setAllSheets] = useState<string[]>([]);
  const [plan, setPlan] = useState<ImportPlan | null>(null);
  const [busy, setBusy] = useState<"prepare" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const request = useRef(0);

  async function prepare(f: File, k: ImportKind, p: ImportParams) {
    const n = ++request.current;
    setBusy("prepare");
    setError(null);
    try {
      const res = await api<ImportPlan>(`/api/imports/${k}`, { method: "POST", body: buildFormData(k, f, p) });
      if (n !== request.current) return;
      setPlan(res);
      if (k === "xlsx" && !p.sheet) setAllSheets(summarizePlan(res).tables.map((t) => t.name));
    } catch (e) {
      if (n !== request.current) return;
      setPlan(null);
      setError(e instanceof ApiRequestError ? importErrorText(e.status, e.message) : importErrorText(null, (e as Error).message));
    } finally {
      if (n === request.current) setBusy(null);
    }
  }

  function pick(f: File | undefined | null) {
    if (!f) return;
    const check = checkFile(f);
    if ("error" in check) {
      setError(check.error);
      return;
    }
    setFile(f);
    setKind(check.kind);
    setParams({});
    setAllSheets([]);
    setPlan(null);
    void prepare(f, check.kind, {});
  }

  useEffect(() => {
    if (initialFile) pick(initialFile);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  function change(p: ImportParams) {
    setParams(p);
    if (file && kind) void prepare(file, kind, p);
  }

  async function apply() {
    if (!plan) return;
    const summary = summarizePlan(plan);
    setBusy("apply");
    setError(null);
    try {
      await submit([includeOp(plan.import_id) as never]);
      toast(`Import übernommen: ${describe(summary)}.`);
      onClose();
      navigate(targetPath(summary));
    } catch (e) {
      setError(importErrorText(null, (e as Error).message));
      setBusy(null);
    }
  }

  const summary = plan ? summarizePlan(plan) : null;
  const empty = summary ? emptyPlanMessage(summary) : null;

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="import-title">
        <div className="modal-head">
          <h2 id="import-title">Datei importieren</h2>
          <button className="ghost" onClick={onClose} disabled={!!busy} aria-label="Schließen">✕</button>
        </div>

        <div
          className={`dropzone ${over ? "over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files[0]); }}
        >
          <Icon name={kind === "docx" ? "file" : "table"} size={22} />
          {file ? (
            <p><strong>{file.name}</strong> <span className="muted">({Math.max(1, Math.round(file.size / 1024))} KB)</span></p>
          ) : (
            <p>Excel- oder Word-Datei hierher ziehen</p>
          )}
          <button onClick={() => input.current?.click()} disabled={!!busy}>{file ? "Andere Datei wählen" : "Datei wählen"}</button>
          <input
            ref={input} type="file" hidden
            accept=".xlsx,.docx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }}
          />
        </div>

        {kind === "docx" && file && (
          <div className="import-options">
            <label>Titel (optional)
              <input value={params.title ?? ""} placeholder="Standard: erste Überschrift oder Dateiname" disabled={!!busy}
                onChange={(e) => setParams({ ...params, title: e.target.value })}
                onBlur={() => plan && change(params)} />
            </label>
            <label>Speichern in Tabelle (optional)
              <select value={params.bindTable ?? ""} disabled={!!busy} onChange={(e) => change({ ...params, bindTable: e.target.value || undefined })}>
                <option value="">Keine, Formular ohne Speichern-Button</option>
                {existingTables.filter((t) => t.key).map((t) => <option key={t.id} value={t.key}>{t.name || t.key}</option>)}
              </select>
            </label>
          </div>
        )}
        {kind === "xlsx" && allSheets.length > 1 && (
          <div className="import-options">
            <label>Blatt
              <select value={params.sheet ?? ""} disabled={!!busy} onChange={(e) => change({ sheet: e.target.value || undefined })}>
                <option value="">Alle Blätter ({allSheets.length})</option>
                {allSheets.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
          </div>
        )}

        {busy === "prepare" && <p className="muted" role="status">Lese Datei …</p>}
        {error && <p className="alert" role="alert"><Icon name="alert" />{error}</p>}

        {summary && busy !== "prepare" && (
          <div className="import-preview">
            <h3>Vorschau</h3>
            {empty && <p className="alert" role="alert"><Icon name="alert" />{empty}</p>}
            <ul className="preview-list">
              {summary.tables.map((t) => (
                <li key={t.id}><Icon name="table" /><span><strong>{t.name}</strong> <span className="chip" translate="no">{t.key}</span>
                  <span className="muted"> · {t.columns} {t.columns === 1 ? "Spalte" : "Spalten"}, {t.rows} {t.rows === 1 ? "Zeile" : "Zeilen"}</span></span></li>
              ))}
              {summary.documents.map((d) => (
                <li key={d.id}><Icon name="file" /><span><strong>{d.title}</strong>
                  <span className="muted">{d.hasForm
                    ? ` · Formular mit ${d.fields} ${d.fields === 1 ? "Feld" : "Feldern"}${d.lineItems ? ` und ${d.lineItems} Zeilenliste${d.lineItems === 1 ? "" : "n"}` : ""}`
                    : " · Dokument"}</span></span></li>
              ))}
            </ul>
            {summary.boundTable && <p className="muted">Das Formular speichert in die Tabelle <span className="chip" translate="no">{summary.boundTable.key}</span>.</p>}
            {summary.warnings.length > 0 && (
              <div className="warnings" role="status">
                <h4><Icon name="alert" />{summary.warnings.length} {summary.warnings.length === 1 ? "Warnung" : "Warnungen"}</h4>
                <ul>{summary.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
              </div>
            )}
          </div>
        )}

        <div className="modal-foot">
          <button onClick={onClose} disabled={busy === "apply"}>Abbrechen</button>
          <button className="primary" onClick={apply} disabled={!plan || !!empty || !!busy}>
            {busy === "apply" ? "Übernehme …" : "Übernehmen"}
          </button>
        </div>
      </div>
    </div>
  );
}

function describe(s: ReturnType<typeof summarizePlan>): string {
  const parts: string[] = [];
  if (s.tables.length) parts.push(`${s.tables.length} ${s.tables.length === 1 ? "Tabelle" : "Tabellen"}`);
  if (s.documents.length) parts.push(`${s.documents.length} ${s.documents.length === 1 ? "Dokument" : "Dokumente"}`);
  return parts.join(" und ") || "nichts";
}
