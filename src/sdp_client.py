from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from src.config import load_project_env


class ServiceDeskPlusError(RuntimeError):
    """Raised when the ServiceDeskPlus API returns an error response."""


@dataclass(frozen=True)
class ServiceDeskPlusClient:
    """Small stdlib-only ServiceDeskPlus API client for the polling PoC."""

    base_url: str
    auth_token: str

    @classmethod
    def from_env(cls) -> "ServiceDeskPlusClient":
        load_project_env(override=True)

        import os

        base_url = os.getenv("SDP_BASE_URL", "https://digicare.japfa.com").rstrip("/")
        auth_token = os.getenv("SDP_AUTHTOKEN")

        if not auth_token:
            raise ServiceDeskPlusError(
                "Missing SDP_AUTHTOKEN in the project .env file. "
                "Add SDP_AUTHTOKEN=... to .env before running the poller."
            )

        return cls(base_url=base_url, auth_token=auth_token)

    def _request_json(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        query = ""
        if params:
            query = "?" + urllib.parse.urlencode(params)

        url = f"{self.base_url}{path}{query}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.manageengine.sdp.v3+json",
                "authtoken": self.auth_token,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise ServiceDeskPlusError(
                f"SDP API HTTP {exc.code} for {path}: {error_body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ServiceDeskPlusError(f"SDP API request failed for {path}: {exc}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ServiceDeskPlusError(f"SDP API returned non-JSON response for {path}: {body[:500]}") from exc

    def list_requests_created_after(
        self,
        created_after_ms: int,
        *,
        row_count: int = 100,
        start_index: int = 1,
    ) -> dict[str, Any]:
        """
        Fetch one page of requests created after the engine startup watermark.

        The caller is responsible for following list_info.has_more_rows by
        increasing start_index.
        """
        input_data = {
            "list_info": {
                "row_count": row_count,
                "start_index": start_index,
                "sort_field": "created_time",
                "sort_order": "asc",
                "search_criteria": {
                    "field": "created_time",
                    "condition": "greater than",
                    "value": str(created_after_ms),
                },
            }
        }

        return self._request_json(
            "/api/v3/requests",
            params={"input_data": json.dumps(input_data, separators=(",", ":"))},
        )

    def iter_requests_created_after(
        self,
        created_after_ms: int,
        *,
        row_count: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch all currently available pages of requests created after the watermark."""
        start_index = 1
        requests: list[dict[str, Any]] = []

        while True:
            page = self.list_requests_created_after(
                created_after_ms,
                row_count=row_count,
                start_index=start_index,
            )
            page_requests = page.get("requests") or []
            requests.extend(page_requests)

            list_info = page.get("list_info") or {}
            has_more_rows = bool(list_info.get("has_more_rows"))
            returned_count = int(list_info.get("row_count") or len(page_requests) or 0)

            if not has_more_rows or returned_count <= 0:
                break

            start_index += returned_count

        return requests

    def get_request(self, request_id: str | int) -> dict[str, Any]:
        """Fetch the full detail payload for one request ID."""
        response = self._request_json(f"/api/v3/requests/{request_id}")
        request = response.get("request")

        if not isinstance(request, dict):
            raise ServiceDeskPlusError(
                f"SDP detail response for request {request_id} did not contain a request object."
            )

        return request


def nested_get(data: dict[str, Any], *keys: str) -> Any:
    """Safely read a nested value from dict payloads."""
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def request_id_from_payload(request: dict[str, Any]) -> str | None:
    value = request.get("id")
    return str(value) if value is not None else None


def template_name_from_payload(request: dict[str, Any]) -> str | None:
    value = nested_get(request, "template", "name")
    return str(value).strip() if value is not None else None


def created_time_ms_from_payload(request: dict[str, Any]) -> int | None:
    value = nested_get(request, "created_time", "value")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
