"""Weather agent built with LangChain, instrumented with the Microsoft
OpenTelemetry distro so its spans flow into Application Insights.

This file is the runtime that lives *outside* Foundry (e.g. on Azure
Container Apps, GCP Cloud Run, AWS, on-prem...). Foundry only stores a
registration record (see ``register_external_agent.py``) and reads the
spans this process emits.

Reference for the LangChain + distro setup:
https://github.com/microsoft/opentelemetry-distro-python/blob/main/samples/langchain/sample_langchain_instrumentation.py

Note: today the Microsoft distro does not yet accept ``otel_agent_id`` as
an input (https://github.com/microsoft/opentelemetry-distro-python/issues/148).
Until that ships, ``gen_ai.agent.id`` falls back to whatever the
LangChain instrumentation emits. The Foundry registration uses the same
agent name so the trace view still resolves once the distro fix lands.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

# --- OTel: configure the Microsoft distro BEFORE importing anything that
# should be instrumented at runtime. ----------------------------------------
from microsoft.opentelemetry.distro import configure  # type: ignore

configure()  # reads APPLICATIONINSIGHTS_CONNECTION_STRING from env

AGENT_NAME = os.environ.get("AGENT_NAME", "weather-agent")
# Emitted on every OTel span as gen_ai.agent.id. Once the Microsoft
# distro accepts an explicit otel_agent_id
# (https://github.com/microsoft/opentelemetry-distro-python/issues/148)
# this value will be wired into configure(...). Until then it's read
# here only so the rest of the sample can stay consistent.
OTEL_AGENT_ID = os.environ.get("OTEL_AGENT_ID", AGENT_NAME)


# --- Tools -----------------------------------------------------------------
@tool
def get_current_weather(city: str) -> str:
    """Return the current weather for the given city.

    This is a stub that returns deterministic fake data so the sample is
    runnable without a third-party weather API key.
    """
    fake = {
        "seattle": "59F and raining",
        "new york": "72F and partly cloudy",
        "tokyo": "68F and clear",
        "london": "55F and overcast",
    }
    return fake.get(city.lower(), f"70F and sunny in {city}")


@tool
def get_forecast(city: str, days: int = 3) -> str:
    """Return a short multi-day forecast for the given city."""
    return f"{days}-day forecast for {city}: mild temperatures, occasional showers."


# --- Agent -----------------------------------------------------------------
def build_agent():
    llm = AzureChatOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        temperature=0,
    )
    return create_react_agent(
        model=llm,
        tools=[get_current_weather, get_forecast],
        prompt=SystemMessage(
            content=(
                "You are a helpful weather assistant. Use the provided "
                "tools to answer questions about current weather and "
                "short-term forecasts. Be concise."
            )
        ),
    )


# --- HTTP surface ----------------------------------------------------------
class AskRequest(BaseModel):
    question: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.agent = build_agent()
    yield


app = FastAPI(title=AGENT_NAME, lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "agent": AGENT_NAME}


@app.post("/ask")
def ask(req: AskRequest):
    agent = app.state.agent
    result = agent.invoke({"messages": [HumanMessage(content=req.question)]})
    final = result["messages"][-1].content
    return {"agent": AGENT_NAME, "answer": final}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "weather_agent:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
