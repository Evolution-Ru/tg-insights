#!/usr/bin/env python3
"""
Модуль синхронизации задач между Telegram и Asana
Двусторонняя синхронизация: дополнение контекста и проверка покрытия
"""
import json
import sys
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# Добавляем корень проекта в путь
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.analysis.utils.gpt5_client import get_openai_client
from scripts.analysis.embeddings.embeddings import get_embedding, cosine_similarity_embedding
from ..utils.matchers.time_window import TimeWindowMatcher
from ..utils.cache.embedding_cache import EmbeddingCache
from ..utils.extractors.asana_summarizer import AsanaTaskSummarizer
from ..utils.extractors.context_extractor import AsanaContextExtractor, normalize_text
from ..utils.transformers.task_transformer import enrich_asana_task_with_telegram, create_asana_task_from_telegram
from ..utils.reporting.report_generator import analyze_coverage, generate_sync_report
from ..utils.matchers.similarity_calculator import calculate_similarity_gpt5
from ..utils.loaders.data_loader import load_telegram_tasks, load_telegram_projects


# Конфигурация Asana
ASANA_WORKSPACE_GID = "624391999090674"
ASANA_USER_GID = "1169547205416171"
ASANA_PROJECT_GID = "1210655252186716"  # Фарма+
ASANA_ESTIMATED_TIME_FIELD_GID = "1204112099563346"


class AsanaSync:
    """Класс для синхронизации задач между Telegram и Asana"""
    
    def __init__(self, mcp_client=None, openai_client=None, use_time_windows: bool = True, use_embedding_cache: bool = True, use_task_summarization: bool = True):
        """
        Инициализация синхронизатора
        
        Args:
            mcp_client: Клиент MCP для работы с Asana API
            openai_client: Клиент OpenAI для семантического сравнения
            use_time_windows: Использовать временные окна для фильтрации задач
            use_embedding_cache: Использовать кеш эмбеддингов
            use_task_summarization: Использовать предварительную суммаризацию задач через GPT-5
        """
        self.mcp_client = mcp_client
        self.openai_client = openai_client or get_openai_client()
        self.workspace_gid = ASANA_WORKSPACE_GID
        self.project_gid = ASANA_PROJECT_GID
        self.use_time_windows = use_time_windows
        self.time_window_matcher = TimeWindowMatcher() if use_time_windows else None
        self.embedding_cache = EmbeddingCache(use_local_cache=use_embedding_cache) if use_embedding_cache else None
        self.use_task_summarization = use_task_summarization
        self.task_summarizer = AsanaTaskSummarizer(client=self.openai_client) if use_task_summarization else None
        # Кеш суммаризированных задач для текущей сессии
        self._summarized_tasks_cache = {}
        # Инициализируем экстрактор контекста
        self.context_extractor = AsanaContextExtractor(
            task_summarizer=self.task_summarizer,
            summarized_tasks_cache=self._summarized_tasks_cache
        )
        
    def load_telegram_tasks(self, tasks_file: Path) -> List[Dict[str, Any]]:
        """Загрузить задачи из Telegram анализа (делегирует в data_loader)"""
        return load_telegram_tasks(tasks_file)
    
    def load_telegram_projects(self, projects_file: Path) -> List[Dict[str, Any]]:
        """Загрузить проекты из Telegram анализа (делегирует в data_loader)"""
        return load_telegram_projects(projects_file)
    
    def normalize_text(self, text: str) -> str:
        """Нормализация текста для сравнения (делегирует в context_extractor)"""
        return normalize_text(text)
    
    def extract_asana_task_context(self, asana_task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Извлечь контекстную выжимку из задачи Asana (делегирует в context_extractor)
        """
        return self.context_extractor.extract_asana_task_context(asana_task)
    
    def create_asana_task_summary(self, asana_task: Dict[str, Any], use_gpt5: bool = False) -> str:
        """Создать краткую выжимку задачи Asana (делегирует в context_extractor)"""
        return self.context_extractor.create_asana_task_summary(
            asana_task, 
            openai_client=self.openai_client if use_gpt5 else None,
            use_gpt5=use_gpt5
        )
    
    def calculate_similarity(self, text1: str, text2: str, verbose: bool = False) -> float:
        """Вычисление семантической схожести через GPT-5 (делегирует в similarity_calculator)"""
        return calculate_similarity_gpt5(text1, text2, self.openai_client, verbose)
    
    def find_matching_tasks(
        self, 
        telegram_tasks: List[Dict[str, Any]], 
        asana_tasks: List[Dict[str, Any]],
        similarity_threshold: float = 0.7,
        verbose: bool = True,
        max_asana_tasks: Optional[int] = None,
        use_embeddings: bool = True,
        use_gpt5_verification: bool = False,  # Опциональная финальная проверка через GPT-5 (дорого!)
        low_threshold: float = 0.65,  # Низкий порог для потенциальных совпадений
        use_two_stage_matching: bool = True  # Двухэтапное совпадение: низкий порог + GPT-5 проверка
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
            low_threshold: Низкий порог для потенциальных совпадений (по умолчанию 0.65)
            use_two_stage_matching: Двухэтапное совпадение - если score между low_threshold и similarity_threshold, 
                                   отправляется на GPT-5 проверку (по умолчанию True)
        
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
        quota_exceeded_during_embeddings = False  # Инициализируем переменную перед использованием
        if use_embeddings:
            if verbose:
                print(f"\n   🔢 Создание эмбеддингов для {len(asana_tasks)} задач Asana...")
            
            asana_embeddings = []
            asana_texts = []
            asana_contexts = []  # Сохраняем контекстные выжимки для анализа
            
            for idx, asana_task in enumerate(asana_tasks):
                # Извлекаем контекстную выжимку
                context = self.extract_asana_task_context(asana_task)
                asana_contexts.append(context)
                
                # Для эмбеддингов используем компактную версию (лучше качество сопоставления)
                asana_text = context.get('embedding_text', context['full_text'])[:8000]
                asana_texts.append(asana_text)
                
                if verbose and (idx + 1) % 20 == 0:
                    print(f"      📝 Обработано {idx + 1}/{len(asana_tasks)}...", end='\r', flush=True)
            
            # Получаем эмбеддинги батчами
            try:
                if verbose:
                    print(f"      🔄 Получение эмбеддингов через API...")
                
                # Проверяем, что все тексты валидны (не пустые)
                # Для пустых текстов используем минимальную заглушку
                processed_texts = []
                for text in asana_texts:
                    if text and text.strip():
                        processed_texts.append(text[:8000])  # Ограничиваем длину
                    else:
                        # Для пустых задач используем минимальную заглушку
                        processed_texts.append("empty")
                
                # OpenAI embeddings API поддерживает батчи до 2048 элементов
                batch_size = 100
                for i in range(0, len(processed_texts), batch_size):
                    batch_texts = processed_texts[i:i+batch_size]
                    
                    # Фильтруем пустые строки перед отправкой в API
                    batch_texts_filtered = []
                    batch_indices = []  # Индексы валидных текстов в батче
                    for j, text in enumerate(batch_texts):
                        if text and text.strip() and text != "empty":
                            batch_texts_filtered.append(text)
                            batch_indices.append(j)
                    
                    if not batch_texts_filtered:
                        # Если весь батч пустой, добавляем нулевые эмбеддинги
                        for _ in batch_texts:
                            asana_embeddings.append([0.0] * 1536)  # Размерность text-embedding-3-small
                    else:
                        try:
                            batch_response = self.openai_client.embeddings.create(
                                model="text-embedding-3-small",
                                input=batch_texts_filtered
                            )
                            batch_embeddings = [item.embedding for item in batch_response.data]
                            
                            # Заполняем эмбеддинги с учетом пустых текстов
                            embedding_idx = 0
                            for j in range(len(batch_texts)):
                                if j in batch_indices:
                                    asana_embeddings.append(batch_embeddings[embedding_idx])
                                    embedding_idx += 1
                                else:
                                    # Для пустых задач создаем нулевой эмбеддинг
                                    asana_embeddings.append([0.0] * 1536)
                        except Exception as e:
                            error_str = str(e)
                            error_type = type(e).__name__
                            # Детальное логирование ошибки
                            if verbose:
                                print(f"\n      ⚠️  Ошибка создания эмбеддингов (батч {i//batch_size + 1}):")
                                print(f"         Тип: {error_type}")
                                print(f"         Сообщение: {error_str[:200]}")
                            
                            # Проверяем на превышение квоты
                            if '429' in error_str or 'insufficient_quota' in error_str or 'quota' in error_str.lower() or 'rate_limit' in error_str.lower():
                                if verbose:
                                    print(f"\n      ❌ ПРЕВЫШЕНА КВОТА OpenAI! Невозможно создать эмбеддинги.")
                                    print(f"      💡 Решение: пополните баланс OpenAI или используйте предварительную проверку на точные совпадения")
                                use_embeddings = False
                                quota_exceeded_during_embeddings = True
                                break  # Выходим из цикла создания эмбеддингов
                            else:
                                if verbose:
                                    print(f"      ⚠️  Неизвестная ошибка, пробрасываем наверх")
                                raise  # Пробрасываем другие ошибки наверх
                    
                    if quota_exceeded_during_embeddings:
                        break
                    
                    if verbose:
                        print(f"      ✅ Батч {i//batch_size + 1}/{(len(processed_texts)-1)//batch_size + 1} готов", end='\r', flush=True)
                
                if verbose and not quota_exceeded_during_embeddings:
                    print(f"\n      ✅ Эмбеддинги для Asana готовы ({len(asana_embeddings)} шт.)")
            except Exception as e:
                error_str = str(e)
                error_type = type(e).__name__
                # Детальное логирование ошибки верхнего уровня
                if verbose:
                    print(f"\n      ⚠️  Ошибка создания эмбеддингов (верхний уровень):")
                    print(f"         Тип: {error_type}")
                    print(f"         Сообщение: {error_str[:300]}")
                    import traceback
                    print(f"         Traceback: {traceback.format_exc()[:500]}")
                
                # Проверяем на превышение квоты (если ошибка не была обработана внутри цикла)
                if '429' in error_str or 'insufficient_quota' in error_str or 'quota' in error_str.lower() or 'rate_limit' in error_str.lower():
                    if verbose:
                        print(f"\n      ❌ ПРЕВЫШЕНА КВОТА OpenAI! Невозможно создать эмбеддинги.")
                        print(f"      💡 Решение: пополните баланс OpenAI или используйте предварительную проверку на точные совпадения")
                    use_embeddings = False
                    quota_exceeded_during_embeddings = True
                else:
                    if verbose:
                        print(f"\n      ⚠️  Ошибка создания эмбеддингов: {e}, переключаемся на GPT-5")
                        import traceback
                        traceback.print_exc()
                    use_embeddings = False
        
        # Проверяем, была ли ошибка квоты
        quota_exceeded = False
        if not use_embeddings:
            # Проверяем, была ли ошибка квоты при создании эмбеддингов
            if 'quota_exceeded_during_embeddings' in locals() and quota_exceeded_during_embeddings:
                quota_exceeded = True
            else:
                # Пробуем один тестовый запрос к GPT-5 для проверки квоты
                try:
                    test_response = self.openai_client.responses.create(
                        model="gpt-5",
                        input=[{"role": "user", "content": "test"}],
                        reasoning={"effort": "low"}
                    )
                except Exception as e:
                    error_str = str(e)
                    if '429' in error_str or 'insufficient_quota' in error_str or 'quota' in error_str.lower():
                        quota_exceeded = True
                        if verbose:
                            print(f"\n   ❌ ПРЕВЫШЕНА КВОТА OpenAI! Работа невозможна.")
                            print(f"   💡 Решение: пополните баланс OpenAI")
                            print(f"   ✅ Используем только предварительную проверку на точные совпадения названий (без API)")
        
        # Шаг 2: Сравниваем каждую задачу из Telegram с задачами Asana
        if verbose:
            print(f"\n   🔍 Поиск совпадений...")
            if quota_exceeded:
                print(f"      ⚠️  Режим без API: только точные совпадения названий")
            elif use_embeddings:
                cost_info = "💰 Дешево (только эмбеддинги)"
                if use_gpt5_verification:
                    cost_info += " + GPT-5 проверка (дороже)"
                print(f"      ⚡ Используем эмбеддинги {cost_info}")
            else:
                print(f"      🐌 Используем GPT-5 для всех сравнений (медленно и дорого)")
        
        for tg_idx, tg_task in enumerate(telegram_tasks, 1):
            tg_title = tg_task.get('title', '')
            tg_desc = tg_task.get('description', '')
            tg_context = tg_task.get('context', '')
            # Для эмбеддингов используем компактную версию:
            # title + description + первые 1500 символов context (важнее начало)
            # Это улучшает качество, так как эмбеддинги усредняют информацию
            tg_context_compact = tg_context[:1500] if tg_context else ''
            tg_text = f"{tg_title} {tg_desc} {tg_context_compact}".strip()[:8000]
            
            if verbose:
                print(f"\n   [{tg_idx}/{len(telegram_tasks)}] 📱 Telegram: {tg_title[:60]}...")
            
            best_match = None
            best_score = 0.0
            best_asana_idx = -1
            
            # ПРЕДВАРИТЕЛЬНАЯ ПРОВЕРКА: точное/частичное совпадение названий (быстро и точно!)
            tg_title_normalized = self.normalize_text(tg_title)
            exact_match_found = False
            
            for idx, asana_task in enumerate(asana_tasks):
                if idx in asana_matched:
                    continue
                
                asana_name = asana_task.get('name', '')
                asana_name_normalized = self.normalize_text(asana_name)
                
                # Точное совпадение названий
                if tg_title_normalized == asana_name_normalized:
                    best_match = asana_task
                    best_score = 1.0
                    best_asana_idx = idx
                    exact_match_found = True
                    if verbose:
                        print(f"      ✅ ТОЧНОЕ СОВПАДЕНИЕ НАЗВАНИЙ! Score: 1.00 → {asana_name[:50]}")
                    break
                
                # Частичное совпадение: одно название содержит другое
                if tg_title_normalized in asana_name_normalized or asana_name_normalized in tg_title_normalized:
                    # Вычисляем процент совпадения
                    shorter = min(len(tg_title_normalized), len(asana_name_normalized))
                    longer = max(len(tg_title_normalized), len(asana_name_normalized))
                    if shorter > 0:
                        partial_score = shorter / longer
                        if partial_score > 0.7:  # Минимум 70% совпадения
                            if partial_score > best_score:
                                best_match = asana_task
                                best_score = partial_score
                                best_asana_idx = idx
                                exact_match_found = True
                                if verbose:
                                    print(f"      ✅ ЧАСТИЧНОЕ СОВПАДЕНИЕ НАЗВАНИЙ! Score: {partial_score:.2f} → {asana_name[:50]}")
            
            # Если нашли точное совпадение, пропускаем эмбеддинги
            if exact_match_found and best_score >= similarity_threshold:
                matches.append((tg_task, best_match, best_score))
                telegram_matched.add(tg_idx - 1)
                asana_matched.add(best_asana_idx)
                if verbose:
                    print(f"      ✅ Найдено совпадение! Score: {best_score:.2f} → {best_match.get('name', '')[:50]}")
                continue
            
            # Если превышена квота, используем только предварительную проверку
            if quota_exceeded:
                if verbose and not exact_match_found:
                    print(f"      ⚠️  Квота превышена, совпадений не найдено (используется только проверка названий)")
                continue
            
            # Если не нашли точное совпадение, используем эмбеддинги
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
                        candidate_idx, candidate_score = candidates[0]
                        candidate_task = asana_tasks[candidate_idx]
                        
                        # Если эмбеддинг дал лучший результат, чем предварительная проверка, используем его
                        if candidate_score > best_score:
                            best_asana_idx = candidate_idx
                            best_score = candidate_score
                            best_match = candidate_task
                            
                            if verbose:
                                print(f"      🔢 Лучший кандидат через эмбеддинги: {best_score:.3f} → {best_match.get('name', '')[:50]}")
                        elif verbose and best_score > 0:
                            print(f"      🔢 Эмбеддинги: {candidate_score:.3f} (уже есть лучшее совпадение: {best_score:.3f})")
                        
                        # Двухэтапное совпадение: если score между low_threshold и similarity_threshold
                        needs_gpt5_check = False
                        if use_two_stage_matching and low_threshold <= best_score < similarity_threshold:
                            needs_gpt5_check = True
                            if verbose:
                                print(f"         ⚠️  Потенциальное совпадение (score {best_score:.3f} < порога {similarity_threshold}), требуется GPT-5 проверка")
                        
                        # Опциональная финальная проверка через GPT-5
                        # Для GPT-5 используем полный текст для лучшего понимания контекста
                        if best_match and ((use_gpt5_verification and best_score >= similarity_threshold) or needs_gpt5_check):
                            # Используем полный текст из context для GPT-5
                            best_match_context = self.extract_asana_task_context(best_match)
                            asana_text_full = best_match_context['full_text']
                            
                            # Для Telegram также используем полный context при GPT-5 проверке
                            tg_text_full = f"{tg_title} {tg_desc} {tg_context}".strip()[:8000]
                            
                            try:
                                gpt5_score = self.calculate_similarity(tg_text_full, asana_text_full, verbose=verbose)
                                if verbose:
                                    if needs_gpt5_check:
                                        print(f"         🔍 GPT-5 проверка потенциального совпадения: {best_score:.3f} → {gpt5_score:.2f}")
                                    else:
                                        print(f"         🔍 GPT-5 проверка: {best_score:.3f} → {gpt5_score:.2f}")
                                
                                # Используем GPT-5 оценку если она выше порога
                                if gpt5_score >= similarity_threshold:
                                    best_score = gpt5_score
                                    if verbose and needs_gpt5_check:
                                        print(f"         ✅ GPT-5 подтвердил совпадение!")
                                else:
                                    # GPT-5 не подтвердил, но если было точное совпадение названий, оставляем его
                                    if exact_match_found:
                                        if verbose:
                                            print(f"         ⚠️  GPT-5 не подтвердил, но оставляем точное совпадение названий")
                                    else:
                                        # GPT-5 не подтвердил и не было точного совпадения, сбрасываем
                                        if verbose and needs_gpt5_check:
                                            print(f"         ❌ GPT-5 не подтвердил совпадение")
                                        best_match = None
                                        best_score = 0.0
                                        best_asana_idx = -1
                            except Exception as e:
                                if verbose:
                                    print(f"         ⚠️  Ошибка GPT-5 проверки: {e}, используем оценку эмбеддингов")
                                # Если была проверка потенциального совпадения и GPT-5 упал, сбрасываем
                                if needs_gpt5_check:
                                    best_match = None
                                    best_score = 0.0
                                    best_asana_idx = -1
                    
                    # Проверяем порог схожести
                    if best_score < similarity_threshold:
                        best_match = None
                        best_score = 0.0
                        best_asana_idx = -1
                
                except Exception as e:
                    if verbose:
                        print(f"      ⚠️  Ошибка поиска через эмбеддинги: {e}, переключаемся на GPT-5")
                    use_embeddings = False
            
            # Fallback: полный перебор через GPT-5 (если эмбеддинги не работают и квота не превышена)
            comparisons_done = 0  # Инициализируем переменную перед использованием
            quota_error_count = 0
            if not use_embeddings and not quota_exceeded:
                # Если эмбеддинги отключены, используем GPT-5 для всех сравнений
                comparisons_done = 0
                quota_error_count = 0
                for idx, asana_task in enumerate(asana_tasks):
                    if idx in asana_matched:
                        continue
                    
                    asana_name = asana_task.get('name', '')
                    asana_notes = asana_task.get('notes', '') or ''
                    # Для GPT-5 используем полный текст из context
                    asana_context = self.extract_asana_task_context(asana_task)
                    asana_text_full = asana_context['full_text']
                    
                    comparisons_done += 1
                    if verbose and comparisons_done % 10 == 0:
                        print(f"      🔍 Сравнение {comparisons_done}/{len(asana_tasks)}...", end='\r', flush=True)
                    
                    try:
                        # Для Telegram используем полный context при GPT-5 проверке
                        tg_text_full = f"{tg_title} {tg_desc} {tg_context}".strip()[:8000]
                        score = self.calculate_similarity(tg_text_full, asana_text_full, verbose=verbose)
                        
                        if score > best_score and score >= similarity_threshold:
                            best_score = score
                            best_match = asana_task
                            best_asana_idx = idx
                        quota_error_count = 0  # Сбрасываем счетчик при успехе
                    except Exception as e:
                        error_str = str(e)
                        if '429' in error_str or 'insufficient_quota' in error_str or 'quota' in error_str.lower():
                            quota_error_count += 1
                            if quota_error_count >= 3:  # Если 3 ошибки подряд - останавливаем
                                if verbose:
                                    print(f"\n      ❌ Превышена квота OpenAI! Останавливаем сравнения.")
                                    print(f"      ✅ Используем только найденные точные совпадения названий")
                                quota_exceeded = True
                                break
                        if verbose and quota_error_count == 0:
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
        
        # Анализ покрытия: что реализовано в Asana из задач Telegram
        coverage_analysis = self._analyze_coverage(matches, telegram_tasks, asana_tasks)
        
        return {
            'matches': matches,
            'telegram_only': telegram_only,
            'asana_only': asana_only,
            'coverage': coverage_analysis
        }
    
    def find_matching_tasks_v2(
        self,
        telegram_tasks: List[Dict[str, Any]],
        asana_tasks: List[Dict[str, Any]],
        similarity_threshold: float = 0.75,
        verbose: bool = True,
        use_embeddings: bool = True,
        use_gpt5_verification: bool = False,
        low_threshold: float = 0.65,
        use_two_stage_matching: bool = True
    ) -> Dict[str, List[Tuple[Dict, Dict, float]]]:
        """
        Новая версия поиска совпадений с использованием временных окон и кеша эмбеддингов
        
        Алгоритм:
        0. Предварительная суммаризация задач Asana через GPT-5 Batch API (если включена)
        1. Получение эмбеддингов для всех Telegram задач батчами
        2. Определение временных окон для каждой Telegram задачи
        3. Фильтрация задач Asana по окнам
        4. Предварительный поиск через эмбеддинги (с кешем, используя суммаризированные версии)
        5. GPT-5 проверка для топ-кандидатов
        
        Args:
            telegram_tasks: Список задач из Telegram
            asana_tasks: Список задач из Asana
            similarity_threshold: Порог схожести (0.0-1.0)
            verbose: Выводить прогресс
            use_embeddings: Использовать эмбеддинги
            use_gpt5_verification: Использовать GPT-5 для финальной проверки
            low_threshold: Низкий порог для потенциальных совпадений
            use_two_stage_matching: Двухэтапное совпадение
        
        Returns:
            Dict с ключами: 'matches', 'telegram_only', 'asana_only', 'coverage'
        """
        matches = []
        telegram_matched = set()
        asana_matched = set()
        
        if verbose:
            print(f"   📊 Всего задач: {len(telegram_tasks)} Telegram × {len(asana_tasks)} Asana")
            if self.use_time_windows:
                print(f"   ⏰ Используются временные окна для фильтрации")
            if self.embedding_cache:
                cache_stats = self.embedding_cache.get_cache_stats()
                print(f"   💾 Кеш эмбеддингов: {cache_stats['local_cache_size']} записей")
            if self.use_task_summarization and self.task_summarizer:
                print(f"   📝 Используется предварительная суммаризация задач через GPT-5 Batch API")
        
        # Шаг 0: Предварительная суммаризация задач Asana через Batch API (если включена)
        if self.use_task_summarization and self.task_summarizer:
            if verbose:
                print(f"\n   📝 Предварительная суммаризация {len(asana_tasks)} задач Asana через Batch API...")
            
            try:
                summarized_tasks = self.task_summarizer.summarize_tasks_batch(
                    asana_tasks,
                    verbose=verbose
                )
                
                # Сохраняем в кеш текущей сессии
                self._summarized_tasks_cache.update(summarized_tasks)
                
                if verbose:
                    print(f"   ✅ Суммаризировано {len(summarized_tasks)} задач")
            except Exception as e:
                if verbose:
                    print(f"   ⚠️  Ошибка суммаризации: {e}")
                    print(f"   💡 Продолжаем без суммаризации")
                # Продолжаем без суммаризации
        
        # Шаг 1: Получаем эмбеддинги для всех Telegram задач батчами (оптимизация затрат)
        telegram_embeddings_map = {}
        if use_embeddings:
            if verbose:
                print(f"\n   🔢 Получение эмбеддингов для {len(telegram_tasks)} Telegram задач (батчами)...")
            
            telegram_texts = []
            telegram_indices = []
            
            for idx, tg_task in enumerate(telegram_tasks):
                tg_title = tg_task.get('title', '')
                tg_desc = tg_task.get('description', '')
                tg_context = tg_task.get('context', '')
                # Для эмбеддингов используем компактную версию:
                # title + description + первые 1500 символов context (важнее начало)
                # Это улучшает качество, так как эмбеддинги усредняют информацию
                tg_context_compact = tg_context[:1500] if tg_context else ''
                tg_text = f"{tg_title} {tg_desc} {tg_context_compact}".strip()[:8000]
                telegram_texts.append(tg_text)
                telegram_indices.append(idx)
            
            # Получаем эмбеддинги батчами (с кешем)
            if self.embedding_cache:
                telegram_embeddings = self.embedding_cache.get_embeddings_batch(
                    telegram_texts,
                    client=self.openai_client,
                    batch_size=100
                )
            else:
                # Fallback: получаем батчами без кеша
                telegram_embeddings = []
                batch_size = 100
                for i in range(0, len(telegram_texts), batch_size):
                    batch_texts = telegram_texts[i:i+batch_size]
                    try:
                        response = self.openai_client.embeddings.create(
                            model="text-embedding-3-small",
                            input=batch_texts
                        )
                        batch_embeddings = [item.embedding for item in response.data]
                        telegram_embeddings.extend(batch_embeddings)
                        if verbose and (i // batch_size + 1) % 10 == 0:
                            print(f"      📦 Батч {i // batch_size + 1}/{(len(telegram_texts)-1)//batch_size + 1}...", end='\r', flush=True)
                    except Exception as e:
                        if verbose:
                            print(f"      ⚠️  Ошибка батча {i // batch_size + 1}: {e}")
                        # Добавляем None для ошибок
                        telegram_embeddings.extend([None] * len(batch_texts))
            
            # Создаем маппинг индекс -> эмбеддинг
            for idx, embedding in zip(telegram_indices, telegram_embeddings):
                telegram_embeddings_map[idx] = embedding
            
            if verbose:
                successful = sum(1 for emb in telegram_embeddings if emb is not None)
                print(f"\n      ✅ Получено эмбеддингов: {successful}/{len(telegram_tasks)}")
        
        # Обрабатываем каждую задачу Telegram
        for tg_idx, tg_task in enumerate(telegram_tasks, 1):
            tg_title = tg_task.get('title', '')
            tg_desc = tg_task.get('description', '')
            tg_context = tg_task.get('context', '')
            # Для эмбеддингов используем компактную версию:
            # title + description + первые 1500 символов context (важнее начало)
            # Это улучшает качество, так как эмбеддинги усредняют информацию
            tg_context_compact = tg_context[:1500] if tg_context else ''
            tg_text = f"{tg_title} {tg_desc} {tg_context_compact}".strip()[:8000]
            
            if verbose:
                print(f"\n   [{tg_idx}/{len(telegram_tasks)}] 📱 Telegram: {tg_title[:60]}...")
            
            # Шаг 1: Определяем временные окна и фильтруем задачи Asana
            windowed_tasks = {}
            if self.use_time_windows and self.time_window_matcher:
                windowed_tasks = self.time_window_matcher.prioritize_tasks_by_windows(tg_task, asana_tasks)
                
                if verbose:
                    primary_count = len(windowed_tasks.get('primary', []))
                    extended_count = len(windowed_tasks.get('extended', []))
                    distant_count = len(windowed_tasks.get('distant', []))
                    print(f"      ⏰ Окна: основное={primary_count}, расширенное={extended_count}, дальнее={distant_count}")
            else:
                # Без временных окон - используем все задачи
                windowed_tasks = {
                    'primary': asana_tasks,
                    'extended': [],
                    'distant': []
                }
            
            # Шаг 2: Предварительная проверка точных совпадений названий
            tg_title_normalized = self.normalize_text(tg_title)
            best_match = None
            best_score = 0.0
            best_asana_idx = -1
            exact_match_found = False
            
            # Проверяем сначала в основном окне
            for window_name in ['primary', 'extended', 'distant']:
                window_tasks = windowed_tasks.get(window_name, [])
                for idx, asana_task in enumerate(window_tasks):
                    if asana_task.get('gid') in asana_matched:
                        continue
                    
                    asana_name = asana_task.get('name', '')
                    asana_name_normalized = self.normalize_text(asana_name)
                    
                    # Точное совпадение
                    if tg_title_normalized == asana_name_normalized:
                        best_match = asana_task
                        best_score = 1.0
                        best_asana_idx = asana_task.get('gid')
                        exact_match_found = True
                        if verbose:
                            print(f"      ✅ ТОЧНОЕ СОВПАДЕНИЕ НАЗВАНИЙ! Score: 1.00 → {asana_name[:50]}")
                        break
                    
                    # Частичное совпадение
                    if tg_title_normalized in asana_name_normalized or asana_name_normalized in tg_title_normalized:
                        shorter = min(len(tg_title_normalized), len(asana_name_normalized))
                        longer = max(len(tg_title_normalized), len(asana_name_normalized))
                        if shorter > 0:
                            partial_score = shorter / longer
                            if partial_score > 0.7 and partial_score > best_score:
                                best_match = asana_task
                                best_score = partial_score
                                best_asana_idx = asana_task.get('gid')
                                exact_match_found = True
                                if verbose:
                                    print(f"      ✅ ЧАСТИЧНОЕ СОВПАДЕНИЕ НАЗВАНИЙ! Score: {partial_score:.2f} → {asana_name[:50]}")
                
                if exact_match_found:
                    break
            
            # Если нашли точное совпадение, используем его
            if exact_match_found and best_score >= similarity_threshold:
                matches.append((tg_task, best_match, best_score))
                telegram_matched.add(tg_idx - 1)
                asana_matched.add(best_asana_idx)
                if verbose:
                    print(f"      ✅ Найдено совпадение! Score: {best_score:.2f}")
                continue
            
            # Шаг 3: Поиск через эмбеддинги (если включен)
            if use_embeddings:
                try:
                    # Используем предварительно полученный эмбеддинг (батчами)
                    tg_embedding = telegram_embeddings_map.get(tg_idx - 1)
                    
                    if not tg_embedding:
                        if verbose:
                            print(f"      ⚠️  Не удалось получить эмбеддинг, пропускаем")
                        continue
                    
                    # Собираем кандидатов из всех окон с приоритетами
                    all_candidates = []
                    
                    # Обрабатываем окна по приоритету
                    for window_name, window_tasks in [
                        ('primary', windowed_tasks.get('primary', [])),
                        ('extended', windowed_tasks.get('extended', [])),
                        ('distant', windowed_tasks.get('distant', []))
                    ]:
                        if not window_tasks:
                            continue
                        
                        # Получаем эмбеддинги для задач в окне (с кешем)
                        asana_texts = []
                        asana_indices = []
                        
                        for idx, asana_task in enumerate(window_tasks):
                            if asana_task.get('gid') in asana_matched:
                                continue
                            
                            context = self.extract_asana_task_context(asana_task)
                            # Для эмбеддингов используем компактную версию (лучше качество сопоставления)
                            asana_text = context.get('embedding_text', context['full_text'])[:8000]
                            asana_texts.append(asana_text)
                            asana_indices.append((idx, asana_task))
                        
                        if not asana_texts:
                            continue
                        
                        # Получаем эмбеддинги батчами (с кешем)
                        # Важно: используем батчинг для оптимизации затрат
                        if self.embedding_cache:
                            asana_embeddings = self.embedding_cache.get_embeddings_batch(
                                asana_texts,
                                client=self.openai_client,
                                batch_size=100  # OpenAI поддерживает до 2048, используем 100 для надежности
                            )
                        else:
                            # Fallback: батчинг без кеша (важно для оптимизации затрат)
                            asana_embeddings = []
                            batch_size = 100
                            for i in range(0, len(asana_texts), batch_size):
                                batch_texts = asana_texts[i:i+batch_size]
                                try:
                                    response = self.openai_client.embeddings.create(
                                        model="text-embedding-3-small",
                                        input=batch_texts
                                    )
                                    batch_embeddings = [item.embedding for item in response.data]
                                    asana_embeddings.extend(batch_embeddings)
                                except Exception as e:
                                    if verbose:
                                        print(f"         ⚠️  Ошибка батча эмбеддингов Asana: {e}")
                                    # Добавляем None для ошибок
                                    asana_embeddings.extend([None] * len(batch_texts))
                        
                        # Вычисляем схожесть
                        for (idx, asana_task), embedding in zip(asana_indices, asana_embeddings):
                            if embedding is None:
                                continue
                            
                            similarity = cosine_similarity_embedding(tg_embedding, embedding)
                            
                            # Пороги зависят от окна
                            if window_name == 'primary':
                                min_score = low_threshold
                            elif window_name == 'extended':
                                min_score = low_threshold + 0.05  # Чуть выше порог
                            else:  # distant
                                min_score = similarity_threshold  # Только высокие совпадения
                            
                            if similarity >= min_score:
                                all_candidates.append({
                                    'task': asana_task,
                                    'score': similarity,
                                    'window': window_name,
                                    'gid': asana_task.get('gid')
                                })
                    
                    # Сортируем кандидатов по score
                    all_candidates.sort(key=lambda x: x['score'], reverse=True)
                    
                    # Берем топ-кандидатов (максимум 5 из основного окна, 3 из расширенного, 2 из дальнего)
                    top_candidates = []
                    primary_count = 0
                    extended_count = 0
                    distant_count = 0
                    
                    for candidate in all_candidates:
                        window = candidate['window']
                        if window == 'primary' and primary_count < 5:
                            top_candidates.append(candidate)
                            primary_count += 1
                        elif window == 'extended' and extended_count < 3:
                            top_candidates.append(candidate)
                            extended_count += 1
                        elif window == 'distant' and distant_count < 2:
                            top_candidates.append(candidate)
                            distant_count += 1
                    
                    if top_candidates:
                        best_candidate = top_candidates[0]
                        best_match = best_candidate['task']
                        best_score = best_candidate['score']
                        best_asana_idx = best_candidate['gid']
                        
                        if verbose:
                            print(f"      🔢 Лучший кандидат через эмбеддинги: {best_score:.3f} (окно: {best_candidate['window']}) → {best_match.get('name', '')[:50]}")
                        
                        # Двухэтапное совпадение: GPT-5 проверка для потенциальных совпадений
                        needs_gpt5_check = False
                        if use_two_stage_matching and low_threshold <= best_score < similarity_threshold:
                            needs_gpt5_check = True
                            if verbose:
                                print(f"         ⚠️  Потенциальное совпадение (score {best_score:.3f} < порога {similarity_threshold}), требуется GPT-5 проверка")
                        
                        # GPT-5 проверка
                        # Для GPT-5 используем полный текст (full_text) для лучшего понимания контекста
                        if needs_gpt5_check or (use_gpt5_verification and best_score >= similarity_threshold):
                            # Используем полный текст из context для GPT-5 (лучше качество)
                            best_match_context = self.extract_asana_task_context(best_match)
                            asana_text_full = best_match_context['full_text']
                            
                            # Для Telegram также используем полный context при GPT-5 проверке
                            tg_text_full = f"{tg_title} {tg_desc} {tg_context}".strip()[:8000]
                            
                            try:
                                gpt5_score = self.calculate_similarity(tg_text_full, asana_text_full, verbose=verbose)
                                if verbose:
                                    if needs_gpt5_check:
                                        print(f"         🔍 GPT-5 проверка потенциального совпадения: {best_score:.3f} → {gpt5_score:.2f}")
                                    else:
                                        print(f"         🔍 GPT-5 проверка: {best_score:.3f} → {gpt5_score:.2f}")
                                
                                if gpt5_score >= similarity_threshold:
                                    best_score = gpt5_score
                                    if verbose and needs_gpt5_check:
                                        print(f"         ✅ GPT-5 подтвердил совпадение!")
                                else:
                                    if exact_match_found:
                                        if verbose:
                                            print(f"         ⚠️  GPT-5 не подтвердил, но оставляем точное совпадение названий")
                                    else:
                                        if verbose and needs_gpt5_check:
                                            print(f"         ❌ GPT-5 не подтвердил совпадение")
                                        best_match = None
                                        best_score = 0.0
                                        best_asana_idx = -1
                            except Exception as e:
                                if verbose:
                                    print(f"         ⚠️  Ошибка GPT-5 проверки: {e}, используем оценку эмбеддингов")
                                if needs_gpt5_check:
                                    best_match = None
                                    best_score = 0.0
                                    best_asana_idx = -1
                    
                    # Проверяем финальный порог
                    if best_match and best_score >= similarity_threshold:
                        matches.append((tg_task, best_match, best_score))
                        telegram_matched.add(tg_idx - 1)
                        asana_matched.add(best_asana_idx)
                        if verbose:
                            print(f"      ✅ Найдено совпадение! Score: {best_score:.2f} → {best_match.get('name', '')[:50]}")
                    else:
                        if verbose:
                            print(f"      ❌ Совпадений не найдено (порог: {similarity_threshold})")
                
                except Exception as e:
                    if verbose:
                        print(f"      ⚠️  Ошибка поиска через эмбеддинги: {e}")
                        import traceback
                        traceback.print_exc()
            
            # Если не нашли через эмбеддинги и нет точного совпадения
            if not best_match and verbose:
                print(f"      ❌ Совпадений не найдено")
        
        # Задачи только в Telegram
        telegram_only = [
            tg_task for idx, tg_task in enumerate(telegram_tasks)
            if idx not in telegram_matched
        ]
        
        # Задачи только в Asana
        asana_only = [
            asana_task for asana_task in asana_tasks
            if asana_task.get('gid') not in asana_matched
        ]
        
        # Анализ покрытия
        coverage_analysis = analyze_coverage(matches, telegram_tasks, asana_tasks, self.context_extractor)
        
        # Сохраняем кеш перед завершением (если были изменения)
        if self.embedding_cache:
            self.embedding_cache.flush_cache()
            if verbose:
                self.embedding_cache.print_cache_stats()
        
        return {
            'matches': matches,
            'telegram_only': telegram_only,
            'asana_only': asana_only,
            'coverage': coverage_analysis
        }
    
    def _analyze_coverage(
        self,
        matches: List[Tuple[Dict, Dict, float]],
        telegram_tasks: List[Dict[str, Any]],
        asana_tasks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Анализ покрытия (делегирует в report_generator)"""
        return analyze_coverage(matches, telegram_tasks, asana_tasks, self.context_extractor)
    
    def generate_sync_report(
        self,
        matching_result: Dict[str, List],
        output_file: Path
    ):
        """Генерировать отчет о синхронизации (делегирует в report_generator)"""
        return generate_sync_report(matching_result, output_file, self.context_extractor)
    
    def enrich_asana_task_with_telegram(
        self, 
        asana_task: Dict[str, Any], 
        telegram_task: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Дополнить задачу из Asana данными из Telegram (делегирует в task_transformer)"""
        return enrich_asana_task_with_telegram(asana_task, telegram_task)
    
    def create_asana_task_from_telegram(
        self, 
        telegram_task: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Подготовить данные для создания задачи в Asana (делегирует в task_transformer)"""
        return create_asana_task_from_telegram(
            telegram_task,
            workspace_gid=self.workspace_gid,
            project_gid=self.project_gid,
            assignee_gid=ASANA_USER_GID
        )
    


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

