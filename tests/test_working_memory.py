"""
Unit tests for tracker.memory.working (WorkingMemory).
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import pytest
from tracker.memory.working import WorkingMemory
from tracker.memory.semantic import SemanticMemory


def test_add_and_pop_candidate_priority_ordering():
    wm = WorkingMemory(target_k=10, max_steps=15)
    
    # Candidate A: standard role, no ATS
    cand_a = {
        "title": "Machine Learning Engineer",
        "company": "Company A",
        "url": "https://companyA.com/jobs/123",
        "date_posted": "2026-10-04",
        "source": "aidevboard"
    }
    # Candidate B: ATS role with salary (higher score)
    cand_b = {
        "title": "AI Engineer (Entry Level)",
        "company": "Company B",
        "apply_url": "https://boards.greenhouse.io/companyb/jobs/999",
        "date_posted": "2026-10-04",
        "salary": "$130k - $160k",
        "source": "aidevboard"
    }
    # Candidate C: Senior role (disqualified -> score 0 or False)
    cand_c = {
        "title": "Senior Staff AI Engineer",
        "company": "Company C",
        "url": "https://companyC.com/jobs/456",
        "date_posted": "2026-10-04",
        "source": "aidevboard"
    }

    assert wm.add_candidate(cand_a) is True
    assert wm.add_candidate(cand_b) is True
    # Disqualified senior candidate should not be added
    assert wm.add_candidate(cand_c) is False

    # Top candidate should be cand_b due to ATS and entry level / salary bonuses
    top = wm.pop_best_candidate()
    assert top is not None
    assert top["company"] == "Company B"
    assert top["priority_score"] > 0

    second = wm.pop_best_candidate()
    assert second is not None
    assert second["company"] == "Company A"

    assert wm.pop_best_candidate() is None


def test_candidate_url_deduplication():
    wm = WorkingMemory()
    cand1 = {
        "title": "AI Researcher",
        "company": "OpenAI",
        "url": "https://boards.greenhouse.io/openai/jobs/101/"
    }
    cand2 = {
        "title": "AI Researcher",
        "company": "OpenAI",
        "url": "https://BOARDS.GREENHOUSE.IO/openai/jobs/101"
    }
    assert wm.add_candidate(cand1) is True
    assert wm.add_candidate(cand2) is False
    assert len(wm.candidate_queue) == 1


def test_add_verified_job_and_goal_satisfaction():
    wm = WorkingMemory(target_k=2)
    assert not wm.is_goal_satisfied()

    job1 = {
        "title": "Machine Learning Engineer",
        "company": "Anthropic",
        "url": "https://jobs.lever.co/anthropic/abc-123"
    }
    job2 = {
        "title": "Research Engineer",
        "company": "DeepMind",
        "url": "https://careers.google.com/jobs/results/456"
    }

    assert wm.add_verified_job(job1) is True
    # Duplicate submission should return False
    assert wm.add_verified_job(job1) is False
    assert not wm.is_goal_satisfied()

    assert wm.add_verified_job(job2) is True
    assert wm.is_goal_satisfied()
    assert len(wm.verified_jobs) == 2


def test_get_progress_status_block():
    wm = WorkingMemory(target_k=10, max_steps=12)
    
    # Early step
    status_early = wm.get_progress_status_block(current_step=3)
    assert "Goal Progress: 0/10 verified positions collected." in status_early
    assert "Step Budget: Step 3/12 (9 steps remaining)." in status_early
    assert "Candidate queue empty" in status_early

    # Add a candidate
    wm.add_candidate({
        "title": "Junior ML Engineer",
        "company": "Scale AI",
        "url": "https://boards.greenhouse.io/scaleai/jobs/1"
    })
    status_with_cand = wm.get_progress_status_block(current_step=4)
    assert "Candidates in Queue: 1 pending inspection." in status_with_cand
    assert "Fetch top candidate 'Junior ML Engineer' at 'Scale AI'" in status_with_cand

    # Urgent countdown step (<= 2 steps left)
    status_urgent = wm.get_progress_status_block(current_step=11)
    assert "URGENT BUDGET WARNING: Only 1 steps left!" in status_urgent

    # Goal satisfied
    for i in range(10):
        wm.add_verified_job({
            "title": f"Engineer {i}",
            "company": f"Company {i}",
            "url": f"https://jobs.example.com/{i}"
        })
    status_done = wm.get_progress_status_block(current_step=6)
    assert "CRITICAL DIRECTIVE: Target of 10 positions achieved!" in status_done


def test_prune_conversation_history():
    wm = WorkingMemory()

    long_output_1 = "Candidate listings raw data:\n" + ("x" * 500)
    long_output_2 = "Another big page payload:\n" + ("y" * 600)
    short_output = "Page title: Job not found."
    recent_long_1 = "Recent tool payload 1:\n" + ("z" * 400)
    recent_long_2 = "Recent tool payload 2:\n" + ("w" * 400)

    messages = [
        {"role": "system", "content": "You are an autonomous research agent."},
        {"role": "user", "content": "Find 10 AI/ML jobs."},
        {"role": "assistant", "content": "Let me search aidevboard."},
        {"role": "tool", "content": long_output_1, "name": "search_aidevboard"},
        {"role": "assistant", "content": "Now fetching company X."},
        {"role": "tool", "content": short_output, "name": "fetch_article"},
        {"role": "assistant", "content": "Searching again."},
        {"role": "tool", "content": long_output_2, "name": "search_tavily"},
        {"role": "assistant", "content": "Checking recent link 1."},
        {"role": "tool", "content": recent_long_1, "name": "fetch_article"},
        {"role": "assistant", "content": "Checking recent link 2."},
        {"role": "tool", "content": recent_long_2, "name": "fetch_article"},
    ]

    pruned = wm.prune_conversation_history(messages, keep_recent_tools=2)
    assert len(pruned) == len(messages)
    # System and user prompts unmodified
    assert pruned[0]["content"] == "You are an autonomous research agent."
    assert pruned[1]["content"] == "Find 10 AI/ML jobs."

    # First tool message (long_output_1) should be pruned because it's older than the last 2 tools
    assert "[Observation: Output archived in WorkingMemory" in pruned[3]["content"]
    assert len(pruned[3]["content"]) < 150

    # Second tool message (short_output) was < 300 chars, so it remains unchanged
    assert pruned[5]["content"] == short_output

    # Third tool message (long_output_2) should also be pruned
    assert "[Observation: Output archived in WorkingMemory" in pruned[7]["content"]

    # Last two tool messages must be kept intact in full detail
    assert pruned[9]["content"] == recent_long_1
    assert pruned[11]["content"] == recent_long_2
