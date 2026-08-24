"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from pydantic_ai.exceptions import AgentRunError

from .agent import run_research
from .cache import ResponseCache
from .config import load_settings
from .errors import ResearchAgentError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-agent",
        description="Research SEC filings and U.S. federal data with primary-source citations.",
    )
    parser.add_argument("question", nargs="?", help="Research question")
    parser.add_argument("--refresh", action="store_true", help="Ignore fresh cache entries")
    parser.add_argument("--no-cache", action="store_true", help="Disable the local response cache")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON")
    parser.add_argument("--clear-cache", action="store_true", help="Clear cached API responses")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.clear_cache:
        cache = ResponseCache()
        try:
            cache.clear()
        finally:
            cache.close()
        print("Cache cleared.")
        return
    if not args.question:
        build_parser().error("a question is required unless --clear-cache is used")

    settings = load_settings()
    try:
        result = asyncio.run(
            run_research(
                args.question,
                settings,
                refresh=args.refresh,
                use_cache=not args.no_cache,
            )
        )
    except (ResearchAgentError, AgentRunError, KeyboardInterrupt) as exc:
        print(f"research-agent: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if args.json_output:
        print(
            json.dumps(
                {
                    "answer": result.answer,
                    "model_usage": result.model_usage,
                    "http_requests": result.http_requests,
                    "model": settings.llm_model,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    else:
        print(result.answer)
        usage = ", ".join(f"{key}={value}" for key, value in result.model_usage.items())
        print(f"\nRun: model={settings.llm_model}; http_requests={result.http_requests}; {usage}")


if __name__ == "__main__":
    main()
