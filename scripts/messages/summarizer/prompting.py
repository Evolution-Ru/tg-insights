from typing import Any, Dict, List, Optional, Tuple
import json


def compose_system_ru() -> str:
    return (
        "Ты помощник, который делает контекстные выжимки по правилам:\n"
        "- Удаляй только явный шум: приветствия, прощания, смайлики, пустые реплики, дублирование.\n"
        "- Никогда не выбрасывай новые факты, даже мелкие.\n"
        "- Если сомневаешься — сохраняй.\n"
        "- Объединяй подряд идущие реплики по одной теме.\n"
        "- Фиксируй участников и значимые изменения контекста.\n"
        "- Новый блок должен содержать только НОВЫЕ факты относительно прошлого контекста, без повторов.\n"
        "- Сохраняй числа, даты, суммы, проценты и формулировки фактов с кратким описанием самого фактабез искажений. Не додумывай.\n"
        "- Если упоминается стратегия/инструкция/процесс — выпиши её пошагово, кратко, но с конкретикой (что, как, чем подтверждено).\n"
        "- Если есть обязательства/сроки/встречи — укажи точные даты/время/город/место/таймзону, если они прозвучали.\n"
        "- Если в переписке есть коды/логины/ссылки/идентификаторы — включи их в раздел ‘Ссылки/идентификаторы’.\n"
        "- Критичные формулировки можно дать ‘короткой цитатой’ в кавычках без интерпретации."
    )


def compose_user_prompt(
    previous_context: Optional[str],
    rendered_messages: str,
    participants: List[str],
    *,
    chat_id: int,
    chat_title: Optional[str],
    last_message_date: Optional[str],
) -> Tuple[str, str]:
    header: List[str] = []
    title = (chat_title or "").strip()
    if title:
        header.append(f"Диалог: {title} ({chat_id})")
    else:
        header.append(f"Диалог: {chat_id}")
    if last_message_date:
        header.append(f"Последняя дата сообщения в обрабатываемом блоке: {last_message_date}")
    user_prompt: List[str] = []
    user_prompt.append("\n".join(header))
    user_prompt.append("")
    user_prompt.append("Прошлый контекст (если есть):")
    user_prompt.append(previous_context.strip() if previous_context else "[нет]")
    user_prompt.append("")
    user_prompt.append(
        "Новые сообщения (очисти шум, сохрани факты/планы/сроки/эмоции, объедини по темам):"
    )
    user_prompt.append(rendered_messages)
    user_prompt.append("")
    user_prompt.append("Участники диалога:")
    user_prompt.append(", ".join(participants) if participants else "[не определены]")
    user_prompt.append("")
    user_prompt.append(
        "Сформируй новый контекстный блок ТОЛЬКО про новые факты из этих сообщений. Коротко и по делу."
    )
    user_prompt.append("Строгий формат вывода (используй все релевантные разделы):")
    user_prompt.append("- Участники: имена/ники (если новые или уточняются)")
    user_prompt.append("- Новые факты: пункты с конкретикой (кто/что/когда/где)")
    user_prompt.append("- Обязательства: пункты с конкретикой (кто/что/кому/до какой даты)")
    user_prompt.append("- Стратегии/инструкции (если есть): шаги 1..N со смысловыми деталями")
    user_prompt.append(
        "- Даты/сроки/места: перечисление с точностью до времени/таймзоны (если есть)"
    )
    user_prompt.append("- Ссылки/идентификаторы/коды: явный список (если есть)")
    user_prompt.append("- Эмоциональный фон/оценки: (если есть, 1–2 фразы)")
    user_prompt.append("- Риски/блокеры: (если есть)")
    user_prompt.append(
        "Не повторяй старые факты, если они не уточняются. Не обобщай: сохраняй конкретику."
    )

    schema_instruction = (
        "Верни ТОЛЬКО JSON (без пояснений и Markdown) со схемой: {\n"
        '  "participants": [string],\n'
        '  "facts": [string],\n'
        '  "obligations": [string],\n'
        '  "strategies": [ { "title": string, "steps": [string] } ],\n'
        '  "dates": [string],\n'
        '  "links": [string],\n'
        '  "emotions": [string],\n'
        '  "risks": [string],\n'
        '  "block_text": string\n'
        "}.\nПоле block_text — связный краткий блок на русском по нашим правилам."
    )
    return "\n".join(user_prompt), schema_instruction


def build_responses_input(
    system_ru: str, user_prompt_str: str, schema_instruction: Optional[str] = None
) -> List[Dict[str, Any]]:
    user_content = (
        "\n".join([user_prompt_str, "", schema_instruction])
        if schema_instruction
        else user_prompt_str
    )
    return [
        {"role": "system", "content": system_ru},
        {"role": "user", "content": user_content},
    ]


def build_chat_messages(system_ru: str, user_prompt_str: str) -> List[Dict[str, Any]]:
    return [
        {"role": "system", "content": system_ru},
        {"role": "user", "content": user_prompt_str},
    ]


def build_block_from_parsed(parsed: Dict[str, Any]) -> Optional[Tuple[str, Optional[str]]]:
    if not isinstance(parsed, dict):
        return None
    block = parsed.get("block_text")
    if isinstance(block, str) and block.strip():
        return block.strip(), json.dumps(parsed, ensure_ascii=False)
    parts_out: List[str] = []
    p_list = parsed.get("participants") or []
    if p_list:
        parts_out.append("- Участники: " + ", ".join([str(x) for x in p_list if x]))
    facts = parsed.get("facts") or []
    if facts:
        parts_out.append(
            "- Новые факты и договорённости:\n  - " + "\n  - ".join([str(x) for x in facts if x])
        )
    strategies = parsed.get("strategies") or []
    if strategies:
        lines = ["- Стратегии/инструкции:"]
        for s in strategies:
            title = (s or {}).get("title") or ""
            steps = (s or {}).get("steps") or []
            lines.append(f"  - {title}" if title else "  - (без названия)")
            for i, st in enumerate(steps, 1):
                lines.append(f"    {i}. {st}")
        parts_out.append("\n".join(lines))
    dates = parsed.get("dates") or []
    if dates:
        parts_out.append("- Даты/сроки/места: " + "; ".join([str(x) for x in dates if x]))
    links = parsed.get("links") or []
    if links:
        parts_out.append(
            "- Ссылки/идентификаторы/коды: " + "; ".join([str(x) for x in links if x])
        )
    emotions = parsed.get("emotions") or []
    if emotions:
        parts_out.append(
            "- Эмоциональный фон/оценки: " + "; ".join([str(x) for x in emotions if x])
        )
    risks = parsed.get("risks") or []
    if risks:
        parts_out.append("- Риски/блокеры: " + "; ".join([str(x) for x in risks if x]))
    if parts_out:
        final_block = "\n".join(parts_out)
        context_json = json.dumps(
            {
                "participants": parsed.get("participants") or [],
                "facts": parsed.get("facts") or [],
                "strategies": parsed.get("strategies") or [],
                "dates": parsed.get("dates") or [],
                "links": parsed.get("links") or [],
                "emotions": parsed.get("emotions") or [],
                "risks": parsed.get("risks") or [],
                "block_text": final_block,
            },
            ensure_ascii=False,
        )
        return final_block, context_json
    return None
