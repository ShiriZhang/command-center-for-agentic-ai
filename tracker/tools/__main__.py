"""
CLI Dispatcher for Tracker Standalone Tools.
Allows direct execution of tools without model orchestration:
  python -m tracker.tools fetch_article <url>
  python -m tracker.tools search_web <query> [max_results]
  python -m tracker.tools finish <report>

CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import argparse
import json
import sys
from typing import List, Optional

from tracker.tools.fetch import fetch_article
from tracker.tools.search import search_web
from tracker.tools.finish import finish


def dispatch_tool(argv: Optional[List[str]] = None) -> int:
    """
    Parses CLI arguments and dispatches execution to the corresponding tool.
    Returns process exit code.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args_list = argv if argv is not None else sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="python -m tracker.tools",
        description="Standalone CLI tool invocation for Agentic Tracker without LLM orchestration."
    )
    subparsers = parser.add_subparsers(dest="tool_name", help="Tool to invoke")

    # Tool 1: fetch_article
    p_fetch = subparsers.add_parser(
        "fetch_article",
        aliases=["fetch"],
        help="Fetch and sanitize web article content with DNS SSRF guardrails"
    )
    p_fetch.add_argument("url", help="Target URL to fetch")

    # Tool 2: search_web
    p_search = subparsers.add_parser(
        "search_web",
        aliases=["search"],
        help="Execute web search across Tavily API and AI Dev Jobs candidate discovery"
    )
    p_search.add_argument("query", help="Primary search query")
    p_search.add_argument(
        "extra_args",
        nargs="*",
        help="Optional additional query keywords or numeric max_results limit"
    )
    p_search.add_argument(
        "--max-results", "-n",
        dest="max_results_flag",
        type=int,
        default=None,
        help="Maximum results to return (default: 5)"
    )

    # Tool 3: finish
    p_finish = subparsers.add_parser(
        "finish",
        help="Finalize research loop and output the synthesized report"
    )
    p_finish.add_argument("report", nargs="+", help="Synthesized report content text")

    if not args_list:
        parser.print_help()
        return 1

    parsed = parser.parse_args(args_list)

    if parsed.tool_name in ("fetch_article", "fetch"):
        result = fetch_article(parsed.url)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    elif parsed.tool_name in ("search_web", "search"):
        # Process query and limit
        query_parts = [parsed.query]
        max_results = parsed.max_results_flag or 5

        if parsed.extra_args:
            # Check if last token is an integer limit
            last_tok = parsed.extra_args[-1]
            if last_tok.isdigit() and len(parsed.extra_args) == 1 and parsed.max_results_flag is None:
                max_results = int(last_tok)
            elif last_tok.isdigit() and len(parsed.extra_args) > 1 and parsed.max_results_flag is None:
                max_results = int(last_tok)
                query_parts.extend(parsed.extra_args[:-1])
            else:
                query_parts.extend(parsed.extra_args)

        full_query = " ".join(query_parts)
        result = search_web(full_query, max_results=max_results)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0

    elif parsed.tool_name == "finish":
        report_content = " ".join(parsed.report)
        result = finish(report_content)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(dispatch_tool())
