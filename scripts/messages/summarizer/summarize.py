from typing import Any, Dict, List, Optional, Tuple
import json

from . import logging as slog
from . import model as smodel
from .prompting import (
    compose_system_ru,
    compose_user_prompt,
    build_responses_input,
    build_chat_messages,
    build_block_from_parsed,
)


def summarize_block(
    previous_context: Optional[str],
    rendered_messages: str,
    participants: List[str],
    *,
    chat_id: int,
    chat_title: Optional[str],
    last_message_date: Optional[str],
    lang: str = "ru",
    log_io: bool = False,
) -> Tuple[str, Optional[str]]:
    """Build a concise context block for new dialog messages.

    Strategy:
    - Tries OpenAI Responses with a strict JSON schema first (for structured fields and block_text)
    - If parsing fails, falls back to Chat Completions text output
    - As a last resort, calls Responses without schema

    Args:
        previous_context: Last stored context block for this dialog (or None)
        rendered_messages: Pre-rendered messages text for the model
        participants: List of participant labels passed to the model
        chat_id: Dialog identifier (for metadata in the prompt)
        chat_title: Optional dialog title (for metadata)
        last_message_date: ISO date of the last message in this chunk (for metadata)
        lang: Response language hint (kept for compatibility)
        log_io: If True, logs prompts and raw responses

    Returns:
        Tuple of (final_block_text, context_json_or_none). context_json contains the
        structured JSON returned by Responses when available (participants/facts/etc.).
    """
    client = smodel.build_client()
    model_name = smodel.model_name()

    system_ru = compose_system_ru()
    user_prompt_str, schema_instruction = compose_user_prompt(
        previous_context,
        rendered_messages,
        participants,
        chat_id=chat_id,
        chat_title=chat_title,
        last_message_date=last_message_date,
    )

    if log_io:
        try:
            slog.log(
                "OpenAI request (Responses) model="
                + model_name
                + "\nSYSTEM:\n"
                + system_ru
                + "\nUSER:\n"
                + user_prompt_str
                + "\nSCHEMA:\n"
                + schema_instruction
            )
        except Exception:
            pass

    resp_text = None
    try:
        resp = client.responses.create(
            model=model_name,
            input=build_responses_input(system_ru, user_prompt_str, schema_instruction),
            reasoning={"effort": "low"},
        )
        if getattr(resp, "output", None):
            chunks: List[str] = []
            for item in resp.output:
                if getattr(item, "content", None):
                    for c in item.content:
                        if getattr(c, "text", None):
                            chunks.append(c.text)
            resp_text = "\n".join(chunks).strip()
        if log_io:
            try:
                slog.log(
                    "OpenAI response (Responses) raw:\n" + (resp_text or "[empty]")
                )
            except Exception:
                pass
    except Exception:
        resp_text = None

    if resp_text:
        try:
            parsed = json.loads(resp_text)
        except Exception:
            parsed = None
        if parsed:
            built = build_block_from_parsed(parsed)
            if built:
                block_text, context_json = built
                if log_io:
                    try:
                        slog.log("OpenAI structured JSON parsed for Responses")
                    except Exception:
                        pass
                return block_text, context_json

    # Fallback 1: Chat Completions
    messages = build_chat_messages(system_ru, user_prompt_str)
    if log_io:
        try:
            slog.log(
                f"OpenAI request (Completions) model={model_name}\nSYSTEM:\n{system_ru}\nUSER:\n{user_prompt_str}"
            )
        except Exception:
            pass
    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=messages
        )
        text = (resp.choices[0].message.content or "").strip()
        if log_io:
            try:
                slog.log("OpenAI response (Completions) text:\n" + (text or "[empty]"))
            except Exception:
                pass
        if text:
            return text, None
    except Exception as e:
        # Fallback 2: Responses без JSON-требования
        if log_io:
            try:
                slog.log(
                    "OpenAI request (Responses fallback, no schema) model=" + model_name
                )
            except Exception:
                pass
        try:
            resp = client.responses.create(
                model=model_name,
                input=build_responses_input(system_ru, user_prompt_str),
                reasoning={"effort": "low"},
            )
            if getattr(resp, "output", None):
                chunks2: List[str] = []
                for item in resp.output:
                    if getattr(item, "content", None):
                        for c in item.content:
                            if getattr(c, "text", None):
                                chunks2.append(c.text)
                text2 = "\n".join(chunks2).strip()
                if log_io:
                    try:
                        slog.log(
                            "OpenAI response (Responses fallback) raw:\n"
                            + (text2 or "[empty]")
                        )
                    except Exception:
                        pass
                if text2:
                    return text2, None
        except Exception as e2:
            raise RuntimeError(f"OpenAI call failed: {e} / {e2}") from e2

    raise RuntimeError("OpenAI returned empty response")
