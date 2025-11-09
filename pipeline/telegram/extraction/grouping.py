"""
Группировка и дедупликация задач
"""
from typing import List, Dict, Any
from shared.ai.gpt5_client import get_openai_client
from pipeline.telegram.vectorization.embeddings import cosine_similarity_embedding


def find_similar_tasks(tasks: List[Dict[str, Any]], similarity_threshold: float = 0.85, client=None) -> Dict[int, List[int]]:
    """
    Находит похожие задачи используя OpenAI embeddings.
    Возвращает словарь: {task_index: [список индексов похожих задач]}
    
    Args:
        tasks: Список задач для сравнения
        similarity_threshold: Порог схожести (0-1)
        client: OpenAI клиент (если None, создается новый)
    
    Returns:
        Словарь с группами похожих задач
    """
    if client is None:
        client = get_openai_client()
    
    if len(tasks) < 2:
        return {}
    
    print(f"\n🔗 Поиск связанных задач среди {len(tasks)} задач...")
    
    try:
        # Создаем текстовые представления задач для сравнения
        task_texts = []
        for task in tasks:
            # Комбинируем название и описание для лучшего поиска
            text = f"{task.get('title', '')} {task.get('description', '')}"
            # Убираем лишние пробелы и ограничиваем длину
            text = ' '.join(text.split()[:50])  # Первые 50 слов
            task_texts.append(text)
        
        # Получаем embeddings для всех задач
        print(f"   Получение embeddings для {len(task_texts)} задач...", end=" ", flush=True)
        embeddings_response = client.embeddings.create(
            model="text-embedding-3-small",
            input=task_texts
        )
        embeddings = [item.embedding for item in embeddings_response.data]
        print(f"✓ получено {len(embeddings)} embeddings")
        
        # Вычисляем косинусное сходство между всеми парами задач
        similar_groups = {}
        processed = set()
        
        for i in range(len(tasks)):
            if i in processed:
                continue
            
            similar_to_i = [i]
            
            for j in range(i + 1, len(tasks)):
                if j in processed:
                    continue
                
                similarity = cosine_similarity_embedding(embeddings[i], embeddings[j])
                
                if similarity >= similarity_threshold:
                    similar_to_i.append(j)
                    processed.add(j)
            
            if len(similar_to_i) > 1:
                similar_groups[i] = similar_to_i
                processed.add(i)
        
        print(f"   Найдено {len(similar_groups)} групп связанных задач")
        return similar_groups
        
    except Exception as e:
        print(f"⚠ Ошибка при поиске похожих задач: {e}")
        return {}


def group_and_deduplicate_tasks(all_tasks: List[Dict[str, Any]], similarity_threshold: float = 0.85, client=None) -> Dict[str, Any]:
    """
    Группирует задачи и находит связи между задачами из разных чатов.
    Возвращает словарь с группированными задачами и статистикой.
    
    Args:
        all_tasks: Список всех извлеченных задач
        similarity_threshold: Порог схожести для группировки
        client: OpenAI клиент (если None, создается новый)
    
    Returns:
        Словарь с группированными задачами и статистикой
    """
    if client is None:
        client = get_openai_client()
    
    print(f"\n📊 Анализ {len(all_tasks)} извлеченных задач...")
    
    # Находим похожие задачи
    similar_groups = find_similar_tasks(all_tasks, similarity_threshold, client)
    
    # Создаем структуру результата
    result = {
        "total_tasks": len(all_tasks),
        "unique_tasks": [],
        "duplicate_groups": [],
        "tasks_by_chat": {},
        "tasks_by_status": {}
    }
    
    # Группируем по чатам (поддерживаем и старую и новую структуру)
    for task in all_tasks:
        # Новая структура: chats - массив, старая: chat_name - строка
        chats = task.get('chats', [])
        if not chats and task.get('chat_name'):
            chats = [task.get('chat_name')]
        if not chats:
            chats = ['Неизвестно']
        
        for chat in chats:
            if chat not in result["tasks_by_chat"]:
                result["tasks_by_chat"][chat] = []
            result["tasks_by_chat"][chat].append(task)
    
    # Группируем по статусу
    for task in all_tasks:
        status = task.get('status', 'неизвестно')
        if status not in result["tasks_by_status"]:
            result["tasks_by_status"][status] = []
        result["tasks_by_status"][status].append(task)
    
    # Обрабатываем группы похожих задач
    processed_indices = set()
    for main_idx, similar_indices in similar_groups.items():
        if main_idx in processed_indices:
            continue
        
        # Создаем группу дубликатов
        # Собираем все чаты из задач (поддерживаем обе структуры)
        all_chats_in_group = set()
        for idx in similar_indices:
            task = all_tasks[idx]
            chats = task.get('chats', [])
            if not chats and task.get('chat_name'):
                chats = [task.get('chat_name')]
            all_chats_in_group.update(chats)
        
        group = {
            "main_task": all_tasks[main_idx],
            "related_tasks": [all_tasks[idx] for idx in similar_indices if idx != main_idx],
            "total_occurrences": len(similar_indices),
            "chats": list(all_chats_in_group) if all_chats_in_group else ['Неизвестно']
        }
        
        result["duplicate_groups"].append(group)
        
        # Добавляем основную задачу в unique_tasks
        main_task = all_tasks[main_idx].copy()
        main_task["related_chats"] = group["chats"]
        main_task["total_mentions"] = len(similar_indices)
        result["unique_tasks"].append(main_task)
        
        # Помечаем все задачи в группе как обработанные
        processed_indices.update(similar_indices)
    
    # Добавляем задачи, которые не были сгруппированы
    for i, task in enumerate(all_tasks):
        if i not in processed_indices:
            result["unique_tasks"].append(task)
    
    print(f"   Уникальных задач: {len(result['unique_tasks'])}")
    print(f"   Групп дубликатов: {len(result['duplicate_groups'])}")
    
    return result

