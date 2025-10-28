from typing import Any, Dict, List, Optional, Tuple
import sqlite3
from .db import table_has_column


def build_participants(messages: List[Dict[str, Any]]) -> List[str]:
    parts: List[str] = []
    seen = set()
    for m in messages:
        name = None
        if m.get("direction") == "out":
            name = "Я"
        else:
            if m.get("sender_name"):
                name = m["sender_name"]
            elif m.get("sender_username"):
                name = m["sender_username"]
            elif m.get("from_id"):
                name = f"user:{m['from_id']}"
        if name and name not in seen:
            seen.add(name)
            parts.append(name)
    return parts


def build_participants_header(messages: List[Dict[str, Any]]) -> List[str]:
    header_parts: List[str] = []
    seen: set[str] = set()
    for m in messages:
        label = None
        if m.get("direction") == "out":
            nm = m.get("sender_name")
            un = m.get("sender_username")
            fid = m.get("from_id")
            if nm or un:
                base = nm or un
                details: List[str] = []
                if un and un != base:
                    details.append(un)
                if fid:
                    details.append(str(fid))
                label = f"{base} (" + ", ".join(details) + ")" if details else base
            else:
                label = "Я"
        else:
            nm = m.get("sender_name")
            un = m.get("sender_username")
            fid = m.get("from_id")
            base = nm or un or (f"user:{fid}" if fid else "unknown")
            details: List[str] = []
            if un and un != base:
                details.append(un)
            if fid:
                details.append(str(fid))
            label = f"{base} (" + ", ".join(details) + ")" if details else base
        if label and label not in seen:
            seen.add(label)
            header_parts.append(label)
    return header_parts


def preview_participants_for_dialog(
    conn: sqlite3.Connection,
    chat_id: int,
    after_date: Optional[str],
    limit: int = 30,
) -> List[str]:
    """Вернёт список участников (заголовок), рассчитанный на первых limit непройденных сообщениях."""
    has_msg_from_name = table_has_column(conn, "messages", "from_name")
    has_msg_from_username = table_has_column(conn, "messages", "from_username")
    sel_sender_name = "u.name" if not has_msg_from_name else "COALESCE(u.name, m.from_name)"
    sel_sender_username = (
        "u.username" if not has_msg_from_username else "COALESCE(u.username, m.from_username)"
    )
    params: Tuple[Any, ...]
    if after_date:
        q = f"""
			SELECT m.message_id, m.date, m.from_id, m.direction,
				   {sel_sender_name} AS sender_name,
				   {sel_sender_username} AS sender_username
			FROM messages m
			LEFT JOIN users u ON u.id = m.from_id
			WHERE m.chat_id = ? AND m.date > ?
			ORDER BY m.date ASC, m.message_id ASC
			LIMIT ?
		"""
        params = (chat_id, after_date, limit)
    else:
        q = f"""
			SELECT m.message_id, m.date, m.from_id, m.direction,
				   {sel_sender_name} AS sender_name,
				   {sel_sender_username} AS sender_username
			FROM messages m
			LEFT JOIN users u ON u.id = m.from_id
			WHERE m.chat_id = ?
			ORDER BY m.date ASC, m.message_id ASC
			LIMIT ?
		"""
        params = (chat_id, limit)
    rows = conn.execute(q, params).fetchall()
    msgs: List[Dict[str, Any]] = []
    inbound_id = None
    for r in rows:
        msgs.append(
            {
                "message_id": r[0],
                "date": r[1],
                "from_id": r[2],
                "direction": r[3],
                "sender_name": r[4],
                "sender_username": r[5],
            }
        )
        if inbound_id is None and r[3] == "in" and r[2] is not None:
            inbound_id = r[2]
    header = build_participants_header(msgs)

    # Применяем фолбэк для 1:1: unknown -> chat_title/username/from_id
    chat_row = conn.execute(
        "SELECT chat_name, chat_type, username FROM messages WHERE chat_id = ? ORDER BY date DESC LIMIT 1",
        (chat_id,),
    ).fetchone()
    chat_title = chat_row[0] if chat_row and chat_row[0] else None
    chat_type = chat_row[1] if chat_row and len(chat_row) > 1 else None
    chat_username = chat_row[2] if chat_row and len(chat_row) > 2 else None
    if chat_type == "user":
        base = (
            chat_title or chat_username or (f"user:{inbound_id}" if inbound_id else "unknown")
        ).strip()
        details: List[str] = []
        if chat_username and chat_username != base:
            details.append(chat_username)
        if inbound_id:
            details.append(str(inbound_id))
        other_label = f"{base} (" + ", ".join(details) + ")" if details else base
        header = [other_label if p == "unknown" else p for p in header]
    return header


def adjust_for_user_chat(
    chunk: List[Dict[str, Any]],
    chat_title: Optional[str],
    chat_type: Optional[str],
    chat_username: Optional[str],
    participants: List[str],
    participants_header: List[str],
) -> Tuple[List[str], List[str]]:
    if chat_type != "user":
        return participants, participants_header
    inbound_id = None
    for m in chunk:
        if m.get("direction") == "in" and m.get("from_id"):
            inbound_id = m.get("from_id")
            break
    base = (
        chat_title or chat_username or (f"user:{inbound_id}" if inbound_id else "unknown")
    ).strip()
    details: List[str] = []
    if chat_username and chat_username != base:
        details.append(chat_username)
    if inbound_id:
        details.append(str(inbound_id))
    other_label = f"{base} (" + ", ".join(details) + ")" if details else base
    participants2 = [other_label if p == "unknown" else p for p in participants]
    header2 = [other_label if p == "unknown" else p for p in participants_header]
    return participants2, header2
