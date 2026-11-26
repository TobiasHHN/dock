// Tipp-Effekt im Editor (3.F5): Der Inhalt liegt sofort vollständig im Editor (TextSync/OT bleiben unberührt),
// ein ProseMirror-Plugin verbirgt nur den noch nicht „getippten“ Rest, blendet frische Wörter weich ein und
// zeigt an der Kante einen leuchtenden Cursor. Jede andere Änderung am Dokument beendet den Effekt sofort.
import { Extension, type Editor } from "@tiptap/react";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { unitToPos } from "./tiptap";
import { Typewriter, wordStops } from "./typewriterQueue";

interface Fresh { from: number; to: number; t: number }
interface State {
  id: string;
  hideFrom: number;
  end: number;
  active: boolean;
  fading: boolean;
  fresh: Fresh[];
}
type Meta =
  | { type: "start"; state: State }
  | { type: "step"; id: string; hideFrom: number; fresh: Fresh[] }
  | { type: "activate" | "fade" | "clear"; id: string };

const key = new PluginKey<State | null>("typewriter");
const FRESH_MS = 700;
const FADE_MS = 700;

const queue = new Typewriter();
let raf = 0;
let last = 0;

function loop(now: number) {
  const dt = Math.min(100, now - last);
  last = now;
  raf = queue.tick(dt) ? requestAnimationFrame(loop) : 0;
}

function kick() {
  if (raf) return;
  last = performance.now();
  raf = requestAnimationFrame(loop);
}

const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

function caret(fading: boolean) {
  const el = document.createElement("span");
  el.className = fading ? "tw-caret out" : "tw-caret";
  return el;
}

export const TypewriterExtension = Extension.create({
  name: "typewriter",
  addProseMirrorPlugins() {
    return [
      new Plugin<State | null>({
        key,
        state: {
          init: () => null,
          apply(tr, value) {
            const meta = tr.getMeta(key) as Meta | undefined;
            if (meta?.type === "start") return meta.state;
            if (!value) return value;
            if (meta) {
              if (meta.id !== value.id) return value;
              if (meta.type === "clear") return null;
              if (meta.type === "activate") return { ...value, active: true };
              if (meta.type === "fade") return { ...value, hideFrom: value.end, active: true, fading: true };
              if (meta.type === "step") return { ...value, hideFrom: meta.hideFrom, fresh: meta.fresh };
            }
            return tr.docChanged ? null : value; // fremde Änderung: Effekt sofort beenden
          },
        },
        props: {
          decorations(state) {
            const s = key.getState(state);
            if (!s) return null;
            const now = performance.now();
            const decos: Decoration[] = [];
            if (s.hideFrom < s.end) decos.push(Decoration.inline(s.hideFrom, s.end, { class: "tw-hidden" }));
            for (const f of s.fresh) {
              const age = now - f.t;
              if (age < FRESH_MS && f.from < f.to) {
                decos.push(Decoration.inline(f.from, f.to, { class: "tw-fresh", style: `animation-delay:${-Math.round(age)}ms` }));
              }
            }
            if (s.active) decos.push(Decoration.widget(s.hideFrom, () => caret(s.fading), { side: -1, key: s.fading ? "tw-out" : "tw" }));
            return DecorationSet.create(state.doc, decos);
          },
        },
      }),
    ];
  },
});

/** Einheiten [fromUnit, toUnit) des Editors tippen lassen. Liefert false, wenn der Effekt nicht läuft (dann ist der Text einfach da). */
export function typeIn(editor: Editor, id: string, fromUnit: number, toUnit: number): boolean {
  if (reducedMotion() || editor.isDestroyed || toUnit <= fromUnit) return false;
  const { doc } = editor.state;
  const from = unitToPos(doc, fromUnit);
  const end = unitToPos(doc, toUnit);
  const { stops, costs } = wordStops(doc.textBetween(from, end, undefined, "¶"));
  if (!stops.length) return false;

  const dispatch = (meta: Meta) => {
    if (editor.isDestroyed) return;
    editor.view.dispatch(editor.state.tr.setMeta(key, meta).setMeta("addToHistory", false));
  };
  const mine = () => !editor.isDestroyed && key.getState(editor.state)?.id === id;

  dispatch({ type: "start", state: { id, hideFrom: from, end, active: false, fading: false, fresh: [] } });
  queue.add({
    id, stops, costs,
    onStart: () => mine() && dispatch({ type: "activate", id }),
    onStep: (shown, prev) => {
      const s = key.getState(editor.state);
      if (!s || s.id !== id) return false;
      const now = performance.now();
      const fresh = [...s.fresh.filter((f) => now - f.t < FRESH_MS), { from: unitToPos(editor.state.doc, fromUnit + prev), to: unitToPos(editor.state.doc, fromUnit + shown), t: now }];
      dispatch({ type: "step", id, hideFrom: unitToPos(editor.state.doc, fromUnit + shown), fresh });
      return true;
    },
    onDone: () => {
      if (!mine()) return;
      dispatch({ type: "fade", id });
      setTimeout(() => mine() && dispatch({ type: "clear", id }), FADE_MS);
    },
  });
  kick();
  return true;
}

/** Editor wird abgebaut: laufende Effekte dieses Blocks verwerfen. */
export function cancelTyping(id: string) {
  queue.cancel(id);
}
