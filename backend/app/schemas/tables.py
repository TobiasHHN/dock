"""Tabellen, Spalten, Zeilen (anwendungslogik.md 2)."""
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from .common import Actor, Strict, Value


class TextType(Strict):
    kind: Literal["text"]


class LongTextType(Strict):
    kind: Literal["long_text"]


class IntegerType(Strict):
    kind: Literal["integer"]
    min: int | None = None
    max: int | None = None


class NumberType(Strict):
    kind: Literal["number"]
    decimals: int = 2


class CurrencyType(Strict):
    kind: Literal["currency"]
    currency: str = "EUR"


class BooleanType(Strict):
    kind: Literal["boolean"]


class DateType(Strict):
    kind: Literal["date"]


class DateTimeType(Strict):
    kind: Literal["datetime"]


class SelectOption(Strict):
    id: str
    label: str


class SelectType(Strict):
    kind: Literal["select"]
    options: list[SelectOption]


class UserType(Strict):
    kind: Literal["user"]


class ReferenceType(Strict):
    kind: Literal["reference"]
    table: str
    on_delete: Literal["restrict", "cascade", "set_null"] = "restrict"


ColumnType = Annotated[
    Union[
        TextType, LongTextType, IntegerType, NumberType, CurrencyType, BooleanType,
        DateType, DateTimeType, SelectType, UserType, ReferenceType,
    ],
    Field(discriminator="kind"),
]


class ColumnIn(Strict):
    """Spalte beim Anlegen (table.create, column.add). `position` vergibt der Server, falls leer."""

    id: str
    key: str
    name: str
    type: ColumnType
    required: bool = False
    unique: bool = False
    default: Value | None = None  # auch "{{now}}" oder "{{user.id}}"
    position: str | None = None


class Column(BaseModel):
    id: str
    key: str
    name: str
    type: ColumnType
    required: bool = False
    unique: bool = False
    default: Value | None = None
    position: str


class ColumnPatch(Strict):
    key: str | None = None
    name: str | None = None
    type: ColumnType | None = None
    required: bool | None = None
    unique: bool | None = None
    default: Value | None = None


class Table(BaseModel):
    id: str
    key: str
    name: str
    columns: list[Column]
    display_column: str | None = None
    version: int = 1


class NewRow(Strict):
    id: str
    values: dict[str, Value]  # Key oder ID der Spalte -> Wert
    after: str | None = None


class Row(BaseModel):
    id: str
    table_id: str
    position: str
    values: dict[str, Value | None]  # col_id -> Wert
    created_at: datetime
    created_by: Actor | None = None
    updated_at: datetime
    updated_by: Actor | None = None
    version: int = 1


class FilterCondition(Strict):
    column: str
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "is_null"] = "eq"
    value: Value | None = None  # darf einen {{ }}-Ausdruck enthalten


class SortSpec(Strict):
    column: str
    dir: Literal["asc", "desc"] = "asc"


class RowsPage(BaseModel):
    table: str
    rows: list[Row]
    total: int
