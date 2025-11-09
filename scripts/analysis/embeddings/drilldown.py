"""
Drill-down функциональность для поиска исходных сообщений
"""
import sqlite3
from typing import List, Dict, Any
from .embeddings import find_relevant_sources_by_embedding
from ..utils.db import get_messages_by_ids, search_messages_by_keywords
from ..utils.gpt5_client import get_openai_client


def extract_keywords(text: str, max_keywords: int = 5) -> List[str]:
    """
    Извлекает ключевые слова из текста (упрощенная версия).
    
    Args:
        text: Текст для извлечения ключевых слов
        max_keywords: Максимальное количество ключевых слов
    
    Returns:
        Список ключевых слов
    """
    # Убираем стоп-слова и берем существительные/глаголы
    stop_words = {'и', 'в', 'на', 'с', 'по', 'для', 'от', 'до', 'что', 'как', 'это', 'быть', 'есть'}
    words = text.lower().split()
    keywords = [w for w in words if len(w) > 3 and w not in stop_words]
    return keywords[:max_keywords]


def drill_down_to_raw_messages(
    query_text: str,
    conn: sqlite3.Connection,
    output_dir,
    chat_ids: Dict[str, str],
    top_k: int = 10,
    client=None
) -> List[Dict[str, Any]]:
    """
    Drill-down: находит релевантные исходные сообщения для запроса.
    Использует эмбеддинги для семантического поиска.
    
    Args:
        query_text: Текст запроса для поиска
        conn: Подключение к базе данных
        output_dir: Директория с файлами эмбеддингов
        chat_ids: Словарь с ID чатов
        top_k: Количество результатов
        client: OpenAI клиент (если None, создается новый)
    
    Returns:
        Список релевантных исходных сообщений
    """
    if client is None:
        client = get_openai_client()
    
    print(f"\n   🔍 Drill-down: поиск исходных сообщений для запроса...")
    print(f"      Запрос: {query_text[:100]}...")
    
    # Сначала пробуем найти через эмбеддинги, если они есть
    relevant_sources = find_relevant_sources_by_embedding(
        query_text,
        'raw_messages',
        output_dir,
        top_k=top_k,
        client=client
    )
    
    if relevant_sources:
        print(f"      ✓ Найдено {len(relevant_sources)} релевантных источников через эмбеддинги")
        # Получаем полные сообщения по ID из метаданных
        message_ids = [s['metadata'].get('message_id') for s in relevant_sources if s['metadata'].get('message_id')]
        if message_ids:
            return get_messages_by_ids(conn, message_ids)
    
    # Fallback: поиск по ключевым словам и датам из метаданных
    print(f"      Поиск через ключевые слова...")
    keywords = extract_keywords(query_text)
    return search_messages_by_keywords(conn, chat_ids, keywords, limit=top_k)

