import asyncio
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db import finish_ticket_job, init_db, upsert_ticket_job, update_ticket_status
from src.workflow import build_workflow

ticket_input = {
    "instruction": "Treat this JSON as a ServiceDeskPlus AWS ticket automation task. Plan the work, use AWS MCP tools when needed, and produce the expected outputs.",
    "name": "WAF Creation Request",
    "ticket": {
        "ticket_id": "443123",
        "subject": "Request waf",
        "status": "Open",
        "template": "Cloud-WAF Create-Modify Rule",
        "service_category": "Security",
        "priority": "Medium",
        "group": "Security Administrator",
        "requester": {
            "name": "Ario Singgih Permana",
            "email": "ario.permana@japfa.com",
            "department": "GLOBAL TECH. INFRASTRUCTURE",
            "site": "Corporate Shared Services JCI - HO Jakarta",
        },
        "technician": {
            "name": "Marcello Widiyarto Kusumo",
            "email": "marcello.kusumo@japfa.com",
            "group": "Security Administrator",
        },
    },
    "task": {
        "resources": [
            {
                "account_id": "948097794244",
                "waf_name": "twaf",
            },
            {
                "account_id": "948097794244",
                "waf_name": "twaf-admin",
            },
        ],
    },
}


async def main():
    init_db()

    ticket_id = ticket_input["ticket"]["ticket_id"]
    upsert_ticket_job(ticket_id, status="received")
    update_ticket_status(ticket_id, status="running")
    workflow_started_at = time.perf_counter()

    workflow = await build_workflow()

    config = {
        "configurable": {
            "thread_id": f"ticket-{ticket_input['ticket']['ticket_id']}"
        }
    }

    response = await workflow.ainvoke(
        {"ticket_input": ticket_input},
        config=config,
    )

    resolution_time = time.perf_counter() - workflow_started_at
    final_status = response.get("workflow_status", "unknown")
    finish_ticket_job(ticket_id, status=final_status, resolution_time_seconds=resolution_time)

    print("\nWorkflow status:\n")
    print(response.get("workflow_status"))

    print("\nFinal output:\n")
    print(response.get("final_output") or response.get("execution_plan"))


if __name__ == "__main__":
    asyncio.run(main())
