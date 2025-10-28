import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Set
from datetime import datetime, timedelta


# Обрабатываем последние 6 месяцев, но минимум 30 сообщений (= размер партии)
MINIMUM_MESSAGES_TO_PROCESS = 30

def get_six_months_ago() -> str:
    """Возвращает дату 6 месяцев назад в ISO формате"""
    six_months_ago = datetime.now() - timedelta(days=180)
    return six_months_ago.strftime("%Y-%m-%dT%H:%M:%S")


def should_use_time_filter(conn: sqlite3.Connection, chat_id: int, after_date: Optional[str]) -> bool:
    """Проверяет нужно ли фильтровать по времени (6 мес) или брать минимум 30 сообщений.
    
    Логика:
    - Если за последние 6 месяцев >= 30 непройденных сообщений → фильтруем по времени
    - Если за последние 6 месяцев < 30 непройденных сообщений → берем последние 30 (без фильтра по времени)
    """
    six_months_ago = get_six_months_ago()
    cutoff_date = max(after_date, six_months_ago) if after_date else six_months_ago
    
    # Считаем сколько непройденных сообщений за последние 6 месяцев
    count = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND date > ?",
        (chat_id, cutoff_date),
    ).fetchone()[0]
    
    # Если >= 30 сообщений за полгода → фильтруем по времени
    return count >= MINIMUM_MESSAGES_TO_PROCESS


DDL_CONTEXTS = """
CREATE TABLE IF NOT EXISTS dialog_contexts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dialog_id TEXT,
    message_date TEXT,
    context_text TEXT,
    context_json TEXT
);
"""

DDL_DENIED = """
CREATE TABLE IF NOT EXISTS dialog_denied (
    dialog_id TEXT PRIMARY KEY,
    denied_at TEXT,
    reason TEXT
);
"""

DDL_INDEX_MSG = (
    "CREATE INDEX IF NOT EXISTS idx_messages_chat_date ON messages(chat_id, date);"
)
DDL_INDEX_CTX = "CREATE INDEX IF NOT EXISTS idx_ctx_dialog_date ON dialog_contexts(dialog_id, message_date);"
DDL_UNIQUE_CTX = "CREATE UNIQUE INDEX IF NOT EXISTS uq_ctx_dialog_date ON dialog_contexts(dialog_id, message_date);"

DDL_BATCH_REQUESTS = """
CREATE TABLE IF NOT EXISTS batch_requests (
    custom_id TEXT PRIMARY KEY,
    requested_at TEXT,
    applied_at TEXT
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
    except Exception:
        pass
    conn.execute(DDL_CONTEXTS)
    # Migrate: add context_json if missing
    cur = conn.execute("PRAGMA table_info(dialog_contexts);")
    cols = {row[1] for row in cur.fetchall()}
    if "context_json" not in cols:
        try:
            conn.execute("ALTER TABLE dialog_contexts ADD COLUMN context_json TEXT;")
        except Exception:
            pass
    conn.execute(DDL_DENIED)
    conn.execute(DDL_INDEX_MSG)
    conn.execute(DDL_INDEX_CTX)
    conn.execute(DDL_UNIQUE_CTX)
    conn.execute(DDL_BATCH_REQUESTS)
    conn.commit()


def table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table});")
    return any(row[1] == column for row in cur.fetchall())


def get_last_context_date(conn: sqlite3.Connection, chat_id: int) -> Optional[str]:
    row = conn.execute(
        "SELECT MAX(message_date) FROM dialog_contexts WHERE dialog_id = ?",
        (str(chat_id),),
    ).fetchone()
    return row[0] if row and row[0] else None


def load_denied_ids(conn: sqlite3.Connection) -> Set[int]:
    ids: Set[int] = set()
    cur = conn.execute("SELECT dialog_id FROM dialog_denied")
    for (did,) in cur.fetchall():
        try:
            ids.add(int(did))
        except Exception:
            continue
    return ids


def dialog_has_unprocessed(
    conn: sqlite3.Connection, chat_id: int, after_date: Optional[str]
) -> bool:
    # Проверяем нужно ли фильтровать по времени или брать последние N сообщений
    use_time_filter = should_use_time_filter(conn, chat_id, after_date)
    
    if use_time_filter:
        # >= 30 сообщений за 6 месяцев → проверяем по времени
        six_months_ago = get_six_months_ago()
        cutoff_date = max(after_date, six_months_ago) if after_date else six_months_ago
        row = conn.execute(
            "SELECT 1 FROM messages WHERE chat_id = ? AND date > ? LIMIT 1",
            (chat_id, cutoff_date),
        ).fetchone()
    else:
        # < 30 сообщений за 6 месяцев → проверяем есть ли вообще непройденные (последние MINIMUM_MESSAGES_TO_PROCESS)
        if after_date:
            row = conn.execute(
                "SELECT 1 FROM messages WHERE chat_id = ? AND date > ? LIMIT 1",
                (chat_id, after_date),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM messages WHERE chat_id = ? LIMIT 1",
                (chat_id,),
            ).fetchone()
    return bool(row)


def mark_denied(
    conn: sqlite3.Connection, chat_id: int, reason: str = "user_denied"
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO dialog_denied(dialog_id, denied_at, reason) VALUES(?, datetime('now'), ?)",
        (str(chat_id), reason),
    )
    conn.commit()


def get_unprocessed_overview(
    conn: sqlite3.Connection, exclude_ids: Optional[Set[int]] = None
) -> List[Dict[str, Any]]:
    last_dates: Dict[int, Optional[str]] = {}
    cur = conn.execute(
        "SELECT dialog_id, MAX(message_date) FROM dialog_contexts GROUP BY dialog_id;"
    )
    for did, maxdt in cur.fetchall():
        try:
            last_dates[int(did)] = maxdt
        except Exception:
            continue
    rows = conn.execute(
        "SELECT chat_id, COUNT(*) AS cnt, MAX(date) AS latest, MAX(chat_name) AS chat_name FROM messages GROUP BY chat_id"
    ).fetchall()
    overview: List[Dict[str, Any]] = []
    for chat_id, total_cnt, latest, chat_name in rows:
        chat_id = int(chat_id)
        if exclude_ids and chat_id in exclude_ids:
            continue
        last_dt = last_dates.get(chat_id)
        
        # Проверяем нужно ли фильтровать по времени или брать последние N сообщений
        use_time_filter = should_use_time_filter(conn, chat_id, last_dt)
        
        if use_time_filter:
            # >= 30 сообщений за 6 месяцев → считаем по времени
            six_months_ago = get_six_months_ago()
            cutoff_date = max(last_dt, six_months_ago) if last_dt else six_months_ago
            unprocessed = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND date > ?",
                (chat_id, cutoff_date),
            ).fetchone()[0]
        else:
            # < 30 сообщений за 6 месяцев → считаем последние MINIMUM_MESSAGES_TO_PROCESS
            if last_dt:
                unprocessed = conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND date > ?",
                    (chat_id, last_dt),
                ).fetchone()[0]
                # Ограничиваем максимум MINIMUM_MESSAGES_TO_PROCESS
                unprocessed = min(unprocessed, MINIMUM_MESSAGES_TO_PROCESS)
            else:
                # Берем минимум из (всего сообщений, MINIMUM_MESSAGES_TO_PROCESS)
                unprocessed = min(total_cnt, MINIMUM_MESSAGES_TO_PROCESS)
        
        overview.append(
            {
                "chat_id": chat_id,
                "total_count": int(total_cnt),
                "latest_message_date": latest,
                "last_processed_date": last_dt,
                "unprocessed_count": int(unprocessed),
                "chat_name": chat_name,
            }
        )
    overview = [o for o in overview if o["unprocessed_count"] > 0]
    overview.sort(key=lambda o: (o["total_count"], o["chat_id"]))
    return overview


def fetch_next_chunk(
    conn: sqlite3.Connection, chat_id: int, after_date: Optional[str], limit: int
) -> List[Dict[str, Any]]:
    from .db import table_has_column as _thc  # self-import safe in package scope

    has_transcript = _thc(conn, "messages", "transcript")
    select_text = (
        "COALESCE(NULLIF(TRIM(m.text), ''), NULLIF(TRIM(m.transcript), ''))"
        if has_transcript
        else "m.text"
    )
    # sender columns fallback
    has_msg_from_name = _thc(conn, "messages", "from_name")
    has_msg_from_username = _thc(conn, "messages", "from_username")
    sel_sender_name = (
        "u.name" if not has_msg_from_name else "COALESCE(u.name, m.from_name)"
    )
    sel_sender_username = (
        "u.username"
        if not has_msg_from_username
        else "COALESCE(u.username, m.from_username)"
    )
    
    # Проверяем нужно ли фильтровать по времени или брать последние N сообщений
    use_time_filter = should_use_time_filter(conn, chat_id, after_date)
    
    params: Tuple[Any, ...]
    if use_time_filter:
        # >= 30 сообщений за 6 месяцев → фильтруем по времени
        six_months_ago = get_six_months_ago()
        cutoff_date = max(after_date, six_months_ago) if after_date else six_months_ago
        
        query = f"""
			SELECT m.message_id, m.date, m.from_id, m.direction,
			       {select_text} AS content,
			       {sel_sender_name} AS sender_name,
			       {sel_sender_username} AS sender_username,
			       m.json
			FROM messages m
			LEFT JOIN users u ON u.id = m.from_id
			WHERE m.chat_id = ? AND m.date > ?
			ORDER BY m.date ASC, m.message_id ASC
			LIMIT ?
		"""
        params = (chat_id, cutoff_date, limit)
    else:
        # < 30 сообщений за 6 месяцев → берем последние MINIMUM_MESSAGES_TO_PROCESS без фильтра по времени
        if after_date:
            query = f"""
				SELECT m.message_id, m.date, m.from_id, m.direction,
				       {select_text} AS content,
				       {sel_sender_name} AS sender_name,
				       {sel_sender_username} AS sender_username,
				       m.json
				FROM messages m
				LEFT JOIN users u ON u.id = m.from_id
				WHERE m.chat_id = ? AND m.date > ?
				ORDER BY m.date ASC, m.message_id ASC
				LIMIT ?
			"""
            params = (chat_id, after_date, MINIMUM_MESSAGES_TO_PROCESS)
        else:
            # Берем последние MINIMUM_MESSAGES_TO_PROCESS сообщений (сначала выбираем последние N, потом сортируем по возрастанию)
            query = f"""
				SELECT m.message_id, m.date, m.from_id, m.direction,
				       {select_text} AS content,
				       {sel_sender_name} AS sender_name,
				       {sel_sender_username} AS sender_username,
				       m.json
				FROM (
					SELECT * FROM messages
					WHERE chat_id = ?
					ORDER BY date DESC, message_id DESC
					LIMIT ?
				) m
				LEFT JOIN users u ON u.id = m.from_id
				ORDER BY m.date ASC, m.message_id ASC
			"""
            params = (chat_id, MINIMUM_MESSAGES_TO_PROCESS)
    rows = conn.execute(query, params).fetchall()
    result: List[Dict[str, Any]] = []
    for r in rows:
        msg = {
            "message_id": r[0],
            "date": r[1],
            "from_id": r[2],
            "direction": r[3],
            "content": (r[4] or "").strip() if r[4] is not None else "",
            "sender_name": r[5],
            "sender_username": r[6],
        }
        # Forwarded metadata (optional)
        try:
            js = r[7]
            if js:
                import json as _json

                jb = _json.loads(js)
                fwd = jb.get("fwd_from")
                if fwd:
                    msg["is_forwarded"] = True
                    name = fwd.get("from_name")
                    if not name:
                        peer = fwd.get("from_id") or fwd.get("from_peer")
                        if isinstance(peer, dict):
                            uname = peer.get("username")
                            uid = (
                                peer.get("user_id")
                                or peer.get("channel_id")
                                or peer.get("chat_id")
                            )
                            name = uname or (f"user:{uid}" if uid else None)
                    if isinstance(name, str) and name.strip():
                        msg["forwarded_from"] = name.strip()
        except Exception:
            pass
        result.append(msg)
    return result


def upsert_context_block(
    conn: sqlite3.Connection,
    chat_id: int,
    message_date: str,
    context_text: str,
    context_json: Optional[str] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO dialog_contexts (dialog_id, message_date, context_text, context_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(dialog_id, message_date)
        DO UPDATE SET context_text = excluded.context_text, context_json = excluded.context_json
        """,
        (str(chat_id), message_date, context_text, context_json),
    )
    conn.commit()


def mark_batch_requested(conn: sqlite3.Connection, custom_ids: List[str]) -> None:
    if not custom_ids:
        return
    now_sql = "datetime('now')"
    cur = conn.cursor()
    for cid in custom_ids:
        try:
            cur.execute(
                "INSERT INTO batch_requests(custom_id, requested_at) VALUES(?, %s) ON CONFLICT(custom_id) DO UPDATE SET requested_at = %s WHERE batch_requests.applied_at IS NULL"
                % (now_sql, now_sql),
                (cid,),
            )
        except Exception:
            continue
    conn.commit()


def mark_batch_applied(conn: sqlite3.Connection, custom_id: str) -> None:
    try:
        conn.execute(
            "UPDATE batch_requests SET applied_at = datetime('now') WHERE custom_id = ?",
            (custom_id,),
        )
        conn.commit()
    except Exception:
        pass


def get_blocked_custom_ids(conn: sqlite3.Connection) -> Set[str]:
    blocked: Set[str] = set()
    try:
        cur = conn.execute(
            "SELECT custom_id FROM batch_requests WHERE applied_at IS NULL AND requested_at IS NOT NULL"
        )
        for (cid,) in cur.fetchall():
            if isinstance(cid, str) and cid:
                blocked.add(cid)
    except Exception:
        return blocked
    return blocked
