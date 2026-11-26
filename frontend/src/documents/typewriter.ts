// Einblend-Effekt für fremde Änderungen im Editor: Der Inhalt liegt sofort vollständig im Editor (TextSync/OT
// bleiben unberührt), ein ProseMirror-Plugin legt nur eine CSS-Animation (weiches Einblenden) über den neuen
// Bereich. Text wird nie verborgen; der Bereich folgt Änderungen am Dokument und verschwindet nach der Animation.
import { Extension, type Editor } from "@tiptap/react";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { unitToPos } from "./tiptap";

interface State { id: string; from: number; to: number }
type Meta = { type: "start"; state: State } | { type: "clear"; id: string };

const key = new PluginKey<State | null>("typewriter");
const REVEAL_MS = 900;
const timers = new Map<string, ReturnType<typeof setTimeout>>();

const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

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
            if (meta?.type === "clear") return meta.id === value.id ? null : value;
            if (!tr.docChanged) return value;
            const from = tr.mapping.map(value.from, 1);
            const to = tr.mapping.map(value.to, -1);
            return to > from ? { ...value, from, to } : null;
          },
        },
        props: {
          decorations(state) {
            const s = key.getState(state);
            if (!s) return null;
            return DecorationSet.create(state.doc, [Decoration.inline(s.from, s.to, { class: "tw-fresh" })]);
          },
        },
      }),
    ];
  },
});

/** Einheiten [fromUnit, toUnit) des Editors weich einblenden. Liefert false, wenn kein Effekt läuft (dann ist der Text einfach da). */
export function typeIn(editor: Editor, id: string, fromUnit: number, toUnit: number): boolean {
  if (reducedMotion() || editor.isDestroyed || toUnit <= fromUnit) return false;
  const { doc } = editor.state;
  const from = unitToPos(doc, fromUnit);
  const to = unitToPos(doc, toUnit);
  if (to <= from) return false;

  const dispatch = (meta: Meta) => {
    if (editor.isDestroyed) return;
    editor.view.dispatch(editor.state.tr.setMeta(key, meta).setMeta("addToHistory", false));
  };
  clearTimeout(timers.get(id));
  dispatch({ type: "start", state: { id, from, to } });
  timers.set(id, setTimeout(() => {
    timers.delete(id);
    dispatch({ type: "clear", id });
  }, REVEAL_MS));
  return true;
}

/** Editor wird abgebaut: laufenden Effekt dieses Blocks verwerfen. */
export function cancelTyping(id: string) {
  clearTimeout(timers.get(id));
  timers.delete(id);
}
