"""
finish Tool for Tracker.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import sys
import json
from typing import Any, Dict


def finish(report: str) -> Dict[str, Any]:
    """
    Terminates the research loop and outputs the synthesized report.
    
    Parameters:
        report: Final synthesized markdown report content.
        
    Returns:
        Structured completion status dictionary.
    """
    return {
        "status": "finished",
        "report_length": len(report),
        "report": report
    }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) < 2:
        print("Usage: python -m tracker.tools.finish <report_content>")
        sys.exit(1)

    content = " ".join(sys.argv[1:])
    result = finish(content)
    print(json.dumps(result, indent=2, ensure_ascii=False))
