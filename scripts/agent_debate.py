#!/usr/bin/env python3
"""
Two-agent debate runner for GitHub Actions.

- Agent A: Developer / Product Builder
- Agent B: Investor / Business Critic

State model:
  The GitHub Issue thread IS the state. Each run fetches existing comments
  posted by this bot, condenses them into a short running summary, and
  appends the next turn(s). This means the debate can be resumed across
  many separate workflow runs (important for the full 40-60 exchange /
  10-hour version, since a single GH Actions job cannot run that long).

Cost controls:
  --rounds caps total turns (1 round = 1 turn each = 2 API calls)
  --max-tokens caps output size per turn
  --model lets you use a cheap model for testing, a stronger one for the real run
  --test-mode limits repo context to README + top-level file tree only
"""

import argparse
import os
import sys
import json
import requests

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

AGENT_A_SYSTEM = """You are Agent A: Developer / Product Builder, reviewing a \
partially built Property Management System (PMS) for Bali villas.
Audit the codebase, say what's built/incomplete/poorly structured, and propose \
practical, incremental improvements. Cite specific repository files when you \
reference the existing system. Be concise. This is a TEST RUN with limited \
context (README + file tree only) -- do not invent file contents you can't see."""

AGENT_B_SYSTEM = """You are Agent B: Investor / Business Critic, reviewing a \
partially built Property Management System (PMS) for Bali villas.
Challenge Agent A's assumptions on business/market grounds: demand, competition, \
pricing, defensibility. Be direct and concise. This is a TEST RUN -- keep it short."""


def get_repo_snapshot(test_mode: bool) -> str:
    """Small, cheap slice of repo context for the test run."""
    parts = []
    for readme_name in ("README.md", "readme.md", "README"):
        if os.path.exists(readme_name):
            with open(readme_name, "r", errors="ignore") as f:
                parts.append(f"README (truncated):\n{f.read()[:1500]}")
            break

    tree_lines = []
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
        depth = root.count(os.sep)
        if depth > 2:
            continue
        for fn in files:
            tree_lines.append(os.path.join(root, fn))
        if test_mode and len(tree_lines) > 60:
            break
    parts.append("Top-level file tree (truncated):\n" + "\n".join(tree_lines[:60]))
    return "\n\n".join(parts)


def call_claude(system: str, user_content: str, model: str, max_tokens: int) -> str:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user_content}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def get_existing_comments(repo: str, issue_number: str, token: str) -> list:
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    r = requests.get(url, headers={"Authorization": f"Bearer {token}",
                                    "Accept": "application/vnd.github+json"}, timeout=30)
    r.raise_for_status()
    return r.json()


def post_comment(repo: str, issue_number: str, token: str, body: str):
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    r = requests.post(url, headers={"Authorization": f"Bearer {token}",
                                     "Accept": "application/vnd.github+json"},
                       json={"body": body}, timeout=30)
    r.raise_for_status()


def build_running_summary(comments: list, max_chars: int = 2000) -> str:
    """Condense prior turns into a short summary block instead of feeding full history."""
    if not comments:
        return "(No prior discussion yet -- this is the opening round.)"
    tail = comments[-4:]  # last few turns is enough context for the next reply
    joined = "\n\n".join(f"[{c['user']['login']}]: {c['body'][:500]}" for c in tail)
    return joined[-max_chars:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--test-mode", action="store_true")
    args = ap.parse_args()

    repo = os.environ["GITHUB_REPOSITORY"]
    issue_number = os.environ["ISSUE_NUMBER"]
    token = os.environ["GITHUB_TOKEN"]

    snapshot = get_repo_snapshot(args.test_mode)

    for round_i in range(1, args.rounds + 1):
        existing = get_existing_comments(repo, issue_number, token)
        summary = build_running_summary(existing)

        # Agent A turn
        a_prompt = (
            f"ROUND {round_i} -- your turn (Agent A).\n\n"
            f"Repo snapshot:\n{snapshot}\n\n"
            f"Discussion so far:\n{summary}\n\n"
            f"Give your next point. Keep it under 150 words for this test."
        )
        a_reply = call_claude(AGENT_A_SYSTEM, a_prompt, args.model, args.max_tokens)
        post_comment(repo, issue_number, token, f"**Agent A (Developer) -- Round {round_i}**\n\n{a_reply}")

        # Agent B turn (sees A's just-posted reply)
        existing = get_existing_comments(repo, issue_number, token)
        summary = build_running_summary(existing)
        b_prompt = (
            f"ROUND {round_i} -- your turn (Agent B).\n\n"
            f"Repo snapshot:\n{snapshot}\n\n"
            f"Discussion so far:\n{summary}\n\n"
            f"Challenge or respond to Agent A. Keep it under 150 words for this test."
        )
        b_reply = call_claude(AGENT_B_SYSTEM, b_prompt, args.model, args.max_tokens)
        post_comment(repo, issue_number, token, f"**Agent B (Investor) -- Round {round_i}**\n\n{b_reply}")

        print(f"Round {round_i} complete: 2 API calls, 2 comments posted.")

    print("Test debate finished.")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"HTTP error: {e} -- {e.response.text if e.response is not None else ''}", file=sys.stderr)
        sys.exit(1)
