"""Node 01 Ingestion: CSV bytes -> RawTable. No semantics, no typing.

Contract: docs/nodes/01_ingestion.md
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path

ENCODINGS = ("utf-8-sig", "cp949", "latin-1")
_NON_WORD = re.compile(r"\W+")


@dataclass(frozen=True)
class Issue:
    code: str
    row: int | None
    detail: str


@dataclass(frozen=True)
class RawTable:
    name: str
    source: str
    sha256: str
    encoding: str
    delimiter: str
    columns: tuple[str, ...]
    raw_columns: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    issues: tuple[Issue, ...]


def normalize_header(h: str) -> str:
    return _NON_WORD.sub("_", h.strip().lower()).strip("_")


def _decode(data: bytes) -> tuple[str, str]:
    for enc in ENCODINGS:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise AssertionError("latin-1 decodes any bytes")


def _sniff(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _columns(raw: list[str], issues: list[Issue]) -> tuple[str, ...]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, h in enumerate(raw):
        name = normalize_header(h)
        if not name:
            name = f"col_{i}"
            issues.append(Issue("EMPTY_HEADER", None, f"column {i} has empty header"))
        if name in seen:
            seen[name] += 1
            dup = f"{name}_{seen[name]}"
            issues.append(Issue("DUPLICATE_COLUMN", None, f"{name!r} -> {dup!r}"))
            name = dup
        else:
            seen[name] = 1
        out.append(name)
    return tuple(out)


def ingest_csv(path: str | Path, name: str | None = None) -> RawTable:
    path = Path(path)
    data = path.read_bytes()
    if not data.strip():
        raise ValueError(f"{path}: empty file")
    text, enc = _decode(data)
    delim = _sniff(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delim)

    issues: list[Issue] = []
    raw_header = next(reader)
    columns = _columns(raw_header, issues)
    n = len(columns)

    rows: list[dict[str, str]] = []
    for fields in reader:
        line = reader.line_num
        if not any(f.strip() for f in fields):
            issues.append(Issue("BLANK_ROW", line, "skipped"))
            continue
        if len(fields) < n:
            issues.append(Issue("RAGGED_ROW", line, f"{len(fields)} fields < {n}, padded"))
            fields = fields + [""] * (n - len(fields))
        elif len(fields) > n:
            issues.append(Issue("RAGGED_ROW", line, f"{len(fields)} fields > {n}, dropped {fields[n:]!r}"))
            fields = fields[:n]
        row = dict(zip(columns, fields))
        row["_row"] = line
        rows.append(row)

    return RawTable(
        name=name or path.stem,
        source=str(path),
        sha256=hashlib.sha256(data).hexdigest(),
        encoding=enc,
        delimiter=delim,
        columns=columns,
        raw_columns=tuple(raw_header),
        rows=tuple(rows),
        issues=tuple(issues),
    )


def ingest(files: dict[str, str | Path]) -> dict[str, RawTable]:
    return {name: ingest_csv(p, name) for name, p in files.items()}
