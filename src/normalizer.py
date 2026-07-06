from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from typing import Any


class _TableHTMLParser(HTMLParser):
    """Small stdlib HTML table extractor for SDP description HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str | None]]] = []
        self._in_table = 0
        self._in_row = False
        self._in_cell = False
        self._current_table: list[list[str | None]] | None = None
        self._current_row: list[str | None] | None = None
        self._current_cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            if self._in_table == 0:
                self._current_table = []
            self._in_table += 1
        elif tag == "tr" and self._in_table > 0:
            self._in_row = True
            self._current_row = []
        elif tag in {"td", "th"} and self._in_table > 0 and self._in_row:
            self._in_cell = True
            self._current_cell = []
        elif tag == "br" and self._in_cell:
            self._current_cell.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._in_cell:
            if self._current_row is not None:
                self._current_row.append(_clean_cell("".join(self._current_cell)))
            self._current_cell = []
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._current_table is not None and self._current_row is not None:
                self._current_table.append(self._current_row)
            self._current_row = None
            self._in_row = False
        elif tag == "table" and self._in_table > 0:
            self._in_table -= 1
            if self._in_table == 0 and self._current_table is not None:
                self.tables.append(self._current_table)
                self._current_table = None

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)


def _clean_cell(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = html.unescape(str(value))
    cleaned = cleaned.replace("\xa0", " ").replace("\u200b", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else None


def _normalize_key(value: str | None) -> str:
    value = _clean_cell(value) or "field"
    lowered = value.lower()

    # Drop descriptive conditions that should not become field names.
    lowered = re.sub(r",?\s*if\s+request\s+to\s+aws", "", lowered, flags=re.I)
    lowered = re.sub(r",?\s*if\s+request\s+for\s+aws", "", lowered, flags=re.I)
    lowered = re.sub(r",?\s*if\s+temporary", "", lowered, flags=re.I)
    lowered = re.sub(r"\(\s*dd\s*/\s*mm\s*/\s*yyyy\s*\)", "", lowered, flags=re.I)

    alias_patterns = [
        (r"^no$", "no"),
        (r"^aws\s+account$", "account_id"),
        (r"^waf\s+name$", "waf_name"),
        (r"^rules?\s+name$", "rules_name"),
        (r"^rules?\s+detail$", "rules_detail"),
        (r"^action\s+permit\s*/\s*deny$", "action"),
        (r"^status\s*\(\s*add\s*/\s*remove\s*/\s*modify\s*\)$", "status"),
    ]
    for pattern, alias in alias_patterns:
        if re.match(pattern, lowered, flags=re.I):
            return alias

    lowered = lowered.replace("&", " and ")
    lowered = re.sub(r"[/\\]+", "_", lowered)
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
    lowered = re.sub(r"_+", "_", lowered).strip("_")
    return lowered or "field"


def _dedupe_keys(keys: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for key in keys:
        count = seen.get(key, 0) + 1
        seen[key] = count
        result.append(key if count == 1 else f"{key}_{count}")
    return result


def extract_html_tables(description_html: str | None) -> list[list[list[str | None]]]:
    if not description_html:
        return []
    parser = _TableHTMLParser()
    parser.feed(description_html)
    return parser.tables


def _row_has_data(row: list[str | None]) -> bool:
    return any(_clean_cell(cell) for cell in row)


def _first_non_empty_row_index(table: list[list[str | None]]) -> int | None:
    for index, row in enumerate(table):
        if _row_has_data(row):
            return index
    return None


def _table_score(table: list[list[str | None]]) -> tuple[int, int, int]:
    header_index = _first_non_empty_row_index(table)
    if header_index is None:
        return (0, 0, 0)
    headers = table[header_index]
    header_count = sum(1 for cell in headers if _clean_cell(cell))
    data_count = sum(1 for row in table[header_index + 1 :] if _row_has_data(row))
    has_no_header = int(any((_clean_cell(cell) or "").lower() == "no" for cell in headers))
    return (has_no_header, data_count, header_count)


def choose_description_table(tables: list[list[list[str | None]]]) -> tuple[int | None, list[list[str | None]] | None]:
    candidates: list[tuple[tuple[int, int, int], int, list[list[str | None]]]] = []
    for index, table in enumerate(tables):
        score = _table_score(table)
        if score[1] > 0 and score[2] >= 2:
            candidates.append((score, index, table))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, index, table = candidates[0]
    return index, table


def parse_description_table(description_html: str | None) -> dict[str, Any]:
    tables = extract_html_tables(description_html)
    table_index, table = choose_description_table(tables)

    if table_index is None or table is None:
        return {
            "table_found": False,
            "table_index": None,
            "headers": [],
            "normalized_headers": [],
            "rows": [],
        }

    header_index = _first_non_empty_row_index(table)
    assert header_index is not None

    headers = [_clean_cell(cell) or f"Column {i + 1}" for i, cell in enumerate(table[header_index])]
    normalized_headers = _dedupe_keys([_normalize_key(header) for header in headers])

    rows: list[dict[str, str | None]] = []
    for raw_row in table[header_index + 1 :]:
        if not _row_has_data(raw_row):
            continue

        padded = list(raw_row[: len(normalized_headers)])
        while len(padded) < len(normalized_headers):
            padded.append(None)

        item = {
            key: _clean_cell(value)
            for key, value in zip(normalized_headers, padded, strict=False)
        }

        if any(value is not None for value in item.values()):
            rows.append(item)

    return {
        "table_found": True,
        "table_index": table_index,
        "headers": headers,
        "normalized_headers": normalized_headers,
        "rows": rows,
    }


def _nested_get(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _name(value: Any) -> str | None:
    if isinstance(value, dict):
        if value.get("name") is not None:
            return str(value.get("name"))
        if value.get("display_value") is not None:
            return str(value.get("display_value"))
        return None
    if value is None:
        return None
    return str(value)


def _email(value: Any) -> str | None:
    if isinstance(value, dict):
        email = value.get("email") or value.get("email_id")
        return str(email) if email else None
    return None


def _person(value: Any) -> dict[str, Any]:
    person = value if isinstance(value, dict) else {}
    department = person.get("department") if isinstance(person.get("department"), dict) else None
    return {
        "name": _name(person),
        "email": _email(person),
        "department": _name(department),
        "site": _name(_nested_get(department or {}, "site")),
    }


def normalize_sdp_request(raw_payload: dict[str, Any]) -> dict[str, Any]:
    """
    Convert one SDP request detail payload into the generic AI input shape.

    This is intentionally table-driven: service-specific fields come only from
    the first meaningful HTML table in request.description.
    """
    request = raw_payload.get("request") if isinstance(raw_payload.get("request"), dict) else raw_payload
    if not isinstance(request, dict):
        raise TypeError("normalize_sdp_request expected an SDP request dict or {'request': dict} payload.")

    requester = _person(request.get("requester"))
    technician = _person(request.get("technician"))
    group_name = _name(request.get("group"))

    if technician["site"] is None:
        technician["site"] = _name(request.get("site"))

    description = parse_description_table(request.get("description"))

    return {
        "ticket": {
            "ticket_id": str(request.get("id")) if request.get("id") is not None else None,
            "subject": request.get("subject"),
            "status": _name(request.get("status")),
            "template": _name(request.get("template")),
            "service_category": _name(request.get("service_category")),
            "priority": _name(request.get("priority")),
            "group": group_name,
            "requester": requester,
            "technician": {
                "name": technician.get("name"),
                "email": technician.get("email"),
                "group": group_name,
            },
        },
        "description": description,
    }



def build_final_ai_input(
    *,
    normalized_input: dict[str, Any],
    policy: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "normalized_input": normalized_input,
        "policy": policy or {},
    }


def dumps_pretty(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)
