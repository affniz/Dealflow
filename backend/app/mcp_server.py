"""Dealflow as an MCP server, so Claude (Claude Code, Claude Desktop, any MCP client) can work
with the CRM directly.

It serves the Copilot's own tools at /mcp (Streamable HTTP), as the person whose personal
access token is in the Authorization header. That means the same rules hold everywhere:
- Read tools see only what that person can see (agents: their own records).
- Change tools never change anything. They create a proposal that the person approves or
  rejects in Dealflow's Agent inbox, exactly like the Copilot's and the pipeline agent's.
- Viewers can read but not propose.
"""

import inspect
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Annotated, Any, get_args

import anyio.to_thread
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from pydantic import Field
from sqlmodel import Session
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from app.agent.tools import TOOLS, Tool, ToolContext, ToolError
from app.core.db import get_session
from app.services.api_tokens import bearer, user_for_token

SOURCE = "mcp"  # AgentProposal.source for proposals made through MCP

INSTRUCTIONS = """\
Dealflow is a sales CRM: companies, contacts, deals moving through pipeline stages, and \
activities (notes, calls, meetings, emails, tasks). Money is in the deal's currency, usually \
INR; write Indian amounts in lakh and crore when that's clearer.

You act as the person whose token connected you, with their access: an agent sees only their \
own records. Call pipeline_overview for stage and lost-reason ids. The propose_* tools don't \
change anything: each creates a suggestion that the person approves or rejects in Dealflow's \
Agent inbox, so say that's where to find it. Look a deal up with get_deal before proposing a \
change to it."""

server = MCPServer(name="Dealflow", title="Dealflow CRM", instructions=INSTRUCTIONS)


@contextmanager
def _session() -> Iterator[Session]:
    # Use FastAPI's override of get_session when there is one, so tests share their session.
    from app.main import app

    provider = app.dependency_overrides.get(get_session, get_session)
    made = provider()
    if not inspect.isgenerator(made):
        yield made
        return
    try:
        yield next(made)
    finally:
        made.close()


def _call(tool: Tool, ctx: Context, args: dict[str, Any]) -> str:
    token = bearer((ctx.headers or {}).get("authorization"))
    with _session() as session:
        user = user_for_token(session, token)
        if user is None:  # revoked since the request was let in
            raise MCPToolError("This access token is no longer valid")
        inp = tool.input_model.model_validate(args)
        try:
            result = tool.run(ToolContext(session=session, user=user, source=SOURCE), inp)
        except ToolError as e:
            session.rollback()
            raise MCPToolError(str(e)) from None
        session.commit()  # keeps a proposal the tool created
    return json.dumps(result, default=str, ensure_ascii=False)


def _register(tool: Tool) -> None:
    """Expose one Copilot tool. Its arguments are its input model's fields, at the top level."""
    params = []
    for name, field in tool.input_model.model_fields.items():
        annotation: Any = field.annotation
        if field.description:
            annotation = Annotated[annotation, Field(description=field.description)]
        default = inspect.Parameter.empty if field.is_required() else field.default
        if default is inspect.Parameter.empty and type(None) in get_args(field.annotation):
            default = (
                None  # the Copilot's strict schema needs every key; here, null can be left out
            )
        params.append(
            inspect.Parameter(
                name, inspect.Parameter.KEYWORD_ONLY, annotation=annotation, default=default
            )
        )
    params.append(inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context))

    def call(ctx: Context, **args: Any) -> str:
        return _call(tool, ctx, args)

    call.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    call.__annotations__ = {"ctx": Context, "return": str}
    call.__name__ = tool.name
    server.add_tool(
        call,
        name=tool.name,
        title=tool.name.replace("_", " ").capitalize(),
        description=tool.description,
        annotations=ToolAnnotations(
            # proposals don't change records, but they do add something for a person to review
            readOnlyHint=not tool.proposes_change,
            destructiveHint=False,
            idempotentHint=not tool.proposes_change,
            openWorldHint=False,
        ),
        structured_output=False,
    )


for _tool in TOOLS:
    _register(_tool)


@asynccontextmanager
async def running() -> AsyncIterator[None]:
    """Run the MCP transport for the API's lifetime (the API's lifespan enters this)."""
    # Stateless, with plain JSON responses: no server-side sessions to keep, so it works behind
    # several API workers. Requests need a token, so DNS-rebinding protection (meant for
    # unauthenticated local servers) isn't needed, and it would reject a deployed host name.
    # A session manager runs only once, so each start builds a fresh one (tests start many).
    server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    async with server.session_manager.run():
        yield


def _token_is_valid(scope: Scope) -> bool:
    headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
    with _session() as session:
        return user_for_token(session, bearer(headers.get("authorization"))) is not None


class _Authenticated:
    """Refuse requests without a valid personal access token before they reach MCP."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not await anyio.to_thread.run_sync(_token_is_valid, scope):
            response = JSONResponse(
                {
                    "detail": "Send a Dealflow personal access token as 'Authorization: Bearer "
                    "dfp_…'. Create one in Dealflow under Your account."
                },
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            return await response(scope, receive, send)
        await server.session_manager.handle_request(scope, receive, send)


# Starlette treats a class instance as a plain ASGI app (not a request -> response function)
route = Route("/mcp", endpoint=_Authenticated(), methods=["GET", "POST", "DELETE"])
