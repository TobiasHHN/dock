// Erweiterungspunkt für Blocktypen anderer Tasks: P3 (table_view, form, field, line_items) und P4 (workflow)
// tragen hier ihre Komponente ein, z. B. in ihrer eigenen Datei:
//
//   import { BLOCK_COMPONENTS } from "../documents/blocks/registry";
//   BLOCK_COMPONENTS.table_view = TableView;
//
// Bis dahin zeigt die Dokument-Ansicht einen Platzhalter. Eine Komponente bekommt den flachen Block und rendert
// ihre Kinder bei Bedarf mit `<BlockChildren parent={block.id} />` (z. B. ein Formular seine Felder).
import type { ComponentType } from "react";
import type { FlatBlock } from "../blockOps";

export type BlockComponent = ComponentType<{ block: FlatBlock }>;

export const BLOCK_COMPONENTS: Partial<Record<string, BlockComponent>> = {};
