"""
db.py — chat-table access for the Titan AI agent service.

Uses the titan_ai_svc login, which can touch ONLY the three
tai_chat_* tables. Connections are short-lived (open, do the work,
close) so an idle service holds nothing open overnight.
"""

import json

import pymssql

import config


def _connect():
    return pymssql.connect(
        server=config.NEXUS_SERVER,
        user=config.SVC_USERNAME,
        password=config.SVC_PASSWORD,
        database=config.NEXUS_DATABASE,
        port="1433",
        as_dict=True,
        autocommit=False,
    )


def claim_pending_message():
    """Atomically claim the oldest pending user message.

    Returns the claimed row (dict) or None. UPDATE ... OUTPUT makes the
    claim atomic, so even a second worker instance could not double-claim.
    """
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE m
            SET m.status = 'processing'
            OUTPUT inserted.message_id, inserted.session_id, inserted.content
            FROM dbo.tai_chat_messages AS m
            WHERE m.message_id = (
                SELECT TOP 1 message_id
                FROM dbo.tai_chat_messages
                WHERE status = 'pending' AND role = 'user'
                ORDER BY message_id
            )
            """
        )
        row = cur.fetchone()
        conn.commit()
        return row
    finally:
        conn.close()


def load_history(session_id, exclude_message_id):
    """Prior user/assistant turns for the session, oldest first,
    capped at the most recent HISTORY_MAX_TURNS rows."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT role, content FROM (
                SELECT TOP %s message_id, role, content
                FROM dbo.tai_chat_messages
                WHERE session_id = %s
                  AND message_id < %s
                  AND role IN ('user', 'assistant')
                ORDER BY message_id DESC
            ) AS recent
            ORDER BY message_id ASC
            """,
            (config.HISTORY_MAX_TURNS, session_id, exclude_message_id),
        )
        return cur.fetchall()
    finally:
        conn.close()


def get_session_username(session_id):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT username FROM dbo.tai_chat_sessions WHERE session_id = %s",
            (session_id,),
        )
        row = cur.fetchone()
        return row["username"] if row else "unknown"
    finally:
        conn.close()


def insert_status(session_id, text):
    """Transient 'working on it' line shown in the chat."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO dbo.tai_chat_messages (session_id, role, content, status)
            VALUES (%s, 'status', %s, 'done')
            """,
            (session_id, text),
        )
        conn.commit()
    finally:
        conn.close()


def insert_assistant(session_id, content, tool_trace, model,
                     input_tokens, output_tokens, latency_ms):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO dbo.tai_chat_messages
                (session_id, role, content, tool_trace, status,
                 model, input_tokens, output_tokens, latency_ms)
            VALUES (%s, 'assistant', %s, %s, 'done', %s, %s, %s, %s)
            """,
            (
                session_id,
                content,
                json.dumps(tool_trace) if tool_trace else None,
                model,
                input_tokens,
                output_tokens,
                latency_ms,
            ),
        )
        cur.execute(
            "UPDATE dbo.tai_chat_sessions SET last_activity_at = GETDATE() "
            "WHERE session_id = %s",
            (session_id,),
        )
        conn.commit()
    finally:
        conn.close()


def insert_error(session_id, text):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO dbo.tai_chat_messages (session_id, role, content, status)
            VALUES (%s, 'error', %s, 'done')
            """,
            (session_id, text),
        )
        conn.commit()
    finally:
        conn.close()


def insert_export_file(session_id, filename, blob):
    """Store a generated export; returns file_id."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO dbo.tai_chat_files (session_id, filename, file_bytes, byte_count)
            OUTPUT inserted.file_id
            VALUES (%s, %s, %s, %s)
            """,
            (session_id, filename, blob, len(blob)),
        )
        file_id = cur.fetchone()["file_id"]
        conn.commit()
        return file_id
    finally:
        conn.close()


def insert_file_message(session_id, file_id, filename):
    """Attach a download chip to the thread (role='file' row)."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO dbo.tai_chat_messages
                (session_id, role, content, status, file_id)
            VALUES (%s, 'file', %s, 'done', %s)
            """,
            (session_id, filename, file_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_user_message(message_id, status):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.tai_chat_messages SET status = %s WHERE message_id = %s",
            (status, message_id),
        )
        conn.commit()
    finally:
        conn.close()


# ── voice (voice-1.0.0) ──────────────────────────────────────────────

def claim_pending_voice_job():
    """Atomically claim the oldest pending voice job (TTS or STT).
    Returns the claimed row (dict) or None."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE m
            SET m.status = 'processing'
            OUTPUT inserted.message_id, inserted.session_id,
                   inserted.role, inserted.content, inserted.file_id
            FROM dbo.tai_chat_messages AS m
            WHERE m.message_id = (
                SELECT TOP 1 message_id
                FROM dbo.tai_chat_messages
                WHERE status = 'pending'
                  AND role IN ('voice_req', 'stt_req')
                ORDER BY message_id
            )
            """
        )
        row = cur.fetchone()
        conn.commit()
        return row
    finally:
        conn.close()


def get_message_content(message_id):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM dbo.tai_chat_messages WHERE message_id = %s",
            (message_id,),
        )
        row = cur.fetchone()
        return row["content"] if row else None
    finally:
        conn.close()


def get_file_bytes(file_id):
    """Returns (bytes, content_type) for a stored file."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT file_bytes, content_type FROM dbo.tai_chat_files "
            "WHERE file_id = %s",
            (file_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"file {file_id} not found")
        return bytes(row["file_bytes"]), row["content_type"]
    finally:
        conn.close()


def insert_media_file(session_id, filename, blob, content_type):
    """Store a non-Excel file (audio etc.) with an explicit MIME type."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO dbo.tai_chat_files
                (session_id, filename, content_type, file_bytes, byte_count)
            OUTPUT inserted.file_id
            VALUES (%s, %s, %s, %s, %s)
            """,
            (session_id, filename, content_type, blob, len(blob)),
        )
        file_id = cur.fetchone()["file_id"]
        conn.commit()
        return file_id
    finally:
        conn.close()


def insert_voice_row(session_id, role, content, file_id):
    """Announce a finished voice result to the thread ('voice'/'stt')."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO dbo.tai_chat_messages
                (session_id, role, content, status, file_id)
            VALUES (%s, %s, %s, 'done', %s)
            """,
            (session_id, role, content, file_id),
        )
        conn.commit()
    finally:
        conn.close()


def recover_stuck_messages():
    """On service start, requeue anything left 'processing' by a crash."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.tai_chat_messages SET status = 'pending' "
            "WHERE status = 'processing' "
            "AND role IN ('user', 'voice_req', 'stt_req')"
        )
        n = cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()
