"""The tool-use loop shared by every Dealflow agent (Copilot, pipeline agent).

It asks Claude, runs the tools it requests (reads straight away, changes as proposals), sends
the results back, and repeats until Claude answers or the step limit is reached. `messages` is
only ever appended to, and is returned exactly as sent to the API.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session

from app.agent.tools import TOOL_SPECS, TOOLS_BY_NAME, ToolContext, ToolError
from app.core.config import settings
from app.models import User

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
REFUSAL_REPLY = "Sorry, I can't help with that one."


class MessagesClient(Protocol):
    """The slice of `anthropic.Anthropic` used here, so tests can pass a fake."""

    beta: Any


@dataclass
class LoopResult:
    messages: list[dict[str, Any]]
    input_tokens: int = 0
    output_tokens: int = 0
    hit_step_limit: bool = False
    refused: bool = False
    final_text: str = ""
    proposal_ids: list[int] = field(default_factory=list)


def run_tool(ctx: ToolContext, name: str, raw_input: Any) -> tuple[str, bool]:
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return f"Unknown tool {name}", True
    try:
        inp = tool.input_model.model_validate(raw_input)
        result = tool.run(ctx, inp)
        return json.dumps(result, default=str, ensure_ascii=False), False
    except ValidationError as exc:
        return f"Invalid input: {exc.errors(include_url=False)}", True
    except ToolError as exc:
        return str(exc), True
    except HTTPException as exc:
        return str(exc.detail), True
    except Exception:  # never let one bad tool call take down the whole run
        log.exception("Agent tool %s failed", name)
        ctx.session.rollback()
        return "The tool failed unexpectedly; say you couldn't do this.", True


def run_loop(
    session: Session,
    client: MessagesClient,
    *,
    user: User,
    system: str,
    messages: list[dict[str, Any]],
    source: str,
    max_steps: int,
    step_limit_reply: str,
    conversation_id: int | None = None,
    run_id: int | None = None,
    max_proposals: int | None = None,
) -> LoopResult:
    messages = list(messages)
    result = LoopResult(messages=messages)

    for step in range(max_steps):
        response = client.beta.messages.create(
            model=settings.AGENT_MODEL,
            max_tokens=16000,
            system=system,
            tools=TOOL_SPECS,
            messages=messages,
            output_config={"effort": settings.AGENT_EFFORT},
            cache_control={"type": "ephemeral"},
            # if a safety classifier declines, the API retries on a fallback model
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        usage = response.usage
        result.input_tokens += (
            usage.input_tokens
            + (usage.cache_read_input_tokens or 0)
            + (usage.cache_creation_input_tokens or 0)
        )
        result.output_tokens += usage.output_tokens
        # append the content exactly as returned (thinking blocks included)
        messages.append({"role": "assistant", "content": response.to_dict()["content"]})
        texts = [b.text for b in response.content if b.type == "text" and b.text.strip()]
        if texts:
            result.final_text = "\n\n".join(texts)

        if response.stop_reason == "pause_turn":
            continue
        if response.stop_reason == "refusal":
            messages.append({"role": "assistant", "content": REFUSAL_REPLY})
            result.refused = True
            result.final_text = REFUSAL_REPLY
            break
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            break  # end_turn, max_tokens or stop_sequence: the answer is in

        tool_results = []
        for block in tool_uses:
            ctx = ToolContext(
                session=session,
                user=user,
                source=source,
                conversation_id=conversation_id,
                run_id=run_id,
                tool_use_id=block.id,
                proposals_left=None
                if max_proposals is None
                else max_proposals - len(result.proposal_ids),
            )
            content, is_error = run_tool(ctx, block.name, block.input)
            if not is_error and block.name.startswith("propose_"):
                result.proposal_ids.append(json.loads(content)["proposal_id"])
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    **({"is_error": True} if is_error else {}),
                }
            )
        # every tool_use gets its result, so the history stays valid even if we stop here
        messages.append({"role": "user", "content": tool_results})
        if step == max_steps - 1:
            messages.append({"role": "assistant", "content": step_limit_reply})
            result.hit_step_limit = True
            result.final_text = step_limit_reply

    return result
