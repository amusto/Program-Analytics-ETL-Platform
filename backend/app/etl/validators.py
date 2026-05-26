"""Row-level validation utilities.

The ETL extracts CSV rows as raw strings, normalizes empty cells to None,
then passes each row through the relevant Pydantic model. Anything that
fails validation is captured with its full error context so it can be
written to a failed-records sink instead of silently dropped.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generic, Iterator, Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


@dataclass
class ValidationFailure:
    """Captures a single row that failed validation."""

    source_file: str
    line_number: int
    raw_row: dict
    errors: list[dict]


@dataclass
class ValidationResult(Generic[T]):
    valid: list[T] = field(default_factory=list)
    failures: list[ValidationFailure] = field(default_factory=list)


def _normalize_row(row: dict[str, str]) -> dict[str, object]:
    """Normalize CSV cell values.

    CSV readers return empty strings for blank cells; Pydantic treats empty
    strings as present-but-blank, which breaks Optional[date]. Convert
    empties to None so optional fields parse correctly.
    """
    normalized: dict[str, object] = {}
    for key, value in row.items():
        if value is None or (isinstance(value, str) and value.strip() == ""):
            normalized[key] = None
        else:
            normalized[key] = value.strip() if isinstance(value, str) else value
    return normalized


def read_csv(path: Path) -> Iterator[tuple[int, dict[str, str]]]:
    """Yield (line_number, row_dict) for every data row.

    Line numbers are 1-based and account for the header row, so they match
    what a human would see opening the file in a spreadsheet app.
    """
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for idx, row in enumerate(reader, start=2):  # +1 header, +1 to 1-index
            yield idx, row


def validate_rows(
    path: Path,
    schema: Type[T],
) -> ValidationResult[T]:
    """Parse every row of `path` against `schema`, splitting valid from invalid."""
    valid: list[T] = []
    failures: list[ValidationFailure] = []

    for line_number, raw_row in read_csv(path):
        normalized = _normalize_row(raw_row)
        try:
            valid.append(schema.model_validate(normalized))
        except ValidationError as exc:
            failures.append(
                ValidationFailure(
                    source_file=path.name,
                    line_number=line_number,
                    raw_row=raw_row,
                    errors=[
                        {
                            "loc": list(err["loc"]),
                            "msg": err["msg"],
                            "type": err["type"],
                        }
                        for err in exc.errors()
                    ],
                )
            )
    return ValidationResult(valid=valid, failures=failures)
