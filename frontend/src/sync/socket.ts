// WebSocket-Verbindung mit automatischem Wiederverbinden (T 5.2). Die Abos stellt der Store nach jedem
// (Wieder-)Verbinden selbst her (subscribe mit `since`), siehe sync/store.ts.
import type { WsClientMessage, WsServerMessage } from "../api";

export type ConnectionStatus = "idle" | "connecting" | "open" | "closed";

export interface Transport {
  connect(token: string): void;
  close(): void;
  send(msg: WsClientMessage): boolean;
  onMessage: (msg: WsServerMessage) => void;
  onStatus: (status: ConnectionStatus) => void;
  /** Server hat die Anmeldung abgelehnt (Code 4401). */
  onUnauthorized: () => void;
}

const WS_UNAUTHORIZED = 4401;

export class SocketTransport implements Transport {
  onMessage: (msg: WsServerMessage) => void = () => {};
  onStatus: (status: ConnectionStatus) => void = () => {};
  onUnauthorized: () => void = () => {};

  private ws: WebSocket | null = null;
  private token: string | null = null;
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;

  connect(token: string) {
    if (this.token === token && this.ws && this.ws.readyState <= WebSocket.OPEN) return;
    this.close();
    this.token = token;
    this.open();
  }

  close() {
    this.token = null;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      ws.onclose = null;
      ws.close();
    }
    this.onStatus("closed");
  }

  send(msg: WsClientMessage): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(msg));
    return true;
  }

  private open() {
    if (!this.token) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(this.token)}`);
    this.ws = ws;
    this.onStatus("connecting");
    ws.onopen = () => {
      this.attempt = 0;
      this.onStatus("open");
    };
    ws.onmessage = (ev) => {
      try {
        this.onMessage(JSON.parse(ev.data));
      } catch (e) {
        console.error("Ungültige WebSocket-Nachricht", e);
      }
    };
    ws.onclose = (ev) => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.onStatus("closed");
      if (ev.code === WS_UNAUTHORIZED) {
        this.token = null;
        this.onUnauthorized();
        return;
      }
      // Wiederverbinden mit wachsendem Abstand (0,5 s … 10 s)
      const delay = Math.min(10_000, 500 * 2 ** this.attempt++);
      this.timer = setTimeout(() => this.open(), delay);
    };
  }
}
