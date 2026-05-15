"""Query the project's Application Insights and confirm spans tagged
with the expected gen_ai.agent.id have arrived.

Used by ``deploy.sh`` / ``deploy.ps1`` after generating traffic so the
deploy script can fail loudly if instrumentation is misconfigured.
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta

from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryStatus

AGENT_NAME = os.environ.get("AGENT_NAME", "weather-agent")
OTEL_AGENT_ID = os.environ.get("OTEL_AGENT_ID", AGENT_NAME)
RESOURCE_ID = os.environ.get("APPINSIGHTS_RESOURCE_ID")
LOOKBACK_MIN = int(os.environ.get("VALIDATE_LOOKBACK_MIN", "15"))
MIN_SPANS = int(os.environ.get("VALIDATE_MIN_SPANS", "1"))


def main() -> int:
    if not RESOURCE_ID:
        raise SystemExit(
            "Set APPINSIGHTS_RESOURCE_ID to the full ARM resource ID of the "
            "Application Insights component connected to the Foundry project, "
            "e.g. /subscriptions/<sub>/resourceGroups/<rg>/providers/"
            "microsoft.insights/components/<name>."
        )

    client = LogsQueryClient(DefaultAzureCredential())
    # OTel spans land in the `dependencies` table; gen_ai.* attributes are
    # surfaced under customDimensions.
    kql = f"""
    dependencies
    | where timestamp > ago({LOOKBACK_MIN}m)
    | where tostring(customDimensions["gen_ai.agent.id"]) == "{OTEL_AGENT_ID}"
    | summarize spans = count(), last_seen = max(timestamp)
    """
    response = client.query_resource(
        resource_id=RESOURCE_ID,
        query=kql,
        timespan=timedelta(minutes=LOOKBACK_MIN),
    )
    if response.status != LogsQueryStatus.SUCCESS:
        print(f"Query failed: {response}")
        return 2

    rows = response.tables[0].rows
    if not rows:
        print("No matching spans returned.")
        return 1

    spans, last_seen = rows[0][0], rows[0][1]
    print(f"Found {spans} spans for gen_ai.agent.id={OTEL_AGENT_ID} (last_seen={last_seen})")
    if spans < MIN_SPANS:
        print(f"Expected at least {MIN_SPANS}; failing.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
