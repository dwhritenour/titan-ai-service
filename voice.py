"""
voice.py — Titan AI voice features (ElevenLabs).   voice-1.0.0

Two queue-driven jobs, both riding dbo.tai_chat_messages exactly like
user questions do (the Anvil app never calls ElevenLabs — keys stay in
this service's .env):

  TTS  (role='voice_req', content = message_id to speak)
       The target answer is rewritten as a short SPOKEN summary by the
       model (markdown tables read terribly aloud), synthesized via
       ElevenLabs text-to-speech, stored in tai_chat_files as mp3, and
       announced with a role='voice' row (file_id set, content = the
       target message_id). The Anvil client plays it.

  STT  (role='stt_req', file_id = audio blob in tai_chat_files)
       The recording is transcribed via ElevenLabs speech-to-text
       (Scribe) and returned as a role='stt' row whose content is the
       transcript. The client drops it into the question box for the
       user to confirm — transcripts are never auto-submitted.

Config (.env):
  ELEVENLABS_API_KEY     required for voice (jobs fail politely without)
  ELEVENLABS_VOICE_ID    default JBFqnCBsd6RMkjVDRZzb ("George")
  ELEVENLABS_TTS_MODEL   default eleven_multilingual_v2
  ELEVENLABS_STT_MODEL   default scribe_v2
  VOICE_SUMMARY_MODEL    default = chat MODEL (set a cheaper model to
                         cut the per-tap summary cost)
"""
import json
import logging
import os
import re
import time

import requests
from anthropic import Anthropic

import config

log = logging.getLogger("voice")

API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
TTS_MODEL = os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")
STT_MODEL = os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v2")
SUMMARY_MODEL = os.environ.get("VOICE_SUMMARY_MODEL", config.MODEL)

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{vid}?output_format=mp3_44100_128"
STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"

_summary_client = None

SUMMARY_PROMPT = """Rewrite the following Titan AI answer as a SHORT \
spoken version — what a helpful colleague would say out loud. Rules: \
1 to 4 plain sentences; no markdown, tables, bullet lists or headers; \
read the key numbers naturally ("three hundred thirty-four in stock"); \
keep SKU codes letter-by-letter as written (say "Y S sixty-one C oh \
four hundred" style is NOT needed — just keep the code as text); if \
the answer is a table, speak only the most decision-relevant lines \
and say the full table is on screen. Reply with the spoken text only.

ANSWER:
{answer}"""


def _spoken_text(answer):
    """Markdown answer -> short speakable text."""
    plain = answer.strip()
    # Short, table-free answers can be spoken nearly as-is.
    if len(plain) < 350 and "|" not in plain and "```" not in plain:
        txt = re.sub(r"[*_#`]+", "", plain)
        return re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", txt)
    global _summary_client
    if _summary_client is None:
        _summary_client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = _summary_client.messages.create(
        model=SUMMARY_MODEL,
        max_tokens=300,
        messages=[{"role": "user",
                   "content": SUMMARY_PROMPT.format(answer=answer[:6000])}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _synthesize(text):
    """Text -> mp3 bytes via ElevenLabs."""
    r = requests.post(
        TTS_URL.format(vid=VOICE_ID),
        headers={"xi-api-key": API_KEY, "Content-Type": "application/json"},
        json={"text": text, "model_id": TTS_MODEL},
        timeout=60,
    )
    r.raise_for_status()
    return r.content


def _transcribe(audio_bytes, content_type):
    """Audio bytes -> transcript text via ElevenLabs Scribe."""
    r = requests.post(
        STT_URL,
        headers={"xi-api-key": API_KEY},
        data={"model_id": STT_MODEL},
        files={"file": ("question" + _ext(content_type), audio_bytes,
                        content_type or "application/octet-stream")},
        timeout=120,
    )
    r.raise_for_status()
    return (r.json().get("text") or "").strip()


def _ext(content_type):
    ct = (content_type or "").lower()
    for key, ext in (("webm", ".webm"), ("mp4", ".mp4"), ("mpeg", ".mp3"),
                     ("ogg", ".ogg"), ("wav", ".wav")):
        if key in ct:
            return ext
    return ".webm"


def process_job(db, job):
    """Handle one claimed voice job (role voice_req or stt_req)."""
    role = job["role"]
    session_id = job["session_id"]
    started = time.monotonic()
    if not API_KEY:
        db.mark_user_message(job["message_id"], "error")
        db.insert_error(session_id,
                        "Voice isn't configured on the server yet "
                        "(missing ElevenLabs key) — tell Dave.")
        return
    try:
        if role == "voice_req":
            target_id = int(job["content"])
            answer = db.get_message_content(target_id)
            if not answer:
                raise ValueError(f"message {target_id} not found")
            spoken = _spoken_text(answer)
            mp3 = _synthesize(spoken)
            file_id = db.insert_media_file(
                session_id, f"titan-answer-{target_id}.mp3",
                mp3, "audio/mpeg")
            db.insert_voice_row(session_id, "voice", str(target_id), file_id)
            log.info("TTS for message %s: %s chars spoken, %s bytes mp3, "
                     "%.1fs", target_id, len(spoken), len(mp3),
                     time.monotonic() - started)
        elif role == "stt_req":
            blob, ct = db.get_file_bytes(job["file_id"])
            text = _transcribe(blob, ct)
            if not text:
                raise ValueError("empty transcript")
            db.insert_voice_row(session_id, "stt", text[:2000], None)
            log.info("STT for session %s: %s chars, %.1fs",
                     session_id, len(text), time.monotonic() - started)
        db.mark_user_message(job["message_id"], "done")
    except Exception:
        log.exception("voice job %s failed", job["message_id"])
        db.mark_user_message(job["message_id"], "error")
        kind = "read that answer aloud" if role == "voice_req" \
            else "transcribe that recording"
        db.insert_error(session_id,
                        f"Sorry — couldn't {kind}. Please try again.")
