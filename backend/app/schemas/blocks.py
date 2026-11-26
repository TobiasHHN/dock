"""Dokumente, Blöcke, Formulare (anwendungslogik.md 3, 4)."""
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from .common import Strict, Value
from .tables import FilterCondition, SortSpec

# ── Inline-Inhalt (3.3) ──────────────────────────────────────────────────────


class InlineText(Strict):
    t: Literal["text"]
    text: str
    marks: list[Literal["bold", "italic", "code", "strike"]] = []


class InlineLink(Strict):
    t: Literal["link"]
    text: str
    href: str


class InlineMention(Strict):
    t: Literal["mention"]
    target: str  # URI auf Dokument, Block, Tabelle, Zeile, Nutzer


class InlineValue(Strict):
    t: Literal["value"]
    expr: str  # z. B. "{{run.steps.erfassen.values.name}}"


Inline = Annotated[Union[InlineText, InlineLink, InlineMention, InlineValue], Field(discriminator="t")]

# ── Formulare (4) ────────────────────────────────────────────────────────────


class CreateRowAction(Strict):
    key: str
    type: Literal["create_row"]
    table: str
    values: dict[str, str | Value]  # col -> Ausdruck oder Literal


class CreateRowsAction(Strict):
    key: str
    type: Literal["create_rows"]
    table: str
    for_each: str
    values: dict[str, str | Value]


class UpdateRowAction(Strict):
    key: str
    type: Literal["update_row"]
    table: str
    row: str
    values: dict[str, str | Value]


class DeleteRowAction(Strict):
    key: str
    type: Literal["delete_row"]
    table: str
    row: str


Action = Annotated[
    Union[CreateRowAction, CreateRowsAction, UpdateRowAction, DeleteRowAction], Field(discriminator="type")
]


class Button(Strict):
    id: str
    label: str  # als Aufforderung („Genehmigen“, „Ablehnen“, „Einreichen“), nicht als Ergebnis („Genehmigt“)
    style: Literal["primary", "secondary", "danger"] = "secondary"
    actions: list[str] = []  # Keys der Actions, in dieser Reihenfolge
    outcome: str | None = None  # bestimmt im Workflow den nächsten Schritt
    validate_: bool = Field(True, alias="validate")
    require: list[str] = []  # zusätzliche Pflichtfelder nur für diesen Button
    confirm: str | None = None

    model_config = {"populate_by_name": True, "extra": "forbid"}


FieldInput = Literal[
    "text", "textarea", "integer", "number", "currency", "date", "boolean", "select", "reference", "user"
]

# ── Block-Props je Typ (3.2) ─────────────────────────────────────────────────


class HeadingProps(Strict):
    level: Literal[1, 2, 3] = 1
    content: list[Inline] = []


class ParagraphProps(Strict):
    content: list[Inline] = []


class ListProps(Strict):
    ordered: bool = False


class ListItemProps(Strict):
    content: list[Inline] = []
    checked: bool | None = None


class QuoteProps(Strict):
    pass


class CodeProps(Strict):
    language: str | None = None
    text: str = ""


class DividerProps(Strict):
    pass


class ImageProps(Strict):
    asset_id: str
    alt: str = ""


class TableViewProps(Strict):
    table: str
    columns: list[str] | None = None
    filter: list[FilterCondition] = []
    sort: list[SortSpec] = []
    editable: bool = False
    allow_add: bool = False
    allow_delete: bool = False


class FormProps(Strict):
    actions: list[Action] = []
    buttons: list[Button] | None = None  # None -> automatischer "Speichern"-Button (4.3)
    reset_after_submit: bool | None = None


class FieldProps(Strict):
    key: str
    label: str
    input: FieldInput | None = None  # leer -> aus `column` übernommen
    required: bool = False
    column: str | None = None
    default: Value | None = None
    options: list[dict[str, str]] | None = None  # {id,label} für select
    reference_table: str | None = None


class LineItemColumn(Strict):
    key: str
    label: str | None = None
    column: str | None = None
    input: FieldInput | None = None
    required: bool = False


class LineItemsProps(Strict):
    key: str
    label: str
    columns: list[LineItemColumn]
    min_rows: int | None = None


class WorkflowBlockProps(Strict):
    workflow: str
    mode: Literal["launcher", "run", "subflow"] = "launcher"
    run: str | None = None
    input: dict[str, str] | None = None
    wait: bool = False


# ── Block-Union (rekursiv über `children`) ───────────────────────────────────


class _BlockBase(Strict):
    id: str


class HeadingBlock(_BlockBase):
    type: Literal["heading"]
    props: HeadingProps = HeadingProps()
    children: list["BlockIn"] = []


class ParagraphBlock(_BlockBase):
    type: Literal["paragraph"]
    props: ParagraphProps = ParagraphProps()
    children: list["BlockIn"] = []


class ListBlock(_BlockBase):
    type: Literal["list"]
    props: ListProps = ListProps()
    children: list["BlockIn"] = []


class ListItemBlock(_BlockBase):
    type: Literal["list_item"]
    props: ListItemProps = ListItemProps()
    children: list["BlockIn"] = []


class QuoteBlock(_BlockBase):
    type: Literal["quote"]
    props: QuoteProps = QuoteProps()
    children: list["BlockIn"] = []


class CodeBlock(_BlockBase):
    type: Literal["code"]
    props: CodeProps = CodeProps()
    children: list["BlockIn"] = []


class DividerBlock(_BlockBase):
    type: Literal["divider"]
    props: DividerProps = DividerProps()
    children: list["BlockIn"] = []


class ImageBlock(_BlockBase):
    type: Literal["image"]
    props: ImageProps
    children: list["BlockIn"] = []


class TableViewBlock(_BlockBase):
    type: Literal["table_view"]
    props: TableViewProps
    children: list["BlockIn"] = []


class FormBlock(_BlockBase):
    type: Literal["form"]
    props: FormProps = FormProps()
    children: list["BlockIn"] = []


class FieldBlock(_BlockBase):
    type: Literal["field"]
    props: FieldProps
    children: list["BlockIn"] = []


class LineItemsBlock(_BlockBase):
    type: Literal["line_items"]
    props: LineItemsProps
    children: list["BlockIn"] = []


class WorkflowNodeBlock(_BlockBase):
    type: Literal["workflow"]
    props: WorkflowBlockProps
    children: list["BlockIn"] = []


BlockIn = Annotated[
    Union[
        HeadingBlock, ParagraphBlock, ListBlock, ListItemBlock, QuoteBlock, CodeBlock, DividerBlock, ImageBlock, TableViewBlock, FormBlock, FieldBlock, LineItemsBlock, WorkflowNodeBlock,
    ],
    Field(discriminator="type"),
]

BLOCK_TYPES = ["heading", "paragraph", "list", "list_item", "quote", "code", "divider", "image", "table_view", "form", "field", "line_items", "workflow"]

for _m in (HeadingBlock, ParagraphBlock, ListBlock, ListItemBlock, QuoteBlock, CodeBlock, DividerBlock, ImageBlock, TableViewBlock, FormBlock, FieldBlock, LineItemsBlock, WorkflowNodeBlock):
    _m.model_rebuild()


# ── Gespeicherte Form (flach) und Dokument ──────────────────────────────────


class Block(BaseModel):
    """Flach gespeicherter Block (3.1): Baum ergibt sich aus parent_id + position."""

    id: str
    doc_id: str
    parent_id: str | None = None
    position: str
    type: str
    props: dict[str, Any]
    version: int = 1


class DocumentOwner(Strict):
    workflow: str
    step: str


class Document(BaseModel):
    id: str
    title: str
    owner: DocumentOwner | None = None
    version: int = 1
    updated_at: datetime | None = None


class DocumentOut(BaseModel):
    document: Document
    blocks: list[Block]


class DocumentMarkdown(BaseModel):
    """`get_document(format="md")` (8.2): Markdown mit Block-IDs `{#blk_…}`."""

    document: Document
    markdown: str


class DocumentSummary(BaseModel):
    id: str
    title: str
    owner: DocumentOwner | None = None
    updated_at: datetime | None = None


class LineItem(BaseModel):
    id: str
    position: str
    values: dict[str, Value]


class FormDraft(BaseModel):
    form_block: str
    scope: dict[str, str]  # {"run": "run_42"} oder {"user": "usr_1"}
    values: dict[str, Any]  # key -> Wert | LineItem[]
    version: int = 1
