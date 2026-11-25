// Abgleich eines Textblocks mit dem Server per `text.edit` (L 7.5, T 2.6), unabhängig vom Editor.
//
// Zustand pro Block (klassisches OT-Client-Modell, höchstens ein Edit unterwegs):
//   shadow   = bestätigter Server-Text + der Edit, der gerade unterwegs ist
//   inflight = gesendeter, noch nicht als Echo zurückgekommener Edit (Positionen relativ zum bestätigten Stand)
//   Editor   = shadow + lokale, noch nicht gesendete Eingaben (Puffer)
// Lokale Eingaben gehen entprellt als ein Edit (Diff shadow → Editor) mit der zuletzt bestätigten Block-Version raus.
// Fremde Edits kommen in Server-Reihenfolge; vor dem eigenen Echo wurden sie am Server VOR unserem Edit angewendet,
// also werden sie an inflight und am Puffer vorbei verschoben (side "before"), inflight selbst rückt dahinter.
import type { Actor, Op } from "../api";
import type { BatchAck, ChannelEvent } from "../sync/store";
import type { Json } from "../sync/tableRules";
import {
  type Edit, type Unit, applyEditUnits, cpLength, diffUnits, fromUnits, toUnits, transformOne,
} from "../sync/textOt";

export const SAVE_DELAY = 300;

/** Was TextSync vom Editor braucht. */
export interface TextPort {
  getUnits(): Unit[];
  /** Fremden Edit in den Editor übernehmen (ohne Undo-Eintrag); `expected` = Ergebnis zum Gegenprüfen. */
  applyRemote(edit: Edit, expected: Unit[]): void;
  /** Inhalt vollständig ersetzen (Snapshot, fremdes block.update, Ablehnung). */
  setUnits(units: Unit[]): void;
}

/** Was TextSync vom Sync-Store braucht (zum Testen austauschbar). */
export interface SyncDeps {
  submit(ops: Op[], opts: { batchId: string }): Promise<BatchAck>;
  confirmedBlock(channel: string, id: string): Json | undefined;
  channelSeq(channel: string): number | null;
  listen(channel: string, fn: (e: ChannelEvent) => void): () => void;
  newId(prefix: string): string;
}

type Inflight = { batchId: string; edit: Edit | null }; // edit null = Ersetzen per block.update (Links/Erwähnungen)

export class TextSync {
  private shadow: Unit[] = [];
  private version = 1;
  private inflight: Inflight | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private unlisten: (() => void) | null = null;
  private port: TextPort | null = null;
  private replacedWhileInflight = false;

  constructor(
    readonly blockId: string,
    readonly channel: string,
    private deps: SyncDeps,
    private onRemoteAuthor?: (actor: Actor) => void,
  ) {}

  /** Startet den Abgleich; der Editor muss den bestätigten Inhalt bereits anzeigen. */
  attach(port: TextPort) {
    this.port = port;
    const b = this.deps.confirmedBlock(this.channel, this.blockId);
    this.shadow = toUnits(b?.props?.content);
    this.version = b?.version ?? 1;
    if (b && diffUnits(this.shadow, port.getUnits())) port.setUnits(this.shadow);
    this.unlisten = this.deps.listen(this.channel, (e) => this.onEvent(e));
  }

  /** Beenden; ausstehende Eingaben werden noch gesendet (`discard`: verworfen, z. B. wenn der Block gelöscht wird). */
  detach(discard = false) {
    if (!discard) this.flush();
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.unlisten?.();
    this.unlisten = null;
    this.port = null;
  }

  get busy() {
    return this.inflight !== null || this.timer !== null;
  }

  /** Lokale Eingabe: entprellt senden. */
  changed() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), SAVE_DELAY);
  }

  /** Lokalen Puffer jetzt senden (falls nichts unterwegs ist). */
  flush() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (!this.port || this.inflight) return;
    const cur = this.port.getUnits();
    const d = diffUnits(this.shadow, cur);
    if (!d) return;
    const batchId = this.deps.newId("bat");
    let op: Op;
    if (d.plain) {
      const edit: Edit = { from: d.from, to: d.to, insert: d.insert, marks: d.marks };
      op = { op: "text.edit", block: this.blockId, version: this.version, ...edit } as Op;
      this.inflight = { batchId, edit };
    } else {
      op = { op: "block.update", block: this.blockId, props: { content: fromUnits(cur) } } as Op;
      this.inflight = { batchId, edit: null };
    }
    this.shadow = cur;
    this.deps.submit([op], { batchId }).then(
      (ack) => {
        // Echo schon in einem Snapshot enthalten (kommt dann nie als Op) → abschließen
        const seq = this.deps.channelSeq(this.channel);
        const target = ack.seq?.[this.channel];
        if (this.inflight?.batchId === batchId && (target === undefined || (seq !== null && seq >= target))) this.finishInflight();
      },
      () => {
        if (this.inflight?.batchId !== batchId) return;
        // abgelehnt: auf den bestätigten Stand zurück (Hinweis zeigt der globale Reject-Listener)
        this.inflight = null;
        const b = this.deps.confirmedBlock(this.channel, this.blockId);
        this.shadow = toUnits(b?.props?.content);
        this.version = b?.version ?? this.version;
        this.port?.setUnits(this.shadow);
      },
    );
  }

  private finishInflight() {
    this.inflight = null;
    const b = this.deps.confirmedBlock(this.channel, this.blockId);
    if (b) this.version = b.version;
    if (this.replacedWhileInflight && b) {
      // Inhalt wurde zwischendurch fremd ersetzt: auf den bestätigten Stand gehen
      this.replacedWhileInflight = false;
      this.shadow = toUnits(b.props?.content);
      this.port?.setUnits(this.shadow);
      return;
    }
    if (this.port && diffUnits(this.shadow, this.port.getUnits())) this.changed();
  }

  private onEvent(e: ChannelEvent) {
    if (!this.port) return;
    if (e.type === "snapshot") {
      const b = this.deps.confirmedBlock(this.channel, this.blockId);
      if (!b) return;
      const hadLocal = !!diffUnits(this.shadow, this.port.getUnits());
      this.shadow = toUnits(b.props?.content);
      this.version = b.version;
      if (!hadLocal && !this.inflight) this.port.setUnits(this.shadow);
      return;
    }
    let touched = false;
    for (const op of e.ops) {
      if (op.block !== this.blockId) continue;
      touched = true;
      if (e.batch_id === this.inflight?.batchId) continue; // eigenes Echo
      if (op.op === "text.edit") this.remoteEdit(op as Edit);
      else if (op.op === "block.update" && op.props && "content" in op.props) this.remoteReplace(op.props.content);
    }
    if (!touched) return;
    if (e.batch_id === this.inflight?.batchId) this.finishInflight();
    else {
      const b = this.deps.confirmedBlock(this.channel, this.blockId);
      if (b) this.version = b.version;
      this.onRemoteAuthor?.(e.actor);
    }
  }

  private remoteEdit(r: Edit) {
    const port = this.port!;
    let rI: Edit | null = r;
    if (this.inflight?.edit) {
      rI = transformOne(r, this.inflight.edit, "before");
      this.inflight.edit = transformOne(this.inflight.edit, r, "after");
    } else if (this.inflight) {
      rI = null; // unser block.update ersetzt den Inhalt ohnehin danach
    }
    if (!rI) return;
    const cur = port.getUnits();
    const buffer = diffUnits(this.shadow, cur);
    const r2 = buffer ? transformOne(rI, buffer, "before") : rI;
    this.shadow = applyEditUnits(this.shadow, rI);
    if (r2.from === r2.to && cpLength(r2.insert ?? "") === 0) return;
    port.applyRemote(r2, applyEditUnits(cur, r2));
  }

  private remoteReplace(content: Json[]) {
    if (this.inflight) this.replacedWhileInflight = true;
    this.shadow = toUnits(content);
    this.port!.setUnits(this.shadow);
  }
}
