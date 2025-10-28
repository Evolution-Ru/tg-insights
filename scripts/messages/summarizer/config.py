import os


def openai_api_key() -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return key


def openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5")


def batch_completion_window_default() -> str:
    return os.getenv("OPENAI_BATCH_COMPLETION_WINDOW", "24h")


def batch_wait_seconds_default() -> int:
    try:
        return int(os.getenv("OPENAI_BATCH_WAIT_SECONDS", "10"))
    except Exception:
        return 10
