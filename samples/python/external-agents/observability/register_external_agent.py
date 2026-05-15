"""Register the externally hosted weather agent in Foundry.

After this runs successfully, open the Foundry portal -> your project ->
Agents -> ``weather-agent`` to see the trace view light up with spans
emitted by the running container.

Prereqs:
    * FOUNDRY_PROJECT_ENDPOINT env var
    * AAD credentials with permission to create agents in the project
    * The external runtime (weather_agent.py) is already emitting OTel
      spans to the Application Insights connected to the Foundry project
"""

from __future__ import annotations

import os

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import ExternalAgentDefinition
from azure.identity import DefaultAzureCredential

AGENT_NAME = os.environ.get("AGENT_NAME", "weather-agent")
# The id the running agent emits as gen_ai.agent.id on its OTel spans.
# Defaults to AGENT_NAME but can differ -- e.g. "weather-agent-v1".
OTEL_AGENT_ID = os.environ.get("OTEL_AGENT_ID", AGENT_NAME)


def main() -> None:
    project_client = AIProjectClient(
        endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        credential=DefaultAzureCredential(),
        # External agents are gated behind a preview feature flag during
        # public preview. See spec: Foundry-Features: ExternalAgents=V1Preview.
        allow_preview=True,
    )

    # First-time create goes through create_version() in azure-ai-projects
    # v2.1.0; called with a new agent_name it atomically creates the
    # agent + first registration revision. External agents are
    # versionless from the user's perspective.
    agent = project_client.agents.create_version(
        agent_name=AGENT_NAME,
        description="Weather agent hosted externally on Azure Container Apps.",
        definition=ExternalAgentDefinition(
            # Optional: defaults to agent_name. Set explicitly here so
            # the mapping to gen_ai.agent.id on the OTel spans is
            # obvious -- and to show otel_agent_id can differ from the
            # Foundry agent name (e.g. "weather-agent-v1").
            otel_agent_id=OTEL_AGENT_ID,
        ),
    )

    print(f"Registered external agent: {agent.name}")
    print(f"Resolved otel_agent_id  : {agent.versions.latest.definition.otel_agent_id}")
    print()
    print("Open the Foundry portal and navigate to:")
    print(f"  Project -> Agents -> {agent.name} -> Traces")
    print("to see traces emitted by the external runtime.")


if __name__ == "__main__":
    main()
