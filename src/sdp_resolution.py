from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from src.config import load_project_env
from src.sdp_client import ServiceDeskPlusError


@dataclass(frozen=True)
class ServiceDeskPlusResolutionClient:
    """Small SDP v3 client for adding a resolution and changing request status."""

    base_url: str
    auth_token: str

    @classmethod
    def from_env(cls) -> "ServiceDeskPlusResolutionClient":
        load_project_env(override=True)
        base_url = os.getenv("SDP_BASE_URL", "https://digicare.japfa.com").rstrip("/")
        auth_token = os.getenv("SDP_AUTHTOKEN")

        if not auth_token:
            raise ServiceDeskPlusError(
                "Missing SDP_AUTHTOKEN in the project .env file. "
                "Add SDP_AUTHTOKEN=... before resolving SDP tickets."
            )

        return cls(base_url=base_url, auth_token=auth_token)

    def _request_form_json(
        self,
        *,
        method: str,
        path: str,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        encoded_body = urllib.parse.urlencode(
            {"input_data": json.dumps(input_data, ensure_ascii=False, separators=(",", ":"))}
        ).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=encoded_body,
            method=method.upper(),
            headers={
                "Accept": "application/vnd.manageengine.sdp.v3+json",
                "Content-Type": "application/x-www-form-urlencoded",
                "authtoken": self.auth_token,
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status_code = response.getcode()
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            parsed_error: dict[str, Any]
            try:
                parsed_error = json.loads(error_body)
            except json.JSONDecodeError:
                parsed_error = {"raw_response": error_body}
            raise ServiceDeskPlusError(
                f"SDP API failed: HTTP {exc.code} for {method.upper()} {path}\n"
                f"{json.dumps(parsed_error, indent=2, ensure_ascii=False)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ServiceDeskPlusError(f"SDP API request failed for {method.upper()} {path}: {exc}") from exc

        try:
            result = json.loads(body) if body else {}
        except json.JSONDecodeError:
            result = {"raw_response": body}

        if status_code < 200 or status_code >= 300:
            raise ServiceDeskPlusError(
                f"SDP API failed: HTTP {status_code} for {method.upper()} {path}\n"
                f"{json.dumps(result, indent=2, ensure_ascii=False)}"
            )

        return result

    def add_resolution(self, request_id: str, resolution_comment: str) -> dict[str, Any]:
        return self._request_form_json(
            method="POST",
            path=f"/api/v3/requests/{request_id}/resolutions",
            input_data={"resolution": {"content": resolution_comment}},
        )

    def set_status_resolved(self, request_id: str, status_name: str = "Resolved") -> dict[str, Any]:
        return self._request_form_json(
            method="PUT",
            path=f"/api/v3/requests/{request_id}",
            input_data={"request": {"status": {"name": status_name}}},
        )

    def resolve_ticket(
        self,
        request_id: str,
        resolution_comment: str,
        status_name: str = "Resolved",
    ) -> dict[str, Any]:
        resolution_result = self.add_resolution(request_id, resolution_comment)
        status_result = self.set_status_resolved(request_id, status_name)
        return {
            "resolution_result": resolution_result,
            "status_result": status_result,
        }
