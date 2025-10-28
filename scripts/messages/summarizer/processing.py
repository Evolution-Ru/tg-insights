from typing import Any, Dict, List, Optional, Tuple, Callable, Set
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import db as sdb
from . import participants as spart
from .prompting import compose_system_ru, compose_user_prompt, build_responses_input
from .logging import (
    log,
    log_dialog_pick,
    log_overview_entry,
    log_overview_header,
    log_parallel_done,
)


def render_messages_for_model(messages: List[Dict[str, Any]]) -> str:
    """Render raw message dicts into a compact, model-friendly text.

    - Groups consecutive messages by the same author within 1 hour
    - Preserves timestamps (ISO) and author label per group
    - Marks forwarded messages
    """
    lines: List[str] = []

    current_author: Optional[str] = None
    group_start_date: Optional[str] = None
    last_dt: Optional[datetime] = None
    buffer_contents: List[str] = []

    def flush_group() -> None:
        nonlocal current_author, group_start_date, buffer_contents
        if current_author and group_start_date and buffer_contents:
            lines.append(
                f"[{group_start_date}] {current_author}: " + "\n".join(buffer_contents)
            )
        current_author = None
        group_start_date = None
        buffer_contents = []

    for m in messages:
        author = (
            "Юрий Чукаев"
            if m.get("direction") == "out"
            else (
                m.get("sender_name")
                or m.get("sender_username")
                or (f"user:{m['from_id']}" if m.get("from_id") else "unknown")
            )
        )
        content = (m.get("content") or "").strip()
        if not content:
            continue
        fwd_prefix = ""
        if m.get("is_forwarded"):
            src = m.get("forwarded_from")
            fwd_prefix = f"[переслано от {src}] " if src else "[переслано] "

        date_str = m.get("date")
        try:
            dt = (
                datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                if date_str
                else None
            )
        except Exception:
            dt = None

        can_merge = (
            current_author == author
            and last_dt is not None
            and dt is not None
            and (dt - last_dt) <= timedelta(hours=1)
        )

        if can_merge:
            buffer_contents.append(f"{fwd_prefix}{content}")
            last_dt = dt or last_dt
        else:
            flush_group()
            current_author = author
            group_start_date = date_str
            last_dt = dt
            buffer_contents = [f"{fwd_prefix}{content}"]

    flush_group()
    return "\n".join(lines)


def prepare_dialog_request(
    conn,
    chat_id: int,
    max_chunk: int,
    model_name: str,
    log_io: bool,
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Build a single JSONL request line for the Batch API for one dialog chunk.

    Returns:
        (request_line, meta) or None if there is nothing meaningful to process.
    """
    last_dt = sdb.get_last_context_date(conn, chat_id)
    chunk = sdb.fetch_next_chunk(conn, chat_id, last_dt, max_chunk)
    if not chunk:
        return None
    rendered = render_messages_for_model(chunk)
    if not rendered.strip():
        last_date = chunk[-1]["date"]
        sdb.upsert_context_block(
            conn, chat_id, last_date, "[нет нового содержательного контента]"
        )
        return None
    participants = spart.build_participants(chunk)
    participants_header = spart.build_participants_header(chunk)
    prev_ctx_row = conn.execute(
        """
		SELECT context_text
		FROM dialog_contexts
		WHERE dialog_id = ?
		ORDER BY message_date DESC, id DESC
		LIMIT 1
		""",
        (str(chat_id),),
    ).fetchone()
    prev_context = prev_ctx_row[0] if prev_ctx_row and prev_ctx_row[0] else None
    chat_row = conn.execute(
        "SELECT chat_name, chat_type, username FROM messages WHERE chat_id = ? ORDER BY date DESC LIMIT 1",
        (chat_id,),
    ).fetchone()
    chat_title = chat_row[0] if chat_row and chat_row[0] else None
    chat_type = chat_row[1] if chat_row and len(chat_row) > 1 else None
    chat_username = chat_row[2] if chat_row and len(chat_row) > 2 else None

    participants, participants_header = spart.adjust_for_user_chat(
        chunk, chat_title, chat_type, chat_username, participants, participants_header
    )

    last_date = chunk[-1]["date"]
    system_ru = compose_system_ru()
    user_prompt, schema_instruction = compose_user_prompt(
        prev_context,
        rendered,
        participants,
        chat_id=chat_id,
        chat_title=chat_title,
        last_message_date=last_date,
    )

    input_messages = build_responses_input(system_ru, user_prompt, schema_instruction)
    body = {
        "model": model_name,
        "input": input_messages,
        "reasoning": {"effort": "low"},
    }
    custom_id = f"dlg:{chat_id}:{last_date}"
    request_line = {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/responses",
        "body": body,
    }
    meta = {
        "chat_id": chat_id,
        "last_date": last_date,
        "participants_header": participants_header,
    }
    return request_line, meta


def pick_next_dialog(
    conn: sqlite3.Connection,
    only_dialog: Optional[int] = None,
    exclude_ids: Optional[Set[int]] = None,
) -> Optional[Tuple[int, int, Optional[str]]]:
    """Choose next dialog with unprocessed messages.

    Returns:
        (chat_id, total_messages, last_context_date) or None.
    """
    last_dates: Dict[int, Optional[str]] = {}
    cur = conn.execute(
        "SELECT dialog_id, MAX(message_date) FROM dialog_contexts GROUP BY dialog_id;"
    )
    for did, maxdt in cur.fetchall():
        try:
            last_dates[int(did)] = maxdt
        except Exception:
            continue

    if only_dialog is not None:
        row = conn.execute(
            "SELECT chat_id, COUNT(*) AS cnt FROM messages WHERE chat_id = ?",
            (only_dialog,),
        ).fetchone()
        if not row:
            return None
        chat_id, cnt = int(row[0]), int(row[1])
        last_dt = last_dates.get(chat_id)
        if sdb.dialog_has_unprocessed(conn, chat_id, last_dt):
            return chat_id, cnt, last_dt
        return None

    cur = conn.execute(
        "SELECT chat_id, COUNT(*) AS cnt FROM messages GROUP BY chat_id ORDER BY cnt ASC;"
    )
    for chat_id, cnt in cur.fetchall():
        chat_id = int(chat_id)
        if exclude_ids and chat_id in exclude_ids:
            continue
        last_dt = last_dates.get(chat_id)
        if sdb.dialog_has_unprocessed(conn, chat_id, last_dt):
            return chat_id, int(cnt), last_dt
    return None


def process_dialog_until_done(
    db_path: Path,
    chat_id: int,
    max_chunk: int,
    log_io: bool,
    process_one_dialog_func: Callable[
        [sqlite3.Connection, int, Optional[str], int, bool], Optional[Tuple[int, int]]
    ],
) -> Tuple[int, int]:
    """Process one dialog end-to-end in a dedicated SQLite connection.

    Returns:
        (chat_id, total_processed_messages)
    """
    conn = sqlite3.connect(str(db_path))
    try:
        sdb.ensure_schema(conn)
        total_processed_for_dialog = 0
        while True:
            cur_last_dt = sdb.get_last_context_date(conn, chat_id)
            res = process_one_dialog_func(conn, chat_id, cur_last_dt, max_chunk, log_io)
            if not res:
                break
            _, processed_cnt = res
            total_processed_for_dialog += processed_cnt
        return chat_id, total_processed_for_dialog
    finally:
        conn.close()


def process_overview_sequential(
    conn: sqlite3.Connection,
    max_dialogs: int,
    max_chunk: int,
    log_io: bool,
    *,
    exclude_ids: Optional[Set[int]] = None,
    confirm: bool = False,
    preview_participants: (
        Callable[[sqlite3.Connection, int, Optional[str], int], List[str]] | None
    ) = None,
    on_denied: Callable[[sqlite3.Connection, int, str], None] | None = None,
    process_one_dialog_func: Callable[
        [sqlite3.Connection, int, Optional[str], int, bool], Optional[Tuple[int, int]]
    ],
) -> None:
    """Sequentially process up to N dialogs from overview using the provided worker.

    Supports optional interactive confirmation and denial hook per dialog.
    """
    processed_ids: Set[int] = set(exclude_ids or set())
    processed_total = 0
    while processed_total < max(1, int(max_dialogs)):
        cand = pick_next_dialog(conn, exclude_ids=processed_ids)
        if not cand:
            if processed_total == 0:
                log("Нет диалогов с необработанными сообщениями.")
            break
        chat_id, total_cnt, last_dt = cand
        log_dialog_pick(chat_id, total_cnt, last_dt)
        if confirm:
            row = conn.execute(
                "SELECT chat_name FROM messages WHERE chat_id = ? ORDER BY date DESC LIMIT 1",
                (chat_id,),
            ).fetchone()
            chat_title = row[0] if row and row[0] else str(chat_id)
            unprocessed = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND date > COALESCE(?, '0000-01-01T00:00:00')",
                (chat_id, last_dt),
            ).fetchone()[0]
            if preview_participants:
                ph = preview_participants(
                    conn, chat_id, last_dt, limit=max(10, min(30, max_chunk))
                )
                if ph:
                    log("Участники: " + ", ".join(ph))
            log(
                f"Обработать диалог {chat_id} / {chat_title}? Непройденных сообщений: {unprocessed}. [y/N]"
            )
            ans = input("").strip().lower()
            if not ans or ans[0] != "y":
                if on_denied:
                    on_denied(conn, chat_id, "user_denied_interactive")
                log(
                    f"Диалог {chat_id} отклонён пользователем — помечен в dialog_denied."
                )
                processed_ids.add(chat_id)
                continue
        total_processed_for_dialog = 0
        while True:
            cur_last_dt = sdb.get_last_context_date(conn, chat_id)
            res = process_one_dialog_func(conn, chat_id, cur_last_dt, max_chunk, log_io)
            if not res:
                break
            processed_chat, processed_cnt = res
            total_processed_for_dialog += processed_cnt
            log(
                f"Готово: dialog_id={processed_chat}, обработано сообщений в партии={processed_cnt} (сумма={total_processed_for_dialog})"
            )
        log(f"Диалог {chat_id} полностью обработан.")
        processed_ids.add(chat_id)
        processed_total += 1


def print_overview(
    conn: sqlite3.Connection,
    overview: List[Dict[str, Any]],
    max_chunk: int,
    max_dialogs: int,
) -> None:
    """Emit a short summary of the upcoming work (counts and per-dialog preview)."""
    total_dialogs_found = len(overview)
    dialogs_to_process = min(total_dialogs_found, max(1, int(max_dialogs)))
    overview_slice = overview[:dialogs_to_process]
    
    total_batches = sum(
        (o["unprocessed_count"] + max(1, max_chunk) - 1) // max(1, max_chunk)
        for o in overview_slice
    )
    
    # Показываем сколько найдено ВСЕГО и сколько будет обработано
    if total_dialogs_found > dialogs_to_process:
        log(f"Найдено диалогов: {total_dialogs_found}, будет обработано: {dialogs_to_process} (--max-dialogs)")
    else:
        log(f"Найдено диалогов: {total_dialogs_found}")
    
    log_overview_header(dialogs_to_process, total_batches, max_chunk)
    
    for o in overview_slice:
        batches = (o["unprocessed_count"] + max(1, max_chunk) - 1) // max(1, max_chunk)
        title = o.get("chat_name") or f"ID:{o['chat_id']}"
        log_overview_entry(
            int(o["chat_id"]),
            title,
            int(o["total_count"]),
            int(o["unprocessed_count"]),
            batches,
        )


def process_overview_parallel(
    db_path: Path,
    overview: List[Dict[str, Any]],
    *,
    max_dialogs: int,
    concurrency: int,
    max_chunk: int,
    log_io: bool,
    process_dialog_until_done_func: Callable[[Path, int, int, bool], Tuple[int, int]],
) -> None:
    """Process up to N dialogs in parallel using a provided worker.

    The worker should accept (db_path, chat_id, max_chunk, log_io) and return (chat_id, processed_cnt).
    """
    slice_overview = overview[: max(1, int(max_dialogs))]
    dialog_ids = [int(o["chat_id"]) for o in slice_overview]
    results: List[Tuple[int, int]] = []
    with ThreadPoolExecutor(max_workers=int(concurrency)) as pool:
        fut_to_id = {
            pool.submit(
                process_dialog_until_done_func,
                db_path,
                did,
                int(max_chunk),
                bool(log_io),
            ): did
            for did in dialog_ids
        }
        for fut in as_completed(fut_to_id):
            did = fut_to_id[fut]
            try:
                processed_chat, processed_cnt = fut.result()
                results.append((processed_chat, processed_cnt))
                log(
                    f"Диалог {processed_chat} завершён (обработано сообщений: {processed_cnt})."
                )
            except Exception as e:
                log(f"Ошибка при обработке диалога {did}: {e}")
    total_msgs = sum(cnt for _, cnt in results)
    log_parallel_done(len(results), total_msgs)
