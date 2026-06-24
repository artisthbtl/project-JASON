import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.workflow import build_workflow

ticket_input = {
    "instruction": "Treat this JSON as a ServiceDeskPlus AWS ticket automation task. Plan the work, use AWS MCP tools when needed, and produce the expected outputs.",
    "ticket": {
        "source_system": "servicedeskplus",
        "ticket_id": "423033",
        "subject": "Request waf",
        "status": "Closed",
        "template": "Cloud-WAF Create-Modify Rule",
        "request_type": "Service Request",
        "category": "Server",
        "service_category": "Security",
        "priority": "Medium",
        "impact": "Medium",
        "urgency": "Medium",
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
        "task_type": "aws_waf_create",
        "service": "wafv2",
        "operation": "create_web_acl",
        "description": "Create AWS WAF Web ACLs for the requested non-production application resources.",
        "resources": [
            {
            "account_alias": "jci ho non prod",
            "account_id": "948097794244",
            "region": "ap-southeast-1",
            "scope": "REGIONAL",
            "waf_name": "twaf-admin",
            "rules": {
                "type": "aws_managed_rule_groups",
                "default_action": "allow",
                "managed_rule_groups": [
                {
                    "priority": 0,
                    "policy_rule_name": "AWS-AWSManagedRulesAmazonIpReputationList",
                    "vendor_name": "AWS",
                    "managed_rule_group_name": "AWSManagedRulesAmazonIpReputationList",
                    "override_action": "none"
                },
                {
                    "priority": 1,
                    "policy_rule_name": "AWS-AWSManagedRulesAnonymousIpList",
                    "vendor_name": "AWS",
                    "managed_rule_group_name": "AWSManagedRulesAnonymousIpList",
                    "override_action": "none"
                },
                {
                    "priority": 2,
                    "policy_rule_name": "AWS-AWSManagedRulesLinuxRuleSet",
                    "vendor_name": "AWS",
                    "managed_rule_group_name": "AWSManagedRulesLinuxRuleSet",
                    "override_action": "none"
                },
                {
                    "priority": 3,
                    "policy_rule_name": "AWS-AWSManagedRulesCommonRuleSet",
                    "vendor_name": "AWS",
                    "managed_rule_group_name": "AWSManagedRulesCommonRuleSet",
                    "override_action": "none"
                },
                {
                    "priority": 4,
                    "policy_rule_name": "AWS-AWSManagedRulesKnownBadInputsRuleSet",
                    "vendor_name": "AWS",
                    "managed_rule_group_name": "AWSManagedRulesKnownBadInputsRuleSet",
                    "override_action": "none"
                },
                {
                    "priority": 5,
                    "policy_rule_name": "AWS-AWSManagedRulesPHPRuleSet",
                    "vendor_name": "AWS",
                    "managed_rule_group_name": "AWSManagedRulesPHPRuleSet",
                    "override_action": "none"
                },
                {
                    "priority": 6,
                    "policy_rule_name": "AWS-AWSManagedRulesSQLiRuleSet",
                    "vendor_name": "AWS",
                    "managed_rule_group_name": "AWSManagedRulesSQLiRuleSet",
                    "override_action": "none"
                }
                ]
            }
            },
            {
            "account_alias": "jci ho non prod",
            "account_id": "948097794244",
            "region": "ap-southeast-1",
            "scope": "REGIONAL",
            "waf_name": "twaf",
            "rules": {
                "type": "aws_managed_rule_groups",
                "default_action": "allow",
                "managed_rule_groups": [
                {
                    "priority": 0,
                    "policy_rule_name": "AWS-AWSManagedRulesAmazonIpReputationList",
                    "vendor_name": "AWS",
                    "managed_rule_group_name": "AWSManagedRulesAmazonIpReputationList",
                    "override_action": "none"
                },
                {
                    "priority": 1,
                    "policy_rule_name": "AWS-AWSManagedRulesAnonymousIpList",
                    "vendor_name": "AWS",
                    "managed_rule_group_name": "AWSManagedRulesAnonymousIpList",
                    "override_action": "none"
                },
                {
                    "priority": 2,
                    "policy_rule_name": "AWS-AWSManagedRulesLinuxRuleSet",
                    "vendor_name": "AWS",
                    "managed_rule_group_name": "AWSManagedRulesLinuxRuleSet",
                    "override_action": "none"
                },
                {
                    "priority": 3,
                    "policy_rule_name": "AWS-AWSManagedRulesCommonRuleSet",
                    "vendor_name": "AWS",
                    "managed_rule_group_name": "AWSManagedRulesCommonRuleSet",
                    "override_action": "none"
                },
                {
                    "priority": 4,
                    "policy_rule_name": "AWS-AWSManagedRulesKnownBadInputsRuleSet",
                    "vendor_name": "AWS",
                    "managed_rule_group_name": "AWSManagedRulesKnownBadInputsRuleSet",
                    "override_action": "none"
                },
                {
                    "priority": 5,
                    "policy_rule_name": "AWS-AWSManagedRulesPHPRuleSet",
                    "vendor_name": "AWS",
                    "managed_rule_group_name": "AWSManagedRulesPHPRuleSet",
                    "override_action": "none"
                },
                {
                    "priority": 6,
                    "policy_rule_name": "AWS-AWSManagedRulesSQLiRuleSet",
                    "vendor_name": "AWS",
                    "managed_rule_group_name": "AWSManagedRulesSQLiRuleSet",
                    "override_action": "none"
                }
                ]
            }
            }
        ],
    },
    "guardrails": {
        "allowed_aws_actions": [
            "wafv2:ListWebACLs",
            "wafv2:GetWebACL",
            "wafv2:CreateWebACL",
            "wafv2:AssociateWebACL",
            "sts:GetCallerIdentity",
        ],
        "forbidden_aws_actions": [
            "wafv2:DeleteWebACL",
            "iam:*",
            "organizations:*",
            "account:*",
        ],
        "must_run_plan_before_execution": True,
    },
    "expected_outputs": {
        "planning_output_required": True,
        "execution_summary_required": True,
        "ticket_resolution_required": True,
        "ticket_resolution_format": {
            "include_resource_name": True,
            "include_resource_arn": True,
            "include_region": True,
            "include_account_id": True,
            "include_policy_baseline_used": True,
        },
    },
}

async def main():
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

    print("\nWorkflow status:\n")
    print(response.get("workflow_status"))

    print("\nFinal output:\n")
    print(response.get("final_output") or response.get("execution_plan"))


if __name__ == "__main__":
    asyncio.run(main())
