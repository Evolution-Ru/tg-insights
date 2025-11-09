"""
Модуль для суммаризации задач Asana через GPT-5 Batch API
Создает компактные версии задач с высокой концентрацией полезной информации
"""
import json
import sys
import time
import tempfile
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

# Добавляем корень проекта в путь
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.analysis.utils.gpt5_client import get_openai_client


class AsanaTaskSummarizer:
    """Класс для суммаризации задач Asana через Batch API"""
    
    def __init__(self, cache_dir: Optional[Path] = None, client=None):
        """
        Инициализация суммаризатора
        
        Args:
            cache_dir: Директория для кеша суммаризированных задач
            client: OpenAI клиент (если None, создается новый)
        """
        self.client = client or get_openai_client()
        self.cache_dir = cache_dir or Path(__file__).parent.parent.parent.parent / "cache" / "asana_summaries"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.summary_cache_file = self.cache_dir / "summaries_cache.json"
        self.summary_cache = self._load_summary_cache()
        
        # Статистика
        self.stats = {
            'cached': 0,
            'new': 0,
            'batch_submitted': 0
        }
    
    def _load_summary_cache(self) -> Dict[str, Dict[str, Any]]:
        """Загружает кеш суммаризированных задач"""
        if not self.summary_cache_file.exists():
            return {}
        
        try:
            with open(self.summary_cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"      ⚠️  Ошибка загрузки кеша суммаризаций: {e}")
            return {}
    
    def _save_summary_cache(self):
        """Сохраняет кеш суммаризированных задач"""
        try:
            with open(self.summary_cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.summary_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"      ⚠️  Ошибка сохранения кеша суммаризаций: {e}")
    
    def _get_task_hash(self, asana_task: Dict[str, Any]) -> str:
        """Вычисляет хеш задачи для кеширования"""
        # Используем gid + modified_at для определения изменений
        gid = asana_task.get('gid', '')
        modified_at = asana_task.get('modified_at', '')
        name = asana_task.get('name', '')
        notes = asana_task.get('notes', '') or ''
        
        # Хеш на основе ключевых полей
        content = f"{gid}|{modified_at}|{name}|{notes[:500]}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def _extract_task_metadata(self, asana_task: Dict[str, Any]) -> str:
        """Извлекает метаданные задачи в структурированном виде"""
        metadata_parts = []
        
        # Исполнитель
        assignee = asana_task.get('assignee')
        if assignee:
            if isinstance(assignee, dict):
                assignee_name = assignee.get('name', '')
            else:
                assignee_name = str(assignee)
            if assignee_name:
                metadata_parts.append(f"Исполнитель: {assignee_name}")
        
        # Даты
        created_at = asana_task.get('created_at')
        if created_at:
            metadata_parts.append(f"Создана: {created_at}")
        
        modified_at = asana_task.get('modified_at')
        if modified_at:
            metadata_parts.append(f"Изменена: {modified_at}")
        
        due_on = asana_task.get('due_on')
        if due_on:
            metadata_parts.append(f"Дедлайн: {due_on}")
        
        due_at = asana_task.get('due_at')
        if due_at:
            metadata_parts.append(f"Дедлайн (время): {due_at}")
        
        # Статус
        completed = asana_task.get('completed', False)
        if completed:
            metadata_parts.append("Статус: Завершена")
        else:
            metadata_parts.append("Статус: В работе")
        
        return " | ".join(metadata_parts)
    
    def _create_summarization_prompt(self, asana_task: Dict[str, Any]) -> str:
        """Создает промпт для суммаризации задачи"""
        name = asana_task.get('name', '')
        notes = asana_task.get('notes', '') or ''
        metadata = self._extract_task_metadata(asana_task)
        
        prompt = f"""Проанализируй задачу из Asana и создай компактную выжимку с высокой концентрацией полезной информации.

Требования к выжимке:
- Только сухие факты, без лишних слов
- Высокая концентрация полезной информации
- Низкое содержание бесполезного (убрать воду, повторы, приветствия)
- Сохранить ключевые технические детали
- Сохранить важные решения и результаты
- Убрать мелкие детали и уточнения

Название задачи: {name}

Метаданные: {metadata}

Описание и заметки:
{notes}

Выжимка (компактно, только факты):"""
        
        return prompt
    
    def summarize_tasks_batch(
        self,
        asana_tasks: List[Dict[str, Any]],
        verbose: bool = False
    ) -> Dict[str, str]:
        """
        Суммаризирует задачи Asana через Batch API
        
        Args:
            asana_tasks: Список задач Asana
            verbose: Выводить подробную информацию
            
        Returns:
            Словарь {task_gid: summarized_text}
        """
        if not asana_tasks:
            return {}
        
        # Проверяем кеш и собираем задачи для суммаризации
        tasks_to_summarize = []
        task_gid_to_hash = {}
        results = {}
        
        for task in asana_tasks:
            task_gid = task.get('gid', '')
            if not task_gid:
                continue
            
            task_hash = self._get_task_hash(task)
            task_gid_to_hash[task_gid] = task_hash
            
            # Проверяем кеш
            cache_key = f"{task_gid}_{task_hash}"
            if cache_key in self.summary_cache:
                cached_summary = self.summary_cache[cache_key]
                # Проверяем актуальность (если задача не изменилась)
                cached_hash = cached_summary.get('task_hash')
                if cached_hash == task_hash:
                    results[task_gid] = cached_summary['summary']
                    self.stats['cached'] += 1
                    if verbose:
                        print(f"      ✓ Кеш: {task_gid[:12]}...")
                    continue
            
            # Добавляем в список для суммаризации
            tasks_to_summarize.append(task)
            self.stats['new'] += 1
        
        if not tasks_to_summarize:
            if verbose:
                print(f"      ✅ Все задачи из кеша ({len(results)}/{len(asana_tasks)})")
                print(f"      📊 Статистика: кеш={self.stats['cached']}, новых={self.stats['new']}, батчей={self.stats['batch_submitted']}")
            # Сохраняем кеш даже если все задачи из кеша (для консистентности)
            self._save_summary_cache()
            return results
        
        if verbose:
            print(f"      📝 Суммаризация {len(tasks_to_summarize)} задач через Batch API...")
        
        # Создаем JSONL файл для batch API
        temp_jsonl = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False, encoding='utf-8')
        
        system_prompt = "Ты помогаешь создавать компактные выжимки задач из Asana с высокой концентрацией полезной информации."
        
        for task in tasks_to_summarize:
            task_gid = task.get('gid', '')
            user_prompt = self._create_summarization_prompt(task)
            
            request_data = {
                "custom_id": f"asana_task_{task_gid}",
                "method": "POST",
                "url": "/v1/responses",
                "body": {
                    "model": "gpt-5",
                    "input": [
                        {
                            "role": "system",
                            "content": system_prompt
                        },
                        {
                            "role": "user",
                            "content": user_prompt
                        }
                    ],
                    "reasoning": {"effort": "low"}
                }
            }
            
            temp_jsonl.write(json.dumps(request_data, ensure_ascii=False) + '\n')
        
        temp_jsonl.close()
        jsonl_path = Path(temp_jsonl.name)
        
        # Загружаем файл в OpenAI
        if verbose:
            print(f"      📤 Загрузка файла в OpenAI...")
        with open(jsonl_path, 'rb') as f:
            uploaded_file = self.client.files.create(
                file=f,
                purpose="batch"
            )
        
        # Создаем батч
        if verbose:
            print(f"      📦 Создание батча...")
        batch = self.client.batches.create(
            input_file_id=uploaded_file.id,
            endpoint="/v1/responses",
            completion_window="24h"
        )
        batch_id = batch.id
        self.stats['batch_submitted'] += 1
        
        if verbose:
            print(f"      ✓ Батч создан: {batch_id}")
            print(f"      ⏳ Ожидание завершения батча...")
        
        # Дожидаемся завершения батча
        max_wait_time = 3600  # Максимум 1 час
        start_time = time.time()
        poll_interval = 10  # Проверяем каждые 10 секунд
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait_time:
                raise Exception(f"Батч не завершился за {max_wait_time} секунд")
            
            batch_status = self.client.batches.retrieve(batch_id)
            status = batch_status.status
            
            if status == "completed":
                if verbose:
                    print(f"      ✓ Батч завершен!")
                break
            elif status == "failed":
                raise Exception(f"Батч завершился с ошибкой: {batch_status}")
            elif status in ["cancelled", "expired"]:
                raise Exception(f"Батч был отменен или истек: {status}")
            
            if verbose:
                print(f"      → Статус: {status} (прошло {elapsed:.0f} сек)...", end='\r', flush=True)
            time.sleep(poll_interval)
        
        # Скачиваем результаты
        if verbose:
            print(f"      📥 Скачивание результатов...")
        output_file_id = batch_status.output_file_id
        if not output_file_id:
            # Сохраняем кеш перед ошибкой
            self._save_summary_cache()
            raise Exception("Нет output_file_id в завершенном батче")
        
        output_file = self.client.files.content(output_file_id)
        output_content = output_file.read().decode('utf-8')
        
        # Парсим результаты
        if verbose:
            print(f"      🔍 Парсинг результатов...")
        
        try:
            for line in output_content.strip().split('\n'):
                if not line:
                    continue
                
                try:
                    result_data = json.loads(line)
                    custom_id = result_data.get('custom_id', '')
                    
                    if not custom_id.startswith('asana_task_'):
                        continue
                    
                    task_gid = custom_id.replace('asana_task_', '')
                    
                    # Извлекаем суммаризированный текст из ответа
                    response_body = result_data.get('response', {}).get('body', {})
                    summary_text = ""
                    
                    # Парсим ответ responses API
                    if 'output_text' in response_body:
                        summary_text = response_body['output_text']
                    elif 'output' in response_body:
                        output = response_body['output']
                        if isinstance(output, str):
                            summary_text = output
                        elif isinstance(output, list):
                            chunks = []
                            for item in output:
                                if isinstance(item, dict):
                                    if 'text' in item:
                                        chunks.append(item['text'])
                                    elif 'content' in item:
                                        for c in item.get('content', []):
                                            if isinstance(c, dict) and 'text' in c:
                                                chunks.append(c['text'])
                                elif hasattr(item, 'text'):
                                    chunks.append(item.text)
                            summary_text = '\n'.join(chunks)
                    
                    if not summary_text:
                        if 'error' in result_data.get('response', {}):
                            error_info = result_data['response']['error']
                            if verbose:
                                print(f"      ⚠️  Ошибка для {task_gid}: {error_info}")
                            continue
                        # Fallback: используем название задачи
                        for task in tasks_to_summarize:
                            if task.get('gid') == task_gid:
                                summary_text = task.get('name', '')
                                break
                    
                    # Сохраняем результат
                    task_hash = task_gid_to_hash.get(task_gid, '')
                    cache_key = f"{task_gid}_{task_hash}"
                    
                    results[task_gid] = summary_text.strip()
                    
                    # Сохраняем в кеш
                    self.summary_cache[cache_key] = {
                        'task_gid': task_gid,
                        'task_hash': task_hash,
                        'summary': summary_text.strip(),
                        'created_at': time.time(),
                        'created_at_iso': datetime.now().isoformat()
                    }
                    
                    # Инкрементальное сохранение кеша (каждые 5 задач) для защиты от потери данных
                    if len(results) % 5 == 0:
                        self._save_summary_cache()
                        if verbose:
                            print(f"      💾 Кеш сохранен (обработано {len(results)} задач)")
                    
                    if verbose:
                        print(f"      ✓ Обработана {task_gid[:12]}... ({len(summary_text)} символов)")
                
                except Exception as e:
                    if verbose:
                        print(f"      ⚠️  Ошибка парсинга результата: {e}")
                    continue
        
        finally:
            # Гарантированно сохраняем кеш даже при ошибках
            self._save_summary_cache()
            if verbose and len(results) > 0:
                print(f"      💾 Кеш сохранен (финальное сохранение)")
        
        # Удаляем временный файл
        try:
            jsonl_path.unlink()
        except:
            pass
        
        if verbose:
            print(f"      ✅ Обработано {len(results)}/{len(asana_tasks)} задач")
            print(f"      📊 Статистика: кеш={self.stats['cached']}, новых={self.stats['new']}, батчей={self.stats['batch_submitted']}")
        
        return results
    
    def get_summary(self, asana_task: Dict[str, Any]) -> Optional[str]:
        """
        Получить суммаризированную версию задачи (из кеша или создать новую)
        
        Args:
            asana_task: Задача из Asana
            
        Returns:
            Суммаризированный текст или None
        """
        task_gid = asana_task.get('gid', '')
        if not task_gid:
            return None
        
        task_hash = self._get_task_hash(asana_task)
        cache_key = f"{task_gid}_{task_hash}"
        
        if cache_key in self.summary_cache:
            cached_summary = self.summary_cache[cache_key]
            cached_hash = cached_summary.get('task_hash')
            if cached_hash == task_hash:
                return cached_summary['summary']
        
        # Если нет в кеше, нужно вызвать summarize_tasks_batch
        return None

