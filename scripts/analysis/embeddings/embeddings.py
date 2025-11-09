"""
Работа с эмбеддингами для семантического поиска
"""
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from ..utils.gpt5_client import get_openai_client


def get_embedding(text: str, model: str = "text-embedding-3-small", client=None) -> Optional[List[float]]:
    """
    Получает эмбеддинг для текста.
    Используется для семантического поиска и drill-down.
    
    Args:
        text: Текст для получения эмбеддинга
        model: Модель для эмбеддингов
        client: OpenAI клиент (если None, создается новый)
    
    Returns:
        Список чисел (эмбеддинг) или None при ошибке
    """
    if client is None:
        client = get_openai_client()
    
    try:
        response = client.embeddings.create(
            model=model,
            input=text[:8000]  # Ограничение для embeddings API
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"      ⚠ Ошибка при получении эмбеддинга: {e}")
        return None


def cosine_similarity_embedding(vec1: List[float], vec2: List[float]) -> float:
    """
    Вычисляет косинусное сходство между двумя векторами эмбеддингов.
    
    Args:
        vec1: Первый вектор эмбеддинга
        vec2: Второй вектор эмбеддинга
    
    Returns:
        Косинусное сходство (от -1 до 1)
    """
    try:
        import numpy as np
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))
    except ImportError:
        # Fallback без numpy
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (norm1 * norm2)


def save_embeddings_for_level(
    level: str, 
    items: List[Dict[str, Any]], 
    output_dir: Path,
    client=None,
    cache_hours: float = 3.0
):
    """
    Сохраняет эмбеддинги для элементов определенного уровня.
    Использует кеш, если файл существует и создан менее cache_hours часов назад.
    
    Args:
        level: 'raw_messages', 'compressed_chunks', 'summaries', 'tasks', 'projects'
        items: список словарей с полями 'text', 'id', 'metadata' и т.д.
        output_dir: Директория для сохранения эмбеддингов
        client: OpenAI клиент (если None, создается новый)
        cache_hours: Максимальное время хранения кеша в часах (по умолчанию 3 часа)
    """
    if client is None:
        client = get_openai_client()
    
    embeddings_file = output_dir / f"embeddings_{level}.json"
    
    # Проверяем кеш: если файл существует и создан менее cache_hours часов назад - используем его
    if embeddings_file.exists():
        file_age_hours = (time.time() - embeddings_file.stat().st_mtime) / 3600
        if file_age_hours < cache_hours:
            print(f"   ✅ Используем кеш эмбеддингов для уровня '{level}' (возраст: {file_age_hours:.1f} часов)")
            print(f"   💾 Файл: {embeddings_file}")
            return
    
    embeddings_data = []
    
    print(f"   📊 Сохранение эмбеддингов для уровня '{level}' ({len(items)} элементов)...")
    
    for i, item in enumerate(items, 1):
        text = item.get('text', '')
        if not text:
            continue
        
        # Получаем эмбеддинг
        embedding = get_embedding(text, client=client)
        if embedding:
            embeddings_data.append({
                'id': item.get('id', i),
                'text': text[:500],  # Сохраняем только начало для справки
                'embedding': embedding,
                'metadata': item.get('metadata', {})
            })
            if i % 10 == 0:
                print(f"      Обработано {i}/{len(items)}...", end='\r', flush=True)
    
    print(f"      ✓ Сохранено {len(embeddings_data)} эмбеддингов")
    
    # Сохраняем в файл
    if embeddings_data:
        with open(embeddings_file, "w", encoding="utf-8") as f:
            json.dump(embeddings_data, f, ensure_ascii=False, indent=2)
        print(f"   💾 Эмбеддинги сохранены: {embeddings_file}")


def find_relevant_sources_by_embedding(
    query_text: str,
    source_level: str,
    output_dir: Path,
    top_k: int = 5,
    similarity_threshold: float = 0.7,
    client=None
) -> List[Dict[str, Any]]:
    """
    Находит релевантные исходные элементы по семантической близости.
    Используется для drill-down: когда нужно найти исходные сообщения для задачи/проекта.
    
    Args:
        query_text: текст запроса (например, описание задачи)
        source_level: уровень источника ('raw_messages', 'compressed_chunks', 'summaries')
        output_dir: директория с файлами эмбеддингов
        top_k: количество результатов
        similarity_threshold: минимальный порог схожести
        client: OpenAI клиент (если None, создается новый)
    
    Returns:
        Список релевантных источников с информацией о схожести
    """
    if client is None:
        client = get_openai_client()
    
    embeddings_file = output_dir / f"embeddings_{source_level}.json"
    
    if not embeddings_file.exists():
        print(f"   ⚠ Файл эмбеддингов не найден: {embeddings_file}")
        return []
    
    # Загружаем эмбеддинги
    with open(embeddings_file, "r", encoding="utf-8") as f:
        source_embeddings = json.load(f)
    
    # Получаем эмбеддинг запроса
    query_embedding = get_embedding(query_text, client=client)
    if not query_embedding:
        return []
    
    # Вычисляем схожесть со всеми источниками
    similarities = []
    for source in source_embeddings:
        similarity = cosine_similarity_embedding(query_embedding, source['embedding'])
        if similarity >= similarity_threshold:
            similarities.append({
                'id': source['id'],
                'text': source['text'],
                'similarity': similarity,
                'metadata': source.get('metadata', {})
            })
    
    # Сортируем по схожести и берем top_k
    similarities.sort(key=lambda x: x['similarity'], reverse=True)
    return similarities[:top_k]

