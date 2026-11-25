// Bequeme Namen für die generierten Typen (src/api/types.ts).
// types.ts neu erzeugen, wenn sich Schemas ändern: `npm run gen:types` (Backend muss auf :8000 laufen).
import type { components } from "./types";

type S = components["schemas"];

export type OpBatch = S["OpBatch-Input"];
export type Op = OpBatch["ops"][number];
export type BatchResult = S["BatchResult"];
export type Actor = S["Actor"];
export type ApiError = S["ApiError"];

export type Table = S["Table"];
export type Column = S["Column"];
export type Row = S["Row"];
export type Block = S["Block"];
export type DocumentOut = S["DocumentOut"];

export type Workflow = S["Workflow"];
export type RunStatusView = S["RunStatusView"];
export type RunListItem = S["RunListItem"];
export type TaskListItem = S["TaskListItem"];
export type TaskDetail = S["TaskDetail"];
export type Notification = S["Notification"];

export type WsMessages = S["WsMessages"];
export type WsClientMessage = WsMessages["client"][number];
export type WsServerMessage = WsMessages["server"][number];

export type SnapshotData = WsMessages["snapshots"][number];

export type { components };
