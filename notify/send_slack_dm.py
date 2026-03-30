#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Send a Slack DM to the user who triggered a benchmark run."""
from __future__ import annotations

import json
import os
import urllib.request


def slack_api(token: str, method: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main() -> None:
    token = os.environ["SLACK_BOT_TOKEN"]
    user_map = json.loads(os.environ["GITHUB_SLACK_USER_MAP"])
    github_user = os.environ["GITHUB_USER"]

    slack_user_id = user_map.get(github_user)
    if not slack_user_id:
        print(f"No Slack mapping for '{github_user}', skipping DM")
        return

    dm = slack_api(token, "conversations.open", {"users": slack_user_id})
    if not dm.get("ok"):
        print(f"Failed to open DM: {dm.get('error')}")
        return

    channel = dm["channel"]["id"]
    emoji = os.environ.get("EMOJI", "")
    status = os.environ.get("STATUS", "")
    repo = os.environ.get("REPO_NAME", "")
    pr_url = os.environ.get("PR_URL", "")
    pr_number = os.environ.get("PR_NUMBER", "")
    run_url = os.environ.get("RUN_URL", "")

    text = (
        f"{emoji} *Benchmark {status}*\n"
        f"*Repo:* {repo}\n"
        f"*PR:* <{pr_url}|#{pr_number}>\n"
        f"*Run:* <{run_url}|View results>"
    )
    result = slack_api(token, "chat.postMessage", {
        "channel": channel,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
        "text": f"Benchmark {status}",
    })

    if result.get("ok"):
        print(f"Slack DM sent to {slack_user_id}")
    else:
        print(f"Slack DM failed: {result.get('error')}")


if __name__ == "__main__":
    main()
