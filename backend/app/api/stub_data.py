"""Beispieldaten für die Stub-Endpunkte (Task 0.4). Spiegeln den Bestellprozess aus anwendungslogik.md 10.
Die Stubs werden in Phase 1 pro Router durch echte Implementierungen ersetzt."""
from datetime import datetime, timezone

from app.schemas.blocks import Block, Document, DocumentOwner
from app.schemas.common import Actor
from app.schemas.tables import Column, Row, Table
from app.schemas.workflows import (
    RunEvent, RunListItem, RunStatusView, StatusCandidates, StatusCurrent, StatusStep,
    Task, TaskCandidates, Workflow, WorkflowDefinition,
)

T0 = datetime(2026, 11, 25, 9, 12, tzinfo=timezone.utc)
T1 = datetime(2026, 11, 25, 9, 14, 30, tzinfo=timezone.utc)

ANNA = Actor(type="user", id="usr_anna", name="Anna Beispiel")
BEN = Actor(type="user", id="usr_ben", name="Ben Mitarbeiter")
CHEF = Actor(type="user", id="usr_chef", name="Chef Teamleiter")
BEN_AGENT = Actor(type="agent", id="agt_ben", on_behalf_of="usr_ben", name="Bens Assistent")

ROLES = [
    {"id": "rol_ek", "key": "einkauf", "name": "Einkauf", "member_count": 1},
    {"id": "rol_ma", "key": "mitarbeiter", "name": "Mitarbeiter", "member_count": 1},
    {"id": "rol_chef", "key": "chef", "name": "Chef", "member_count": 1},
]


def _col(i, key, name, type_, pos, required=False, **kw):
    return Column(id=i, key=key, name=name, type=type_, required=required, position=pos, **kw)


TBL_BEST = Table(
    id="tbl_best", key="bestellungen", name="Bestellungen", display_column="col_b_name", version=1,
    columns=[
        _col("col_b_name", "name", "Name", {"kind": "text"}, "a0", True),
        _col("col_b_ks", "kostenstelle", "Kostenstelle", {"kind": "text"}, "a1", True),
        _col("col_b_status", "status", "Status", {"kind": "select", "options": [
            {"id": "eingereicht", "label": "Eingereicht"}, {"id": "genehmigt", "label": "Genehmigt"},
            {"id": "abgelehnt", "label": "Abgelehnt"}, {"id": "bestellt", "label": "Bestellt"}]}, "a2",
             default="eingereicht"),
        _col("col_b_run", "run", "Vorgang", {"kind": "text"}, "a3"),
    ],
)
TBL_ART = Table(
    id="tbl_art", key="artikel", name="Artikel", display_column="col_a_name", version=1,
    columns=[
        _col("col_a_name", "artikelname", "Artikelname", {"kind": "text"}, "a0", True),
        _col("col_a_preis", "preis", "Preis", {"kind": "currency", "currency": "EUR"}, "a1", True),
        _col("col_a_anz", "anzahl", "Anzahl", {"kind": "integer", "min": 1}, "a2", True),
        _col("col_a_best", "bestellung", "Bestellung",
             {"kind": "reference", "table": "tbl_best", "on_delete": "cascade"}, "a3", True),
    ],
)
TABLES = [TBL_BEST, TBL_ART]

ROWS: dict[str, list[Row]] = {
    "tbl_best": [
        Row(id="row_b1", table_id="tbl_best", position="a0", created_at=T0, updated_at=T1, created_by=BEN,
            values={"col_b_name": "Ben Mitarbeiter", "col_b_ks": "4711", "col_b_status": "eingereicht",
                    "col_b_run": "run_42"}),
    ],
    "tbl_art": [
        Row(id="row_a1", table_id="tbl_art", position="a0", created_at=T0, updated_at=T0, created_by=BEN,
            values={"col_a_name": "Dell-Monitor", "col_a_preis": 249.0, "col_a_anz": 2, "col_a_best": "row_b1"}),
    ],
}


def _txt(text):
    return [{"t": "text", "text": text}]


def _b(id_, doc, type_, props, parent=None, pos="a0"):
    return Block(id=id_, doc_id=doc, parent_id=parent, position=pos, type=type_, props=props)


DOCS: dict[str, tuple[Document, list[Block]]] = {
    "doc_einkauf": (
        Document(id="doc_einkauf", title="Einkauf", version=1, updated_at=T0),
        [
            _b("blk_e_h", "doc_einkauf", "heading", {"level": 1, "content": _txt("Einkauf")}, pos="a0"),
            _b("blk_e_p", "doc_einkauf", "paragraph",
               {"content": _txt("Hier neue Bestellungen starten und den Stand verfolgen.")}, pos="a1"),
            _b("blk_e_wf", "doc_einkauf", "workflow", {"workflow": "wf_best", "mode": "launcher"}, pos="a2"),
            _b("blk_e_tv", "doc_einkauf", "table_view",
               {"table": "tbl_best", "editable": False, "allow_add": False, "allow_delete": False}, pos="a3"),
        ],
    ),
    "doc_s1": (
        Document(id="doc_s1", title="Bestellung erfassen", version=1, updated_at=T0,
                 owner=DocumentOwner(workflow="wf_best", step="erfassen")),
        [
            _b("blk_s1_h", "doc_s1", "heading", {"level": 1, "content": _txt("Bestellung erfassen")}, pos="a0"),
            _b("blk_s1_form", "doc_s1", "form", {
                "actions": [
                    {"key": "order", "type": "create_row", "table": "tbl_best", "values": {
                        "col_b_name": "{{fields.name}}", "col_b_ks": "{{fields.kostenstelle}}",
                        "col_b_status": "eingereicht", "col_b_run": "{{run.id}}"}},
                    {"key": "items", "type": "create_rows", "table": "tbl_art", "for_each": "{{fields.artikel}}",
                     "values": {"col_a_name": "{{item.artikelname}}", "col_a_preis": "{{item.preis}}",
                                "col_a_anz": "{{item.anzahl}}", "col_a_best": "{{results.order.id}}"}},
                ],
                "buttons": [{"id": "submit", "label": "Eingereicht", "style": "primary",
                             "actions": ["order", "items"], "outcome": "submitted"}],
            }, pos="a1"),
            _b("blk_s1_name", "doc_s1", "field", {"key": "name", "label": "Name", "column": "col_b_name"},
               parent="blk_s1_form", pos="a0"),
            _b("blk_s1_ks", "doc_s1", "field", {"key": "kostenstelle", "label": "Kostenstelle",
                                                "column": "col_b_ks"}, parent="blk_s1_form", pos="a1"),
            _b("blk_s1_items", "doc_s1", "line_items", {
                "key": "artikel", "label": "Artikel", "min_rows": 1,
                "columns": [{"key": "artikelname", "column": "col_a_name"}, {"key": "preis", "column": "col_a_preis"},
                            {"key": "anzahl", "column": "col_a_anz"}]}, parent="blk_s1_form", pos="a2"),
        ],
    ),
    "doc_s2": (
        Document(id="doc_s2", title="Genehmigung", version=1, updated_at=T0,
                 owner=DocumentOwner(workflow="wf_best", step="genehmigung")),
        [
            _b("blk_s2_h", "doc_s2", "heading", {"level": 1, "content": _txt("Genehmigung")}, pos="a0"),
            _b("blk_s2_form", "doc_s2", "form", {
                "actions": [
                    {"key": "approve", "type": "update_row", "table": "tbl_best",
                     "row": "{{run.steps.erfassen.results.order.id}}", "values": {"col_b_status": "genehmigt"}},
                    {"key": "reject", "type": "update_row", "table": "tbl_best",
                     "row": "{{run.steps.erfassen.results.order.id}}", "values": {"col_b_status": "abgelehnt"}},
                ],
                "buttons": [
                    {"id": "approve", "label": "Genehmigen", "style": "primary", "actions": ["approve"],
                     "outcome": "approved"},
                    {"id": "reject", "label": "Ablehnen", "style": "danger", "actions": ["reject"],
                     "outcome": "rejected", "require": ["kommentar"]},
                ],
            }, pos="a1"),
            _b("blk_s2_komm", "doc_s2", "field", {"key": "kommentar", "label": "Kommentar", "input": "textarea"},
               parent="blk_s2_form", pos="a0"),
        ],
    ),
}

WORKFLOW = Workflow(
    id="wf_best", key="bestellprozess", name="Bestellprozess", latest_version=1,
    draft=WorkflowDefinition.model_validate({
        "start": "erfassen", "starters": [], "managers": [{"kind": "role", "role": "rol_ek"}],
        "steps": [
            {"key": "erfassen", "name": "Bestellung erfassen", "status_label": "In Erfassung",
             "document": "doc_s1", "assignees": [{"kind": "starter"}]},
            {"key": "genehmigung", "name": "Genehmigung", "status_label": "Wartet auf Genehmigung",
             "document": "doc_s2", "assignees": [{"kind": "role", "role": "rol_chef"}],
             "exclude_starter": True, "due_in": "P2D"},
            {"key": "bestellung", "name": "Bestellung auslösen", "status_label": "Wird vom Einkauf bestellt",
             "document": "doc_s3", "assignees": [{"kind": "role", "role": "rol_ek"}], "due_in": "P3D"},
        ],
        "transitions": [
            {"from": "erfassen", "on": "submitted", "to": "genehmigung"},
            {"from": "genehmigung", "on": "approved", "to": "bestellung"},
            {"from": "genehmigung", "on": "rejected", "to": "end"},
            {"from": "bestellung", "on": "ordered", "to": "end"},
        ],
    }),
)

TASK_OPEN = Task(
    id="tsk_2", run_id="run_42", step="genehmigung", status="open",
    candidates=TaskCandidates(roles=["chef"]), excluded=["usr_ben"], created_at=T1,
)

RUN_STATUS = RunStatusView(
    id="run_42", title="Bestellung KS 4711 – Ben Mitarbeiter",
    workflow={"id": "wf_best", "name": "Bestellprozess", "version": 1},
    status="active", started_by=BEN_AGENT, started_at=T0,
    current=StatusCurrent(step="genehmigung", label="Wartet auf Genehmigung", since=T1,
                          candidates=StatusCandidates(roles=[{"key": "chef", "name": "Chef"}])),
    steps=[
        StatusStep(step="erfassen", name="Bestellung erfassen", state="done", label="Eingereicht",
                   by="Bens Assistent im Auftrag von Ben Mitarbeiter", at=T1),
        StatusStep(step="genehmigung", name="Genehmigung", state="active"),
        StatusStep(step="bestellung", name="Bestellung auslösen", state="pending"),
    ],
    events=[
        RunEvent(id="evt_1", run_id="run_42", at=T0, actor=BEN_AGENT, type="started"),
        RunEvent(id="evt_2", run_id="run_42", at=T0, actor=Actor(type="system", id="workflow"),
                 type="step_entered", step="erfassen"),
        RunEvent(id="evt_3", run_id="run_42", at=T1, actor=BEN_AGENT, type="step_completed", step="erfassen",
                 outcome="submitted", label="Eingereicht"),
        RunEvent(id="evt_4", run_id="run_42", at=T1, actor=Actor(type="system", id="workflow"),
                 type="step_entered", step="genehmigung"),
    ],
)

RUN_LIST = [
    RunListItem(id="run_42", title=RUN_STATUS.title, workflow_name="Bestellprozess", status="active",
                status_label="Wartet auf Genehmigung",
                candidates=StatusCandidates(roles=[{"key": "chef", "name": "Chef"}]), started_at=T0)
]
