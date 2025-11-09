"""
Утилиты для работы с базой данных сообщений
"""
import sqlite3
from typing import List, Dict, Any, Optional
from pathlib import Path


def get_db_connection(db_path: Path) -> sqlite3.Connection:
    """
    Создает подключение к базе данных сообщений.
    """
    return sqlite3.connect(str(db_path))


def get_all_messages_from_chats(
    conn: sqlite3.Connection, 
    chat_ids: Dict[str, str], 
    limit_messages_per_chat: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Получает все сообщения из указанных чатов, отсортированные по дате.
    Возвращает объединенный поток сообщений с пометками чатов.
    """
    print(f"\n📥 Сбор всех сообщений из {len(chat_ids)} чатов...")
    
    all_messages = []
    
    for chat_name, chat_id in chat_ids.items():
        print(f"   📋 {chat_name} ({chat_id})...", end=" ", flush=True)
        
        # Получаем сообщения из чата
        query = """
            SELECT 
                m.message_id,
                m.date,
                m.from_id,
                COALESCE(NULLIF(TRIM(m.text), ''), NULLIF(TRIM(m.transcript), ''), '') as content,
                COALESCE(u.name, m.from_name, 'Неизвестно') as sender_name,
                m.chat_id,
                m.chat_name
            FROM messages m
            LEFT JOIN users u ON u.id = m.from_id
            WHERE m.chat_id = ?
              AND (m.text IS NOT NULL OR m.transcript IS NOT NULL)
              AND (TRIM(m.text) != '' OR TRIM(m.transcript) != '')
        """
        
        params = [chat_id]
        
        if limit_messages_per_chat:
            query += " ORDER BY m.date DESC LIMIT ?"
            params.append(limit_messages_per_chat)
        else:
            query += " ORDER BY m.date ASC"
        
        rows = conn.execute(query, params).fetchall()
        
        messages = []
        for row in rows:
            messages.append({
                "chat_id": str(row[5]),
                "chat_name": chat_name,
                "message_id": row[0],
                "date": row[1],
                "from_id": row[2],
                "content": row[3] or "",
                "sender_name": row[4] or "Неизвестно"
            })
        
        # Если был DESC, переворачиваем для хронологического порядка
        if limit_messages_per_chat:
            messages.reverse()
        
        all_messages.extend(messages)
        print(f"✓ {len(messages)} сообщений")
    
    print(f"\n✓ Всего собрано {len(all_messages)} сообщений из {len(chat_ids)} чатов")
    return all_messages


def get_recent_contexts(
    conn: sqlite3.Connection, 
    chat_id: str, 
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Получает последние контексты (группы сообщений) из чата.
    """
    query = """
        SELECT 
            m.message_id,
            m.date,
            m.from_id,
            COALESCE(NULLIF(TRIM(m.text), ''), NULLIF(TRIM(m.transcript), ''), '') as content,
            COALESCE(u.name, m.from_name, 'Неизвестно') as sender_name,
            m.chat_id,
            m.chat_name
        FROM messages m
        LEFT JOIN users u ON u.id = m.from_id
        WHERE m.chat_id = ?
          AND (m.text IS NOT NULL OR m.transcript IS NOT NULL)
          AND (TRIM(m.text) != '' OR TRIM(m.transcript) != '')
        ORDER BY m.date DESC
        LIMIT ?
    """
    
    rows = conn.execute(query, [chat_id, limit]).fetchall()
    
    contexts = []
    for row in rows:
        contexts.append({
            "chat_id": str(row[5]),
            "chat_name": row[6] or "Неизвестный чат",
            "message_id": row[0],
            "date": row[1],
            "from_id": row[2],
            "content": row[3] or "",
            "sender_name": row[4] or "Неизвестно"
        })
    
    # Переворачиваем для хронологического порядка
    contexts.reverse()
    return contexts


def get_messages_by_ids(
    conn: sqlite3.Connection, 
    message_ids: List[int]
) -> List[Dict[str, Any]]:
    """
    Получает сообщения по их ID.
    """
    if not message_ids:
        return []
    
    placeholders = ','.join(['?'] * len(message_ids))
    query = f"""
        SELECT 
            m.message_id,
            m.date,
            m.from_id,
            COALESCE(NULLIF(TRIM(m.text), ''), NULLIF(TRIM(m.transcript), ''), '') as content,
            COALESCE(u.name, m.from_name, 'Неизвестно') as sender_name,
            m.chat_id,
            m.chat_name
        FROM messages m
        LEFT JOIN users u ON u.id = m.from_id
        WHERE m.message_id IN ({placeholders})
        ORDER BY m.date ASC
    """
    
    rows = conn.execute(query, message_ids).fetchall()
    
    messages = []
    for row in rows:
        messages.append({
            "chat_id": str(row[5]),
            "chat_name": row[6] or "Неизвестный чат",
            "message_id": row[0],
            "date": row[1],
            "from_id": row[2],
            "content": row[3] or "",
            "sender_name": row[4] or "Неизвестно"
        })
    
    return messages


def search_messages_by_keywords(
    conn: sqlite3.Connection,
    chat_ids: Dict[str, str],
    keywords: List[str],
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Ищет сообщения по ключевым словам в указанных чатах.
    """
    if not keywords:
        return []
    
    # Формируем условие поиска
    chat_id_list = list(chat_ids.values())
    placeholders = ','.join(['?'] * len(chat_id_list))
    
    # Поиск по ключевым словам
    keyword_conditions = []
    params = list(chat_id_list)
    
    for keyword in keywords:
        keyword_conditions.append("(m.text LIKE ? OR m.transcript LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    
    query = f"""
        SELECT 
            m.message_id,
            m.date,
            m.from_id,
            COALESCE(NULLIF(TRIM(m.text), ''), NULLIF(TRIM(m.transcript), ''), '') as content,
            COALESCE(u.name, m.from_name, 'Неизвестно') as sender_name,
            m.chat_id,
            m.chat_name
        FROM messages m
        LEFT JOIN users u ON u.id = m.from_id
        WHERE m.chat_id IN ({placeholders})
          AND ({' OR '.join(keyword_conditions)})
          AND (m.text IS NOT NULL OR m.transcript IS NOT NULL)
          AND (TRIM(m.text) != '' OR TRIM(m.transcript) != '')
        ORDER BY m.date DESC
        LIMIT ?
    """
    
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    
    messages = []
    for row in rows:
        messages.append({
            "chat_id": str(row[5]),
            "chat_name": next((name for name, cid in chat_ids.items() if str(cid) == str(row[5])), "Неизвестный чат"),
            "message_id": row[0],
            "date": row[1],
            "from_id": row[2],
            "content": row[3] or "",
            "sender_name": row[4] or "Неизвестно"
        })
    
    # Переворачиваем для хронологического порядка
    messages.reverse()
    return messages

