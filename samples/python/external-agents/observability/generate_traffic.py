"""Hit the deployed weather agent with a handful of varied questions so
there are spans in Application Insights for the eval run to score.
"""

from __future__ import annotations

import os
import sys

import httpx

QUESTIONS = [
    "What's the weather in Seattle right now?",
    "Give me a 5-day forecast for Tokyo.",
    "Compare today's weather in New York and London.",
    "Should I bring an umbrella in Seattle today?",
    "What's the warmest of these cities right now: Seattle, Tokyo, London?",
]


def main() -> None:
    base_url = os.environ.get("AGENT_URL") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not base_url:
        raise SystemExit("Set AGENT_URL or pass the agent base URL as argv[1].")

    base_url = base_url.rstrip("/")
    with httpx.Client(timeout=60.0) as client:
        for q in QUESTIONS:
            print(f"\n>>> {q}")
            r = client.post(f"{base_url}/ask", json={"question": q})
            r.raise_for_status()
            print(r.json().get("answer"))


if __name__ == "__main__":
    main()
