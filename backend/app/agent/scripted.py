"""A scripted stand-in for Claude, so the end-to-end tests can drive the Copilot without an API key.

Turned on by AI_SCRIPTED (see scripts/e2e_server.sh), and refused in production. It plays
Claude's side of the tool loop: it reads the conversation, calls the real tools, and answers from
what they return, so the tests exercise the real tools, permissions, proposals and chat, with
only the model's judgement replaced. It understands:

- "which deals are stalled": searches for stalled deals and lists them;
- "move <deal> to <stage>": finds the deal, looks up the stage, and proposes the move;
- anything with "fail" in it: Claude can't be reached, as when the API is down;
- anything else: a reply saying what it understands.
"""

import json
import re
import uuid
from typing import Any

import anthropic
import httpx2
from anthropic.types.beta import BetaMessage

HELP = (
    "This is Dealflow's scripted stand-in for Claude, used in the end-to-end tests. Ask which "
    "deals are stalled, or to move a deal to a stage."
)
MOVE = re.compile(r"\bmove (?P<deal>.+?) to (?P<stage>[^.?!]+?)[.?!]*$", re.IGNORECASE)


class ScriptedClaude:
    """Answers `client.beta.messages.create` like Claude would, from a fixed script."""

    def __init__(self) -> None:
        self.beta = self
        self.messages = self

    def create(self, *, model: str, messages: list[dict[str, Any]], **_: Any) -> BetaMessage:
        asked, steps = _turn_so_far(messages)
        if "fail" in asked.lower():
            raise anthropic.APIConnectionError(
                request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            )
        if move := MOVE.search(asked.strip()):
            content = _move(move["deal"].strip(), move["stage"].strip(), steps)
        elif "stalled" in asked.lower():
            content = _stalled(steps)
        else:
            content = _text(HELP)
        return _message(model, content)


Step = tuple[str, dict[str, Any], Any, bool]  # tool name, input, result, whether it failed


def _turn_so_far(messages: list[dict[str, Any]]) -> tuple[str, list[Step]]:
    """The user's latest message, and the tool calls made since, with their results."""
    start = max(
        i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m["content"], str)
    )
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    steps: list[Step] = []
    for m in messages[start + 1 :]:
        if not isinstance(m["content"], list):
            continue
        for block in m["content"]:
            if block.get("type") == "tool_use":
                calls[block["id"]] = (block["name"], block["input"])
            elif block.get("type") == "tool_result":
                name, inp = calls[block["tool_use_id"]]
                failed = bool(block.get("is_error"))
                result = block["content"] if failed else json.loads(block["content"])
                steps.append((name, inp, result, failed))
    return messages[start]["content"], steps


def _stalled(steps: list[Step]) -> list[dict[str, Any]]:
    if not steps:
        return _call(
            "search_deals",
            {
                "query": None,
                "status": "open",
                "stalled_only": True,
                "mine_only": False,
                "limit": 20,
            },
        )
    deals = steps[0][2]["deals"]
    if not deals:
        return _text("None of the open deals you can see are stalled.")
    lines = [f"- **{d['title']}**: {d['stage']}, {d['days_in_stage']} days" for d in deals]
    return _text("These deals are stalled:\n" + "\n".join(lines))


def _move(title: str, stage_name: str, steps: list[Step]) -> list[dict[str, Any]]:
    if not steps:
        search = {"status": "open", "stalled_only": False, "mine_only": False, "limit": 5}
        return _call("search_deals", {"query": title, **search})
    deals = steps[0][2]["deals"]
    if not deals:
        return _text(f"I couldn't find an open deal called “{title}” that you can see.")
    deal = deals[0]
    if len(steps) == 1:
        return _call("pipeline_overview", {})
    if len(steps) == 2:
        stages = [s for p in steps[1][2]["pipelines"] for s in p["stages"]]
        stage = next((s for s in stages if s["name"].lower() == stage_name.lower()), None)
        if stage is None:
            return _text(f"There's no stage called “{stage_name}”.")
        reason = f"You asked to move it to {stage['name']}."
        inp = {"deal_id": deal["id"], "stage_id": stage["stage_id"], "reason": reason}
        return _call("propose_move_stage", inp)
    _, _, result, failed = steps[2]
    if failed:
        return _text(f"I couldn't suggest that: {result}")
    return _text(
        f"I've suggested moving **{deal['title']}** to {stage_name}. "
        "Nothing changes until you approve it."
    )


def _call(name: str, inp: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"type": "tool_use", "id": "", "name": name, "input": inp}]


def _text(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": text}]


def _message(model: str, content: list[dict[str, Any]]) -> BetaMessage:
    calls = [b for b in content if b["type"] == "tool_use"]
    for block in calls:  # unique in the chat: proposals are matched to their cards by it
        block["id"] = f"toolu_scripted_{uuid.uuid4().hex}"
    return BetaMessage.model_validate(
        {
            "id": f"msg_scripted_{uuid.uuid4().hex}",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": "tool_use" if calls else "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 50},
        }
    )
