"""A scripted stand-in for the Claude Messages API, shared by the agent tests."""

import copy
from collections.abc import Callable
from typing import Any

from anthropic.types.beta import BetaMessage

Reply = Callable[[dict[str, Any]], dict[str, Any]] | dict[str, Any]


DEFAULT_USAGE = {"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 0}


def message(
    content: list[dict[str, Any]],
    stop_reason: str = "end_turn",
    usage: dict[str, Any] | None = None,
    model: str = "claude-opus-5-5",
) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "thinking", "thinking": "", "signature": "sig"}, *content],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage or DEFAULT_USAGE,
    }


def tool_call(name: str, inp: dict[str, Any], call_id: str = "toolu_1") -> dict[str, Any]:
    return message([{"type": "tool_use", "id": call_id, "name": name, "input": inp}], "tool_use")


def say(text: str) -> dict[str, Any]:
    return message([{"type": "text", "text": text}])


class FakeClaude:
    """Mimics `client.beta.messages.create`: returns scripted replies and records requests."""

    def __init__(self) -> None:
        self.script: list[Reply] = []
        self.requests: list[dict[str, Any]] = []
        self.beta = self
        self.messages = self

    def create(self, **kwargs: Any) -> BetaMessage:
        self.requests.append(copy.deepcopy(kwargs))
        reply = self.script.pop(0)
        if callable(reply):
            reply = reply(kwargs)
        return BetaMessage.model_validate(reply)

    def tool_results(self, request_index: int) -> list[dict[str, Any]]:
        last = self.requests[request_index]["messages"][-1]
        assert last["role"] == "user" and isinstance(last["content"], list)
        return last["content"]
