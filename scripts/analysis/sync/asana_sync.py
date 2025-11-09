#!/usr/bin/env python3
"""
Модуль синхронизации задач между Telegram и Asana
Двусторонняя синхронизация: дополнение контекста и проверка покрытия
"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import re

# Добавляем корень проекта в путь
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.analysis.utils.gpt5_client import get_openai_client
from scripts.analysis.embeddings.embeddings import get_embedding, cosine_similarity_embedding


# Конфигурация Asana
ASANA_WORKSPACE_GID = "624391999090674"
ASANA_USER_GID = "1169547205416171"
ASANA_PROJECT_GID = "1210655252186716"  # Фарма+
ASANA_ESTIMATED_TIME_FIELD_GID = "1204112099563346"


class AsanaSync:
    """Класс для синхронизации задач между Telegram и Asana"""
    
    def __init__(self, mcp_client=None, openai_client=None):
        """
        Инициализация синхронизатора
        
        Args:
            mcp_client: Клиент MCP для работы с Asana API
            openai_client: Клиент OpenAI для семантического сравнения
        """
        self.mcp_client = mcp_client
        self.openai_client = openai_client or get_openai_client()
        self.workspace_gid = ASANA_WORKSPACE_GID
        self.project_gid = ASANA_PROJECT_GID
        
    def load_telegram_tasks(self, tasks_file: Path) -> List[Dict[str, Any]]:
        """Загрузить задачи из Telegram анализа"""
        with open(tasks_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('unique_tasks', [])
    
    def load_telegram_projects(self, projects_file: Path) -> List[Dict[str, Any]]:
        """Загрузить проекты из Telegram анализа"""
        with open(projects_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('projects', [])
    
    def normalize_text(self, text: str) -> str:
        """Нормализация текста для сравнения"""
        if not text:
            return ""
        # Приводим к нижнему регистру, убираем лишние пробелы
        text = text.lower().strip()
        # Убираем знаки препинания для более гибкого сравнения
        text = re.sub(r'[^\w\s]', ' ', text)
        # Убираем множественные пробелы
        text = re.sub(r'\s+', ' ', text)
        return text
    
    def calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Вычисление семантической схожести двух текстов через GPT-5
        Возвращает значение от 0 до 1
        """
        if not text1 or not text2:
            return 0.0
        
        prompt = f"""Сравни два текста и определи, насколько они похожи по смыслу (не по словам, а по содержанию).

Текст 1: {text1[:500]}
Текст 2: {text2[:500]}

Ответь одним числом от 0 до 1, где:
- 1.0 = это одна и та же задача/тема
- 0.8-0.9 = очень похожие задачи, но есть различия
- 0.6-0.7 = связанные задачи, но разные
- 0.3-0.5 = частично связаны
- 0.0-0.2 = разные задачи

Только число, без объяснений:"""
        
        try:
            response = self.openai_client.responses.create(
                model="gpt-5",
                input=[{"role": "user", "content": prompt}],
                reasoning={"effort": "low"}
            )
            
            # Извлекаем число из ответа
            if hasattr(response, 'output') and response.output:
                if isinstance(response.output, list) and len(response.output) > 0:
                    output_item = response.output[0]
                    if hasattr(output_item, 'content') and output_item.content:
                        if isinstance(output_item.content, list) and len(output_item.content) > 0:
                            content_item = output_item.content[0]
                            if hasattr(content_item, 'text'):
                                result_text = content_item.text.strip()
                            elif isinstance(content_item, dict) and 'text' in content_item:
                                result_text = content_item['text'].strip()
                            else:
                                result_text = str(content_item).strip()
                        else:
                            result_text = str(output_item.content).strip()
                    elif isinstance(output_item, dict):
                        if 'content' in output_item:
                            content = output_item['content']
                            if isinstance(content, list) and len(content) > 0:
                                if isinstance(content[0], dict) and 'text' in content[0]:
                                    result_text = content[0]['text'].strip()
                                else:
                                    result_text = str(content[0]).strip()
                            else:
                                result_text = str(content).strip()
                        else:
                            result_text = str(output_item).strip()
                    else:
                        result_text = str(output_item).strip()
                else:
                    result_text = str(response.output).strip()
            else:
                result_text = str(response).strip()
            
            # Ищем число в ответе
            match = re.search(r'0?\.\d+|1\.0|0|1', result_text)
            if match:
                similarity = float(match.group())
                return min(max(similarity, 0.0), 1.0)
            return 0.5  # По умолчанию средняя схожесть
        except Exception as e:
            # Fallback на простое сравнение по ключевым словам
            return self._simple_similarity(text1, text2)
    
    def _simple_similarity(self, text1: str, text2: str) -> float:
        """Простое сравнение по ключевым словам (fallback)"""
        words1 = set(self.normalize_text(text1).split())
        words2 = set(self.normalize_text(text2).split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union) if union else 0.0
    
    def find_matching_tasks(
        self, 
        telegram_tasks: List[Dict[str, Any]], 
        asana_tasks: List[Dict[str, Any]],
        similarity_threshold: float = 0.7,
        verbose: bool = True,
        max_asana_tasks: Optional[int] = None,
        use_embeddings: bool = True,
        use_gpt5_verification: bool = False  # Опциональная финальная проверка через GPT-5 (дорого!)
    ) -> Dict[str, List[Tuple[Dict, Dict, float]]]:
        """
        Найти совпадения между задачами из Telegram и Asana
        
        Args:
            telegram_tasks: Список задач из Telegram
            asana_tasks: Список задач из Asana
            similarity_threshold: Порог схожести (0.0-1.0) - для эмбеддингов обычно 0.7-0.8
            verbose: Выводить прогресс
            max_asana_tasks: Максимальное количество задач Asana для сравнения (для теста)
            use_embeddings: Использовать эмбеддинги для быстрого поиска (рекомендуется)
            use_gpt5_verification: Использовать GPT-5 для финальной проверки топ-кандидатов (дорого!)
        
        Returns:
            Dict с ключами:
            - 'matches': список (telegram_task, asana_task, similarity_score)
            - 'telegram_only': задачи только в Telegram
            - 'asana_only': задачи только в Asana
        """
        matches = []
        telegram_matched = set()
        asana_matched = set()
        
        # Ограничиваем количество задач Asana для теста
        if max_asana_tasks:
            asana_tasks = asana_tasks[:max_asana_tasks]
            if verbose:
                print(f"   ⚠️  Ограничение: сравниваем только с {max_asana_tasks} задачами Asana")
        
        if verbose:
            print(f"   📊 Всего задач: {len(telegram_tasks)} Telegram × {len(asana_tasks)} Asana")
        
        # Шаг 1: Создаем эмбеддинги для всех задач Asana (если используем эмбеддинги)
        if use_embeddings:
            if verbose:
                print(f"\n   🔢 Создание эмбеддингов для {len(asana_tasks)} задач Asana...")
            
            asana_embeddings = []
            asana_texts = []
            for idx, asana_task in enumerate(asana_tasks):
                asana_name = asana_task.get('name', '')
                asana_notes = asana_task.get('notes', '') or ''
                asana_text = f"{asana_name} {asana_notes}".strip()[:8000]
                asana_texts.append(asana_text)
                
                if verbose and (idx + 1) % 20 == 0:
                    print(f"      📝 Обработано {idx + 1}/{len(asana_tasks)}...", end='\r', flush=True)
            
            # Получаем эмбеддинги батчами
            try:
                if verbose:
                    print(f"      🔄 Получение эмбеддингов через API...")
                
                # OpenAI embeddings API поддерживает батчи до 2048 элементов
                batch_size = 100
                for i in range(0, len(asana_texts), batch_size):
                    batch_texts = asana_texts[i:i+batch_size]
                    batch_response = self.openai_client.embeddings.create(
                        model="text-embedding-3-small",
                        input=batch_texts
                    )
                    batch_embeddings = [item.embedding for item in batch_response.data]
                    asana_embeddings.extend(batch_embeddings)
                    
                    if verbose:
                        print(f"      ✅ Батч {i//batch_size + 1}/{(len(asana_texts)-1)//batch_size + 1} готов", end='\r', flush=True)
                
                if verbose:
                    print(f"\n      ✅ Эмбеддинги для Asana готовы ({len(asana_embeddings)} шт.)")
            except Exception as e:
                if verbose:
                    print(f"\n      ⚠️  Ошибка создания эмбеддингов: {e}, переключаемся на GPT-5")
                use_embeddings = False
        
        # Шаг 2: Сравниваем каждую задачу из Telegram с задачами Asana
        if verbose:
            print(f"\n   🔍 Поиск совпадений...")
            if use_embeddings:
                cost_info = "💰 Дешево (только эмбеддинги)"
                if use_gpt5_verification:
                    cost_info += " + GPT-5 проверка (дороже)"
                print(f"      ⚡ Используем эмбеддинги {cost_info}")
            else:
                print(f"      🐌 Используем GPT-5 для всех сравнений (медленно и дорого)")
        
        for tg_idx, tg_task in enumerate(telegram_tasks, 1):
            tg_title = tg_task.get('title', '')
            tg_desc = tg_task.get('description', '')
            tg_text = f"{tg_title} {tg_desc}".strip()[:8000]
            
            if verbose:
                print(f"\n   [{tg_idx}/{len(telegram_tasks)}] 📱 Telegram: {tg_title[:60]}...")
            
            best_match = None
            best_score = 0.0
            best_asana_idx = -1
            
            if use_embeddings:
                # Быстрый поиск через эмбеддинги (дешево!)
                try:
                    # Получаем эмбеддинг для задачи Telegram
                    tg_embedding = get_embedding(tg_text, client=self.openai_client)
                    if not tg_embedding:
                        if verbose:
                            print(f"      ⚠️  Не удалось получить эмбеддинг, пропускаем")
                        continue
                    
                    # Вычисляем схожесть со всеми задачами Asana
                    candidates = []
                    for idx, asana_embedding in enumerate(asana_embeddings):
                        if idx in asana_matched:
                            continue
                        
                        similarity = cosine_similarity_embedding(tg_embedding, asana_embedding)
                        candidates.append((idx, similarity))
                    
                    # Сортируем и берем лучшего кандидата
                    candidates.sort(key=lambda x: x[1], reverse=True)
                    
                    if candidates:
                        best_asana_idx, best_score = candidates[0]
                        best_match = asana_tasks[best_asana_idx]
                        
                        if verbose:
                            print(f"      🔢 Лучший кандидат через эмбеддинги: {best_score:.3f} → {best_match.get('name', '')[:50]}")
                        
                        # Опциональная финальная проверка через GPT-5 (если включена)
                        if use_gpt5_verification and best_score >= similarity_threshold:
                            asana_name = best_match.get('name', '')
                            asana_notes = best_match.get('notes', '') or ''
                            asana_text = f"{asana_name} {asana_notes}"
                            
                            try:
                                gpt5_score = self.calculate_similarity(tg_text, asana_text)
                                if verbose:
                                    print(f"         🔍 GPT-5 проверка: {best_score:.3f} → {gpt5_score:.2f}")
                                
                                # Используем GPT-5 оценку если она выше порога
                                if gpt5_score >= similarity_threshold:
                                    best_score = gpt5_score
                                else:
                                    # GPT-5 не подтвердил, сбрасываем
                                    best_match = None
                                    best_score = 0.0
                                    best_asana_idx = -1
                            except Exception as e:
                                if verbose:
                                    print(f"         ⚠️  Ошибка GPT-5 проверки: {e}, используем оценку эмбеддингов")
                    
                    # Проверяем порог схожести
                    if best_score < similarity_threshold:
                        best_match = None
                        best_score = 0.0
                        best_asana_idx = -1
                
                except Exception as e:
                    if verbose:
                        print(f"      ⚠️  Ошибка поиска через эмбеддинги: {e}, переключаемся на GPT-5")
                    use_embeddings = False
            
            # Fallback: полный перебор через GPT-5 (если эмбеддинги не работают)
            if not use_embeddings:
                # Если эмбеддинги отключены, используем GPT-5 для всех сравнений
                comparisons_done = 0
                for idx, asana_task in enumerate(asana_tasks):
                    if idx in asana_matched:
                        continue
                    
                    asana_name = asana_task.get('name', '')
                    asana_notes = asana_task.get('notes', '') or ''
                    asana_text = f"{asana_name} {asana_notes}"
                    
                    comparisons_done += 1
                    if verbose and comparisons_done % 10 == 0:
                        print(f"      🔍 Сравнение {comparisons_done}/{len(asana_tasks)}...", end='\r', flush=True)
                    
                    try:
                        score = self.calculate_similarity(tg_text, asana_text)
                        
                        if score > best_score and score >= similarity_threshold:
                            best_score = score
                            best_match = asana_task
                            best_asana_idx = idx
                    except Exception as e:
                        if verbose:
                            print(f"\n      ⚠️  Ошибка сравнения с задачей '{asana_name[:40]}': {e}")
                        continue
            
            if best_match:
                matches.append((tg_task, best_match, best_score))
                telegram_matched.add(tg_idx - 1)  # tg_idx начинается с 1, индекс с 0
                asana_matched.add(best_asana_idx)
                if verbose:
                    print(f"      ✅ Найдено совпадение! Score: {best_score:.2f} → {best_match.get('name', '')[:50]}")
            else:
                if verbose:
                    print(f"      ❌ Совпадений не найдено (порог: {similarity_threshold})")
        
        # Задачи только в Telegram
        telegram_only = [
            tg_task for idx, tg_task in enumerate(telegram_tasks)
            if idx not in telegram_matched
        ]
        
        # Задачи только в Asana
        asana_only = [
            asana_task for idx, asana_task in enumerate(asana_tasks)
            if idx not in asana_matched
        ]
        
        return {
            'matches': matches,
            'telegram_only': telegram_only,
            'asana_only': asana_only
        }
    
    def enrich_asana_task_with_telegram(
        self, 
        asana_task: Dict[str, Any], 
        telegram_task: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Дополнить задачу из Asana данными из Telegram
        
        Returns:
            Словарь с рекомендациями по обновлению
        """
        updates = {}
        
        asana_notes = asana_task.get('notes', '') or ''
        tg_desc = telegram_task.get('description', '')
        tg_context = telegram_task.get('context', '')
        
        # Если в Asana нет описания или оно короче, добавляем из Telegram
        if not asana_notes or len(asana_notes) < len(tg_desc):
            updates['notes'] = f"{asana_notes}\n\n--- Контекст из Telegram ---\n{tg_desc}\n\n{tg_context}".strip()
        
        # Проверяем статус
        tg_status = telegram_task.get('status', '')
        asana_completed = asana_task.get('completed', False)
        
        if tg_status == 'выполнено' and not asana_completed:
            updates['completed'] = True
        elif tg_status == 'не выполнено' and asana_completed:
            updates['completed'] = False
        
        # Проверяем дедлайн
        tg_deadline = telegram_task.get('deadline')
        asana_due_on = asana_task.get('due_on')
        
        if tg_deadline and not asana_due_on:
            # Парсим дедлайн из Telegram (может быть в разных форматах)
            updates['due_on'] = self._parse_deadline(tg_deadline)
        
        # Добавляем информацию о чатах и обсуждениях
        tg_chats = telegram_task.get('chats', [])
        tg_thread = telegram_task.get('discussion_thread', '')
        
        if tg_chats or tg_thread:
            context_note = "\n\n--- Источники обсуждения ---\n"
            if tg_chats:
                context_note += f"Чаты: {', '.join(tg_chats)}\n"
            if tg_thread:
                context_note += f"Тема обсуждения: {tg_thread}\n"
            
            if 'notes' not in updates:
                updates['notes'] = asana_notes
            updates['notes'] += context_note
        
        return updates
    
    def _parse_deadline(self, deadline_str: str) -> Optional[str]:
        """Парсинг дедлайна из строки в формат YYYY-MM-DD"""
        if not deadline_str:
            return None
        
        # Если уже в формате YYYY-MM-DD
        if re.match(r'\d{4}-\d{2}-\d{2}', deadline_str):
            return deadline_str
        
        # Пытаемся распарсить другие форматы
        # TODO: добавить более сложный парсинг дат
        return None
    
    def create_asana_task_from_telegram(
        self, 
        telegram_task: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Подготовить данные для создания задачи в Asana из Telegram задачи
        
        Returns:
            Словарь с данными для ASANA_CREATE_A_TASK
        """
        title = telegram_task.get('title', 'Без названия')
        description = telegram_task.get('description', '')
        context = telegram_task.get('context', '')
        
        # Формируем описание
        notes = f"{description}\n\n--- Контекст ---\n{context}"
        
        # Добавляем информацию о чатах
        chats = telegram_task.get('chats', [])
        thread = telegram_task.get('discussion_thread', '')
        
        if chats or thread:
            notes += "\n\n--- Источники ---\n"
            if chats:
                notes += f"Чаты: {', '.join(chats)}\n"
            if thread:
                notes += f"Тема: {thread}\n"
        
        task_data = {
            'name': title,
            'notes': notes,
            'assignee': ASANA_USER_GID,
            'projects': [ASANA_PROJECT_GID],
            'workspace': ASANA_WORKSPACE_GID
        }
        
        # Добавляем дедлайн если есть
        deadline = telegram_task.get('deadline')
        if deadline:
            parsed_deadline = self._parse_deadline(deadline)
            if parsed_deadline:
                task_data['due_on'] = parsed_deadline
        
        # Статус выполнения
        status = telegram_task.get('status', '')
        if status == 'выполнено':
            task_data['completed'] = True
        
        return task_data
    
    def generate_sync_report(
        self,
        matching_result: Dict[str, List],
        output_file: Path
    ):
        """Генерировать отчет о синхронизации"""
        report = {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total_telegram_tasks': len(matching_result['matches']) + len(matching_result['telegram_only']),
                'total_asana_tasks': len(matching_result['matches']) + len(matching_result['asana_only']),
                'matched_tasks': len(matching_result['matches']),
                'telegram_only': len(matching_result['telegram_only']),
                'asana_only': len(matching_result['asana_only'])
            },
            'matches': [
                {
                    'telegram_task': match[0],
                    'asana_task': {
                        'gid': match[1].get('gid'),
                        'name': match[1].get('name'),
                        'notes': match[1].get('notes', '')[:200] + '...' if len(match[1].get('notes', '')) > 200 else match[1].get('notes', '')
                    },
                    'similarity_score': match[2],
                    'recommended_updates': self.enrich_asana_task_with_telegram(match[1], match[0])
                }
                for match in matching_result['matches']
            ],
            'telegram_only': matching_result['telegram_only'],
            'asana_only': [
                {
                    'gid': task.get('gid'),
                    'name': task.get('name'),
                    'notes': task.get('notes', '')[:200] + '...' if len(task.get('notes', '')) > 200 else task.get('notes', '')
                }
                for task in matching_result['asana_only']
            ]
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        return report


def main():
    """Основная функция для запуска синхронизации"""
    project_root = Path(__file__).resolve().parent.parent.parent
    results_dir = project_root / "results" / "farma" / "extracted"
    sync_dir = project_root / "results" / "farma" / "sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    
    # Загружаем задачи из Telegram
    telegram_tasks_file = results_dir / "farma_tasks_extracted.json"
    telegram_projects_file = results_dir / "farma_projects_extracted.json"
    
    sync = AsanaSync()
    
    print("📥 Загрузка задач из Telegram...")
    telegram_tasks = sync.load_telegram_tasks(telegram_tasks_file)
    print(f"   Загружено {len(telegram_tasks)} задач из Telegram")
    
    # TODO: Загрузить задачи из Asana через MCP
    # Пока используем заглушку
    print("\n⚠️  ВНИМАНИЕ: Загрузка задач из Asana требует MCP клиента")
    print("   Для полной синхронизации используйте sync_with_mcp()")
    
    # Генерируем отчет о структуре задач из Telegram
    telegram_structure = {
        'total_tasks': len(telegram_tasks),
        'by_status': {},
        'by_assignee': {}
    }
    
    for task in telegram_tasks:
        status = task.get('status', 'неизвестно')
        assignee = task.get('assignee', 'не назначен')
        
        telegram_structure['by_status'][status] = telegram_structure['by_status'].get(status, 0) + 1
        telegram_structure['by_assignee'][assignee] = telegram_structure['by_assignee'].get(assignee, 0) + 1
    
    structure_file = sync_dir / "telegram_tasks_structure.json"
    with open(structure_file, 'w', encoding='utf-8') as f:
        json.dump(telegram_structure, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Структура задач сохранена: {structure_file}")
    print(f"\n📊 Статистика:")
    print(f"   Всего задач: {telegram_structure['total_tasks']}")
    print(f"   По статусам: {telegram_structure['by_status']}")
    print(f"   По ответственным: {telegram_structure['by_assignee']}")


if __name__ == "__main__":
    main()

