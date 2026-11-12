"""Export the development conversation (user messages and assistant replies) to Markdown.

    python tools/export_conversation.py TRANSCRIPT.jsonl OUT.md

Keeps what was said; leaves out tool calls, tool output, hidden reasoning and system notes. Lines that look like
secrets are redacted as a precaution.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DROP = re.compile(r"<(system-reminder|command-[a-z-]+|local-command-[a-z-]+|task-notification|ide_[a-z_]+)>.*?</\1>", re.S)
SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|pk-[A-Za-z0-9_-]{16,}|(?:PORTKEY|OPENAI)_API_KEY\s*=\s*\S+)")


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
    return ""


def main(src: str, out: str) -> None:
    turns, last = [], None
    for line in Path(src).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("type") not in ("user", "assistant") or r.get("isMeta"):
            continue
        content = (r.get("message") or {}).get("content")
        if r["type"] == "user" and isinstance(content, list) and any(x.get("type") == "tool_result" for x in content if isinstance(x, dict)):
            continue
        txt = DROP.sub("", text_of(content)).strip()
        if not txt:
            continue
        who = "Summary of earlier conversation (context carried forward)" if r.get("isCompactSummary") else \
            ("User" if r["type"] == "user" else "Claude")
        txt = SECRET.sub("[redacted]", txt)
        ts = (r.get("timestamp") or "")[:16].replace("T", " ")
        if who == last == "Claude" and turns:  # one reply split across several messages
            turns[-1] = turns[-1] + "\n\n" + txt
            continue
        turns.append(f"### {who} · {ts} UTC\n\n{txt}")
        last = who
    head = ("# Full development conversation: Credit/Financial Analysis Automation\n\n"
            "MGMT 409 final project. Ryan Scrivano with Claude (Claude Code). Every message exchanged during the build,\n"
            "in order. Tool calls, tool output and internal notes are omitted; summaries of earlier context are marked.\n"
            "A dated, condensed record of decisions is in `conversation_log.md`.\n\n---\n\n")
    Path(out).write_text(head + "\n\n---\n\n".join(turns) + "\n", encoding="utf-8")
    print(f"{len(turns)} messages -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
