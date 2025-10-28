from typing import List, Optional
from openai import OpenAI
from . import config


def build_client() -> OpenAI:
    return OpenAI(api_key=config.openai_api_key())


def model_name() -> str:
    return config.openai_model()


# Here we could add wrappers similar to openai_summarize if we move more code later.
