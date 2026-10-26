"""
agent.py — the Claude agent loop for one user question.

Given a claimed user message, this module:
  1. builds the conversation (system prompt + prior turns + question)
  2. lets Claude call allowlisted nexus-mcp-server tools in a loop
  3. returns the final answer text, a tool trace (for the
     "how I got this" expander in the app), and usage numbers.

The system prompt and the tool schemas carry cache_control markers so
Anthropic prompt caching keeps the per-question cost low.
"""

import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from anthropic import Anthropic

import config
import db
import excel_export
import howto_docs
import online_inventory
import rep_locator
import corrosion_charts
import site_crawler
import spec_sheets

_EASTERN = ZoneInfo("America/New_York")

_client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

with open(config.SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as _f:
    _SYSTEM_PROMPT = _f.read()


def _system_blocks(username):
    now = datetime.now(_EASTERN)
    dynamic = (
        f"\n\n## Right now\n"
        f"Current date/time (Eastern): {now.strftime('%A, %B %d, %Y %I:%M %p')}\n"
        f"You are talking to: {username}"
    )
    return [
        {
            "type": "text",
            "text": _SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": dynamic},
    ]


async def answer(nexus, session_id, user_message_id, question):
    """Run the agent loop. Returns dict with answer/trace/usage."""
    started = time.monotonic()
    username = db.get_session_username(session_id)

    history = db.load_history(session_id, user_message_id)
    messages = [
        {"role": r["role"], "content": r["content"]} for r in history
    ]
    messages.append({"role": "user", "content": question})

    tools = nexus.tools_for_anthropic()

    # Native spec-sheet tools (v1.2) ride alongside the MCP tools.
    spec_lib = spec_sheets.get_library(
        config.SPEC_SHEETS_DIR, config.SPEC_CACHE_PATH)
    if spec_lib.sheets:
        tools = tools + spec_sheets.spec_tools_for_anthropic()

    howto_lib = howto_docs.get_library(config.HOWTO_DOCS_DIR)
    if howto_lib.guides:
        tools = tools + howto_docs.howto_tools_for_anthropic()

    # Website tools are ALWAYS registered (the system prompt promises
    # them). If the index is empty — first crawl still running, or the
    # site was unreachable — the tool itself says so, which is far less
    # confusing to the model than a prompt/tool mismatch.
    web_lib = site_crawler.get_library(config)
    tools = tools + site_crawler.website_tools_for_anthropic()

    # Online inventory (v1.4) — live dealer-site CSVs; always registered
    # (same lesson as the website tools: prompt/tool mismatch confuses
    # the model far more than a tool that reports its own failure).
    inv_lib = online_inventory.get_library(config)
    tools = tools + online_inventory.inventory_tools_for_anthropic()

    # Rep locator (v1.5) — public wpDataTables endpoint; always registered.
    rep_lib = rep_locator.get_library(config)
    tools = tools + rep_locator.rep_tools_for_anthropic()

    tools = tools + excel_export.export_tools_for_anthropic()

    # Corrosion chart-row images — always registered; the tool reports
    # cleanly when the crop library has not been generated yet.
    tools = tools + corrosion_charts.chart_tools_for_anthropic()

    if tools:
        # Cache marker on the last tool caches the whole tools block.
        tools[-1] = dict(tools[-1])
        tools[-1]["cache_control"] = {"type": "ephemeral"}

    trace = []
    total_in = 0
    total_out = 0

    for _iteration in range(config.MAX_TOOL_ITERATIONS + 1):
        response = _client.messages.create(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=_system_blocks(username),
            tools=tools,
            messages=messages,
        )
        usage = getattr(response, "usage", None)
        if usage is not None:
            total_in += getattr(usage, "input_tokens", 0) or 0
            total_out += getattr(usage, "output_tokens", 0) or 0

        if response.stop_reason != "tool_use":
            text = "".join(
                b.text for b in response.content if b.type == "text"
            )
            # The output cap can cut an answer off mid-table. Ask the model
            # to continue (this model family rejects assistant prefill, so
            # a plain continuation turn) and stitch the pieces together.
            cont_rounds = 0
            # 2026-10-14: when the cap lands INSIDE a tool call there is no
            # text and the partial tool_use is dropped - the content is
            # empty. Sending an empty assistant turn back is a 400 (that
            # was the "something went wrong" on every sales-order question
            # the day the view section shipped). Nothing to continue from:
            # tell the user plainly instead of crashing.
            if response.stop_reason == "max_tokens" and not response.content:
                return {
                    "answer": ("I ran out of output room while composing a "
                               "database query for that - the question "
                               "probably needs a simpler query. Try asking "
                               "for one thing at a time (for example "
                               "'which customers had the most rush orders "
                               "since September 24?')."),
                    "trace": trace,
                    "input_tokens": total_in,
                    "output_tokens": total_out,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
            while (response.stop_reason == "max_tokens" and cont_rounds < 2
                   and response.content):
                cont_rounds += 1
                messages.append(
                    {"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": (
                    "Your previous message was cut off by the output limit. "
                    "Continue EXACTLY from where it stopped — do not repeat "
                    "anything already written, do not apologize, just "
                    "continue the text.")})
                response = _client.messages.create(
                    model=config.MODEL,
                    max_tokens=config.MAX_TOKENS,
                    system=_system_blocks(username),
                    tools=tools,
                    messages=messages,
                )
                usage = getattr(response, "usage", None)
                if usage is not None:
                    total_in += getattr(usage, "input_tokens", 0) or 0
                    total_out += getattr(usage, "output_tokens", 0) or 0
                text += "".join(
                    b.text for b in response.content if b.type == "text")
            text = text.strip()
            return {
                "answer": text or "(no answer produced)",
                "trace": trace,
                "input_tokens": total_in,
                "output_tokens": total_out,
                "latency_ms": int((time.monotonic() - started) * 1000),
            }

        # Claude asked for tools: run them, feed results back.
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            status_text = config.TOOL_STATUS_TEXT.get(
                block.name, f"Running {block.name}…"
            )
            db.insert_status(session_id, status_text)

            try:
                if block.name in spec_sheets.SPEC_TOOL_NAMES:
                    result_text = spec_lib.call(block.name, block.input)
                elif block.name in howto_docs.HOWTO_TOOL_NAMES:
                    result_text = howto_lib.call(block.name, block.input)
                elif block.name in site_crawler.WEBSITE_TOOL_NAMES:
                    result_text = web_lib.call(block.name, block.input)
                elif block.name in online_inventory.INVENTORY_TOOL_NAMES:
                    result_text = inv_lib.call(block.name, block.input)
                elif block.name in rep_locator.REP_TOOL_NAMES:
                    result_text = rep_lib.call(block.name, block.input)
                elif block.name in excel_export.EXPORT_TOOL_NAMES:
                    result_text = excel_export.handle(db, session_id, block.input)
                elif block.name in corrosion_charts.CHART_TOOL_NAMES:
                    result_text = corrosion_charts.handle(db, session_id, block.input)
                else:
                    result_text = await nexus.call(block.name, block.input)
            except Exception as exc:  # tool failure -> tell the model
                result_text = json.dumps({"error": str(exc)})

            trace.append(
                {
                    "tool": block.name,
                    "input": block.input,
                    "result_preview": result_text[
                        : config.TRACE_RESULT_PREVIEW_CHARS
                    ],
                }
            )
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                }
            )
        messages.append({"role": "user", "content": results})

    # Iteration cap reached — ask for a best-effort wrap-up, no tools.
    messages.append(
        {
            "role": "user",
            "content": (
                "You have reached the tool-call limit for this question. "
                "Answer now with what you have, and say clearly what you "
                "could not verify."
            ),
        }
    )
    response = _client.messages.create(
        model=config.MODEL,
        max_tokens=config.MAX_TOKENS,
        system=_system_blocks(username),
        messages=messages,
    )
    usage = getattr(response, "usage", None)
    if usage is not None:
        total_in += getattr(usage, "input_tokens", 0) or 0
        total_out += getattr(usage, "output_tokens", 0) or 0
    text = "".join(
        b.text for b in response.content if b.type == "text"
    ).strip()
    return {
        "answer": text or "(no answer produced)",
        "trace": trace,
        "input_tokens": total_in,
        "output_tokens": total_out,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
