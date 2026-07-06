from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.db import (
    DB_PATH,
    finish_ticket_job,
    get_service_template_by_template_name,
    get_ticket_job,
    init_db,
    update_ticket_sdp_resolution,
    update_ticket_status,
    update_ticket_token_usage,
    upsert_ticket_job,
    upsert_ticket_payload,
)
from src.normalizer import build_final_ai_input, normalize_sdp_request
from src.sdp_client import (
    ServiceDeskPlusError,
    created_time_ms_from_payload,
    request_id_from_payload,
    template_name_from_payload,
)
from src.sdp_resolution import ServiceDeskPlusResolutionClient


@dataclass(frozen=True)
class EngineRunOptions:
    row_count: int = 100
    target_template_name: str | None = None
    print_final_input: bool = True
    run_workflow: bool = False
    resolve_sdp_ticket: bool = False
    sdp_resolved_status_name: str = "Resolved"
    verbose: bool = True


DEFAULT_STATS: dict[str, int] = {
    "seen": 0,
    "already_known": 0,
    "queued": 0,
    "skipped_template": 0,
    "skipped_old": 0,
    "detail_errors": 0,
    "normalized": 0,
    "workflow_completed": 0,
    "workflow_failed": 0,
    "sdp_resolved": 0,
    "sdp_resolution_failed": 0,
}


def timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    print(f"[{timestamp()}] {message}", flush=True)


def dumps_pretty(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def print_final_ai_input(ticket_id: str, final_ai_input: dict[str, Any]) -> None:
    print("\n" + "=" * 90)
    print(f"FINAL AI INPUT ticket={ticket_id}")
    print("=" * 90)
    print(dumps_pretty(final_ai_input))
    print("=" * 90 + "\n")


def _execution_result_status(workflow_response: dict[str, Any]) -> str:
    execution_result = workflow_response.get("execution_result")
    if isinstance(execution_result, dict) and execution_result.get("status"):
        return str(execution_result.get("status")).strip().lower()
    return str(workflow_response.get("workflow_status") or "unknown").strip().lower()


def _resolution_comment_from_workflow(workflow_response: dict[str, Any]) -> str:
    execution_result = workflow_response.get("execution_result")
    if isinstance(execution_result, dict):
        resolution = execution_result.get("resolution")
        if isinstance(resolution, str) and resolution.strip():
            return resolution.strip()
        if resolution is not None:
            return dumps_pretty(resolution)

    final_output = workflow_response.get("final_output")
    if isinstance(final_output, str) and final_output.strip():
        try:
            parsed = json.loads(final_output)
        except json.JSONDecodeError:
            return final_output.strip()
        if isinstance(parsed, dict) and isinstance(parsed.get("resolution"), str):
            return parsed["resolution"].strip()
        return dumps_pretty(parsed)

    return "Automation workflow completed. No detailed resolution was returned by the execution agent."


class TicketAutomationEngine:
    """
    Central SDP -> parser -> workflow coordinator.

    This class owns application flow only. Reusable implementation details stay in
    src.db, src.sdp_client, src.normalizer, src.workflow, and src.sdp_resolution.
    """

    def __init__(self, client: Any, *, db_path: Path | str = DB_PATH) -> None:
        self.client = client
        self.db_path = db_path
        self._workflow: Any | None = None

    @staticmethod
    def _vlog(options: EngineRunOptions, message: str) -> None:
        if options.verbose:
            log(message)

    def _fetch_detail(self, summary: dict[str, Any]) -> dict[str, Any]:
        request_id = request_id_from_payload(summary)
        if not request_id:
            raise ServiceDeskPlusError("Request summary did not contain an id field.")
        return self.client.get_request(request_id)

    @staticmethod
    def _is_target_template(
        *,
        template_name: str | None,
        target_template_name: str | None,
    ) -> bool:
        if not template_name:
            return False
        if target_template_name:
            return template_name == target_template_name
        return True

    async def _get_workflow(self) -> Any:
        if self._workflow is None:
            from src.workflow import build_workflow

            self._workflow = await build_workflow()
        return self._workflow

    async def run_agent_workflow(
        self,
        *,
        ticket_id: str,
        final_ai_input: dict[str, Any],
        options: EngineRunOptions,
    ) -> dict[str, Any]:
        self._vlog(options, f"ENGINE_NODE workflow.start ticket={ticket_id}")
        update_ticket_status(ticket_id, "running", db_path=self.db_path)
        started_at = time.perf_counter()

        workflow = await self._get_workflow()
        config = {"configurable": {"thread_id": f"ticket-{ticket_id}"}}

        try:
            response = await workflow.ainvoke(
                {
                    "ticket_input": final_ai_input,
                    "task_document": final_ai_input.get("policy") or {},
                    "verbose": options.verbose,
                    "token_usage": {},
                },
                config=config,
            )
        except Exception:
            finish_ticket_job(
                ticket_id,
                "failed",
                time.perf_counter() - started_at,
                db_path=self.db_path,
            )
            self._vlog(options, f"ENGINE_NODE workflow.failed ticket={ticket_id}")
            raise

        token_usage = response.get("token_usage") if isinstance(response.get("token_usage"), dict) else {}
        if token_usage:
            update_ticket_token_usage(ticket_id, token_usage, db_path=self.db_path)

        final_status = str(response.get("workflow_status") or "unknown")
        finish_ticket_job(
            ticket_id,
            final_status,
            time.perf_counter() - started_at,
            db_path=self.db_path,
        )
        self._vlog(options, f"ENGINE_NODE workflow.done ticket={ticket_id} status={final_status}")
        return response

    def resolve_sdp_ticket_after_workflow(
        self,
        *,
        ticket_id: str,
        workflow_response: dict[str, Any],
        options: EngineRunOptions,
    ) -> dict[str, Any] | None:
        execution_status = _execution_result_status(workflow_response)
        allowed_statuses = {"completed", "partial"}

        if execution_status not in allowed_statuses:
            self._vlog(
                options,
                f"ENGINE_NODE sdp_resolution.skipped ticket={ticket_id} execution_status={execution_status}",
            )
            update_ticket_sdp_resolution(
                ticket_id,
                sdp_resolution_status="skipped_not_successful",
                resolution_comment=None,
                sdp_response={"execution_status": execution_status},
                db_path=self.db_path,
            )
            return None

        resolution_comment = _resolution_comment_from_workflow(workflow_response)
        self._vlog(options, f"ENGINE_NODE sdp_resolution.start ticket={ticket_id}")
        update_ticket_status(ticket_id, "resolving_sdp", db_path=self.db_path)
        update_ticket_sdp_resolution(
            ticket_id,
            sdp_resolution_status="running",
            resolution_comment=resolution_comment,
            db_path=self.db_path,
        )

        client = ServiceDeskPlusResolutionClient.from_env()
        result = client.resolve_ticket(
            request_id=ticket_id,
            resolution_comment=resolution_comment,
            status_name=options.sdp_resolved_status_name,
        )

        update_ticket_sdp_resolution(
            ticket_id,
            sdp_resolution_status="resolved",
            resolution_comment=resolution_comment,
            sdp_response=result,
            db_path=self.db_path,
        )
        update_ticket_status(ticket_id, "sdp_resolved", db_path=self.db_path)
        self._vlog(options, f"ENGINE_NODE sdp_resolution.done ticket={ticket_id}")
        return result

    async def process_supported_ticket(
        self,
        *,
        request_id: str,
        request_detail: dict[str, Any],
        service_template: dict[str, Any],
        options: EngineRunOptions,
    ) -> dict[str, Any]:
        self._vlog(options, f"ENGINE_NODE parsing.start ticket={request_id}")
        policy = service_template.get("policy") or {}
        normalized_input = normalize_sdp_request(request_detail)
        self._vlog(options, f"ENGINE_NODE parsing.done ticket={request_id}")

        self._vlog(options, f"ENGINE_NODE input_construction.start ticket={request_id}")
        final_ai_input = build_final_ai_input(
            normalized_input=normalized_input,
            policy=policy,
        )
        self._vlog(options, f"ENGINE_NODE input_construction.done ticket={request_id}")

        upsert_ticket_job(
            request_id,
            status="queued",
            service_template_id=service_template.get("id"),
            db_path=self.db_path,
        )
        upsert_ticket_payload(
            request_id,
            raw_ticket=request_detail,
            normalized_input=normalized_input,
            db_path=self.db_path,
        )

        self._vlog(
            options,
            f"QUEUED ticket={request_id} "
            f"template={normalized_input.get('ticket', {}).get('template')!r} "
            f"service_template_id={service_template.get('id')!r}",
        )

        if options.print_final_input:
            print_final_ai_input(request_id, final_ai_input)

        workflow_response: dict[str, Any] | None = None
        sdp_resolution_response: dict[str, Any] | None = None
        sdp_resolution_error: str | None = None
        if options.run_workflow:
            workflow_response = await self.run_agent_workflow(
                ticket_id=request_id,
                final_ai_input=final_ai_input,
                options=options,
            )
            print("\n" + "=" * 90)
            print(f"WORKFLOW OUTPUT ticket={request_id}")
            print("=" * 90)
            print(workflow_response.get("final_output") or dumps_pretty(workflow_response))
            print("=" * 90 + "\n")

            if options.resolve_sdp_ticket:
                try:
                    sdp_resolution_response = self.resolve_sdp_ticket_after_workflow(
                        ticket_id=request_id,
                        workflow_response=workflow_response,
                        options=options,
                    )
                except ServiceDeskPlusError as exc:
                    sdp_resolution_error = str(exc)
                    update_ticket_status(request_id, "sdp_resolution_failed", db_path=self.db_path)
                    update_ticket_sdp_resolution(
                        request_id,
                        sdp_resolution_status="failed",
                        sdp_response={"error": sdp_resolution_error},
                        db_path=self.db_path,
                    )
                    log(f"SDP_RESOLUTION_ERROR ticket={request_id} error={exc}")

        return {
            "normalized_input": normalized_input,
            "final_ai_input": final_ai_input,
            "workflow_response": workflow_response,
            "sdp_resolution_response": sdp_resolution_response,
            "sdp_resolution_error": sdp_resolution_error,
        }

    async def poll_once(
        self,
        *,
        engine_started_at_ms: int,
        options: EngineRunOptions,
    ) -> dict[str, int]:
        init_db(self.db_path)
        stats = dict(DEFAULT_STATS)

        self._vlog(options, "ENGINE_NODE polling.start")
        summaries = self.client.iter_requests_created_after(
            engine_started_at_ms,
            row_count=options.row_count,
        )
        self._vlog(options, f"ENGINE_NODE polling.done count={len(summaries)}")

        for summary in summaries:
            request_id = request_id_from_payload(summary)
            if not request_id:
                continue

            stats["seen"] += 1

            if get_ticket_job(request_id, db_path=self.db_path) is not None:
                stats["already_known"] += 1
                continue

            try:
                self._vlog(options, f"ENGINE_NODE detail_fetch.start ticket={request_id}")
                request_detail = self._fetch_detail(summary)
                self._vlog(options, f"ENGINE_NODE detail_fetch.done ticket={request_id}")
            except ServiceDeskPlusError as exc:
                stats["detail_errors"] += 1
                log(f"DETAIL_ERROR ticket={request_id} error={exc}")
                continue

            created_time_ms = created_time_ms_from_payload(request_detail)
            if created_time_ms is not None and created_time_ms <= engine_started_at_ms:
                stats["skipped_old"] += 1
                continue

            template_name = template_name_from_payload(request_detail)
            service_template = (
                get_service_template_by_template_name(template_name, db_path=self.db_path)
                if template_name
                else None
            )

            if not self._is_target_template(
                template_name=template_name,
                target_template_name=options.target_template_name,
            ) or service_template is None:
                upsert_ticket_job(
                    request_id,
                    status="skipped_template",
                    db_path=self.db_path,
                )
                upsert_ticket_payload(
                    request_id,
                    raw_ticket=request_detail,
                    db_path=self.db_path,
                )
                stats["skipped_template"] += 1
                self._vlog(options, f"SKIPPED ticket={request_id} template={template_name!r}")
                continue

            try:
                result = await self.process_supported_ticket(
                    request_id=request_id,
                    request_detail=request_detail,
                    service_template=service_template,
                    options=options,
                )
            except Exception as exc:
                stats["workflow_failed"] += 1
                log(f"WORKFLOW_ERROR ticket={request_id} error={exc}")
                continue

            stats["queued"] += 1
            stats["normalized"] += 1
            if options.run_workflow:
                stats["workflow_completed"] += 1
            if result.get("sdp_resolution_response") is not None:
                stats["sdp_resolved"] += 1
            if result.get("sdp_resolution_error") is not None:
                stats["sdp_resolution_failed"] += 1

        return stats

    async def poll_forever(
        self,
        *,
        engine_started_at_ms: int,
        interval_seconds: int,
        options: EngineRunOptions,
    ) -> None:
        while True:
            try:
                stats = await self.poll_once(
                    engine_started_at_ms=engine_started_at_ms,
                    options=options,
                )
                log(f"POLL_DONE stats={stats}")
            except ServiceDeskPlusError as exc:
                log(f"POLL_ERROR error={exc}")

            await asyncio.sleep(interval_seconds)
