// Gefilterte Zeilen vom Server holen (POST /api/tables/{t}/rows/query, L 3.4). Der Server ist die einzige Stelle, die
// Filter auswertet (auch Ausdrücke); der Client legt das Ergebnis auf den Live-Stand (overlayRows).
// Ändert sich der Kanal (`seq`), wird entprellt neu abgefragt, so tauchen neue passende Zeilen anderer auf.
import { useEffect, useRef, useState } from "react";
import { ApiRequestError, api } from "../api/client";
import { type FilterCond, type SortSpec, queryErrorText } from "./tableModel";

export type RowQuery = { ids: string[] | null; total: number | null; loading: boolean; error: string | null };

type RowsPage = { rows: { id: string }[]; total: number };

export const QUERY_DEBOUNCE = 250;

export function useRowQuery(
  table: string | null, conds: FilterCond[], sort: SortSpec[], seq: number | null, limit = 500,
): RowQuery {
  const active = !!table && conds.length > 0;
  const key = JSON.stringify([table, conds, sort, limit]);
  const [state, setState] = useState<RowQuery>({ ids: null, total: null, loading: false, error: null });
  const counter = useRef(0);
  const lastKey = useRef("");

  useEffect(() => {
    if (!active) {
      counter.current++;
      lastKey.current = "";
      setState((s) => (s.ids === null && !s.error && !s.loading ? s : { ids: null, total: null, loading: false, error: null }));
      return;
    }
    const mine = ++counter.current;
    const changedQuery = lastKey.current !== key;
    lastKey.current = key;
    // Bei geänderter Abfrage sofort, bei bloßen Live-Änderungen entprellt
    const timer = setTimeout(async () => {
      setState((s) => ({ ...s, loading: true }));
      try {
        const page = await api<RowsPage>(`/api/tables/${encodeURIComponent(table!)}/rows/query`, {
          method: "POST",
          json: { filter: conds, sort, limit, offset: 0 },
        });
        if (mine === counter.current) setState({ ids: page.rows.map((r) => r.id), total: page.total, loading: false, error: null });
      } catch (e) {
        if (mine !== counter.current) return;
        const status = e instanceof ApiRequestError ? e.status : 0;
        setState({ ids: null, total: null, loading: false, error: queryErrorText(status, (e as Error).message, conds) });
      }
    }, changedQuery ? 0 : QUERY_DEBOUNCE);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, seq, active]);

  return state;
}
