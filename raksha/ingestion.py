"""Read supported inputs without exporting unparsed bytes."""

import csv
import io
import json
from dataclasses import dataclass


class Quarantine(ValueError):
    """A file cannot be parsed safely. Its reason must be a fixed code."""


@dataclass(frozen=True)
class Document:
    kind: str
    content: str | list[list[str]] | dict | list
    delimiter: str = ","


def decode(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def parse_json(text: str) -> Document:
    try:
        data = json.loads(text)
    except RecursionError:
        raise Quarantine("json_too_deep") from None
    except ValueError:
        raise Quarantine("malformed_json") from None
    pending = [(data, 0)]
    while pending:
        node, depth = pending.pop()
        if depth > 128:
            raise Quarantine("json_too_deep")
        if isinstance(node, dict):
            pending.extend((value, depth + 1) for value in node.values())
        elif isinstance(node, list):
            pending.extend((value, depth + 1) for value in node)
    kind = "fhir" if isinstance(data, dict) and data.get("resourceType") == "Bundle" else "json"
    return Document(kind, data)


def parse(raw: bytes, suffix: str) -> Document:
    if suffix not in {".csv", ".tsv", ".json", ".txt"}:
        raise Quarantine("unsupported_format")
    if raw.startswith((b"%PDF-", b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"PK\x03\x04")):
        raise Quarantine("unsupported_format")
    try:
        text = decode(raw)
    except UnicodeError:
        raise Quarantine("undecodable_text") from None
    stripped = text.lstrip()
    if not stripped:
        raise Quarantine("empty_file")
    if any(ord(char) < 32 and char not in "\t\r\n\f" for char in text):
        raise Quarantine("binary_content")
    if stripped.startswith(("<?xml", "<!DOCTYPE", "<html")):
        raise Quarantine("unsupported_format")
    if suffix == ".json" or stripped.startswith("{") or (
        suffix in {".csv", ".tsv"} and stripped.startswith("[")
    ):
        return parse_json(text)
    if suffix == ".txt":
        return Document("text", text)
    delimiter = "\t" if suffix == ".tsv" else ","
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True))
    except csv.Error:
        raise Quarantine("malformed_delimited") from None
    return Document("delimited", rows, delimiter)
