"""
worker.py — Titan AI agent service entry point.

Polls dbo.tai_chat_messages for pending user questions, runs each one
through the Claude agent loop (agent.py) with read-only Nexus tools
(mcp_client.py), and writes answers back. The Anvil app never talks to
this service directly — the database queue is the whole interface.

Run:            python worker.py
Stop (kill switch): Ctrl+C / stop the Windows service — the chat app
simply shows questions as waiting until it returns.
"""

import asyncio
import logging
import sys
import time

import config
import daily_plan_agent
import db
import ledger_agent
import nugget_agent
import howto_docs
import site_crawler
import spec_sheets
import voice
from agent import answer
from mcp_client import NexusMcp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("titan-ai")


async def process_one(nexus, msg):
    """Handle one claimed user message end to end."""
    message_id = msg["message_id"]
    session_id = msg["session_id"]
    question = msg["content"]
    log.info("Processing message %s (session %s)", message_id, session_id)

    try:
        result = await answer(nexus, session_id, message_id, question)
        db.insert_assistant(
            session_id,
            result["answer"],
            result["trace"],
            config.MODEL,
            result["input_tokens"],
            result["output_tokens"],
            result["latency_ms"],
        )
        db.mark_user_message(message_id, "done")
        log.info(
            "Answered message %s: %s tool call(s), %s in / %s out tokens, %s ms",
            message_id,
            len(result["trace"]),
            result["input_tokens"],
            result["output_tokens"],
            result["latency_ms"],
        )
    except Exception:
        log.exception("Failed processing message %s", message_id)
        db.mark_user_message(message_id, "error")
        db.insert_error(
            session_id,
            "Sorry — something went wrong answering that. "
            "Please try again; if it keeps failing, tell Dave.",
        )


async def run():
    # Hardened 2026-08-07: a transient DB failure at boot must not kill
    # the service before the retry loop below even starts.
    try:
        requeued = db.recover_stuck_messages()
        if requeued:
            log.info("Requeued %s message(s) left processing by a previous run",
                     requeued)
    except Exception:
        log.exception("Startup requeue failed (transient DB issue?) — "
                      "continuing; stuck messages recover on next restart")

    log.info(
        "Titan AI service starting (model=%s, poll=%ss)",
        config.MODEL,
        config.POLL_SECONDS,
    )

    # Spec-sheet library (v1.2): extract new/changed PDFs at startup.
    try:
        n_specs = spec_sheets.get_library(
            config.SPEC_SHEETS_DIR, config.SPEC_CACHE_PATH).refresh()
        log.info("Spec sheets loaded: %s from %s", n_specs, config.SPEC_SHEETS_DIR)
    except Exception:
        log.exception("Spec-sheet load failed — continuing without spec tools")

    # How-to guides (v1.1): small markdown corpus, loads in milliseconds.
    try:
        n_guides = howto_docs.get_library(config.HOWTO_DOCS_DIR).refresh()
        log.info("How-to guides loaded: %s from %s", n_guides, config.HOWTO_DOCS_DIR)
    except Exception:
        log.exception("How-to load failed — continuing without howto tools")

    # Website index (v1.3): serve the cache immediately; if stale, a
    # background crawl refreshes it without blocking the queue.
    try:
        web = site_crawler.get_library(config)
        log.info("Website index: %s cached pages (stale: %s)",
                 len(web.pages), web.is_stale())
        if web.refresh_in_background():
            log.info("Website re-crawl started in background")
    except Exception:
        log.exception("Website index init failed — continuing without web tools")

    while True:
        try:
            async with NexusMcp() as nexus:
                n_tools = len(nexus.tools_for_anthropic())
                log.info("nexus-mcp-server up — %s read-only tools", n_tools)
                idle_logged = time.monotonic()
                while True:
                    # Daily Plan agent (v1.6): once per weekday at
                    # AGENT_RUN_TIME it launches the proposal run on
                    # its own thread. Cheap on every other pass.
                    try:
                        daily_plan_agent.tick()
                    except Exception:
                        log.exception("daily_plan_agent.tick failed")
                    # Capacity ledger (ledger-1.0.0): once per weekday at
                    # LEDGER_RUN_TIME, on its own thread. Cheap otherwise.
                    try:
                        ledger_agent.tick()
                    except Exception:
                        log.exception("ledger_agent.tick failed")
                    # Teaching nuggets (nugget-1.0.0): the Friday digest at
                    # NUGGET_DIGEST_TIME; the daily lesson rides the
                    # morning run. Cheap otherwise.
                    try:
                        nugget_agent.tick()
                    except Exception:
                        log.exception("nugget_agent.tick failed")
                    # Voice jobs (voice-1.0.0): seconds each, so they
                    # run before questions for a snappy tap-to-play.
                    try:
                        vjob = db.claim_pending_voice_job()
                        while vjob is not None:
                            voice.process_job(db, vjob)
                            vjob = db.claim_pending_voice_job()
                    except Exception:
                        log.exception("voice job loop failed")
                    msg = db.claim_pending_message()
                    if msg is None:
                        if time.monotonic() - idle_logged > 3600:
                            log.info("Heartbeat: idle, healthy")
                            idle_logged = time.monotonic()
                        await asyncio.sleep(config.POLL_SECONDS)
                        continue
                    await process_one(nexus, msg)
        except KeyboardInterrupt:
            log.info("Shutting down (keyboard interrupt)")
            return
        except Exception:
            # MCP subprocess died, DB blip, etc. — log, wait, rebuild.
            log.exception("Service loop error; restarting in 10s")
            await asyncio.sleep(10)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
