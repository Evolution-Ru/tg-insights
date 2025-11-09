#!/usr/bin/env python3
"""
Модуль сопоставления задач Telegram и Asana
"""
from typing import Dict, List, Any, Tuple
from sync.reporter import analyze_coverage
from pipeline.telegram.vectorization.embeddings import cosine_similarity_embedding


def find_matching_tasks(
    sync_instance,
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
    Поиск совпадений с использованием временных окон и кеша эмбеддингов
    
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
        if sync_instance.use_time_windows:
            print(f"   ⏰ Используются временные окна для фильтрации")
        if sync_instance.embedding_cache:
            cache_stats = sync_instance.embedding_cache.get_cache_stats()
            print(f"   💾 Кеш эмбеддингов: {cache_stats['local_cache_size']} записей")
        if sync_instance.use_task_summarization and sync_instance.task_summarizer:
            print(f"   📝 Используется предварительная суммаризация задач через GPT-5 Batch API")
    
    # Шаг 0: Предварительная суммаризация задач Asana через Batch API (если включена)
    if sync_instance.use_task_summarization and sync_instance.task_summarizer:
        if verbose:
            print(f"\n   📝 Предварительная суммаризация {len(asana_tasks)} задач Asana через Batch API...")
        
        try:
            summarized_tasks = sync_instance.task_summarizer.summarize_tasks_batch(
                asana_tasks,
                verbose=verbose
            )
            
            # Сохраняем в кеш текущей сессии
            sync_instance._summarized_tasks_cache.update(summarized_tasks)
            
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
        if sync_instance.embedding_cache:
            telegram_embeddings = sync_instance.embedding_cache.get_embeddings_batch(
                telegram_texts,
                client=sync_instance.openai_client,
                batch_size=100
            )
        else:
            # Fallback: получаем батчами без кеша
            telegram_embeddings = []
            batch_size = 100
            for i in range(0, len(telegram_texts), batch_size):
                batch_texts = telegram_texts[i:i+batch_size]
                try:
                    response = sync_instance.openai_client.embeddings.create(
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
        if sync_instance.use_time_windows and sync_instance.time_window_matcher:
            windowed_tasks = sync_instance.time_window_matcher.prioritize_tasks_by_windows(tg_task, asana_tasks)
            
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
        tg_title_normalized = sync_instance.normalize_text(tg_title)
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
                asana_name_normalized = sync_instance.normalize_text(asana_name)
                
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
                        
                        context = sync_instance.extract_asana_task_context(asana_task)
                        # Для эмбеддингов используем компактную версию (лучше качество сопоставления)
                        asana_text = context.get('embedding_text', context['full_text'])[:8000]
                        asana_texts.append(asana_text)
                        asana_indices.append((idx, asana_task))
                    
                    if not asana_texts:
                        continue
                    
                    # Получаем эмбеддинги батчами (с кешем)
                    # Важно: используем батчинг для оптимизации затрат
                    if sync_instance.embedding_cache:
                        asana_embeddings = sync_instance.embedding_cache.get_embeddings_batch(
                            asana_texts,
                            client=sync_instance.openai_client,
                            batch_size=100  # OpenAI поддерживает до 2048, используем 100 для надежности
                        )
                    else:
                        # Fallback: батчинг без кеша (важно для оптимизации затрат)
                        asana_embeddings = []
                        batch_size = 100
                        for i in range(0, len(asana_texts), batch_size):
                            batch_texts = asana_texts[i:i+batch_size]
                            try:
                                response = sync_instance.openai_client.embeddings.create(
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
                        best_match_context = sync_instance.extract_asana_task_context(best_match)
                        asana_text_full = best_match_context['full_text']
                        
                        # Для Telegram также используем полный context при GPT-5 проверке
                        tg_text_full = f"{tg_title} {tg_desc} {tg_context}".strip()[:8000]
                        
                        try:
                            gpt5_score = sync_instance.calculate_similarity(tg_text_full, asana_text_full, verbose=verbose)
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
    coverage_analysis = analyze_coverage(matches, telegram_tasks, asana_tasks, sync_instance.context_extractor)
    
    # Сохраняем кеш перед завершением (если были изменения)
    if sync_instance.embedding_cache:
        sync_instance.embedding_cache.flush_cache()
        if verbose:
            sync_instance.embedding_cache.print_cache_stats()
    
    return {
        'matches': matches,
        'telegram_only': telegram_only,
        'asana_only': asana_only,
        'coverage': coverage_analysis
    }

