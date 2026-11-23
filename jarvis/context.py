"""Offline o200k_harmony counting with explicit generation/framing reserves.

Source: https://github.com/openai/tiktoken/blob/0.12.0/tiktoken_ext/openai_public.py
Ollama's chat-template framing is separately reserved, not assumed to be zero.
"""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import urllib.request
from .config import DATA_ROOT, SETTINGS

TOKENIZER_URL = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
TOKENIZER_SHA = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"
TOKENIZER_DIR = DATA_ROOT / "models" / "tokenizer"
TOKENIZER_FILE = TOKENIZER_DIR / hashlib.sha1(TOKENIZER_URL.encode()).hexdigest()


def valid_cache():
    return TOKENIZER_FILE.is_file() and hashlib.sha256(TOKENIZER_FILE.read_bytes()).hexdigest() == TOKENIZER_SHA


def prepare_tokenizer(progress):
    if valid_cache():
        return
    progress("Konuşma bağlamı sayacı hazırlanıyor…")
    TOKENIZER_DIR.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(TOKENIZER_URL, timeout=60) as response:
        data = response.read(8 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != TOKENIZER_SHA:
        raise RuntimeError("Bağlam sayacı dosyası doğrulanamadı.")
    temporary = TOKENIZER_FILE.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(TOKENIZER_FILE)


@lru_cache(maxsize=1)
def encoder():
    if not valid_cache():
        raise RuntimeError("Bağlam sayacı eksik. KUR.cmd dosyasını yeniden çalıştır.")
    os.environ["TIKTOKEN_CACHE_DIR"] = str(TOKENIZER_DIR)
    import tiktoken
    return tiktoken.get_encoding("o200k_harmony")


def count(text):
    return len(encoder().encode(text, disallowed_special=()))


def fit_messages(messages, tools=None):
    """Drop oldest history before trimming appended context, preserving the system.

    At most 2,752 content/tool tokens are passed with the default 4,096 context;
    1,024 generated tokens and 320 framing tokens remain reserved. The application
    does not claim unlimited memory. Web excerpts may be shortened to this budget.
    """
    result = [{"role": m["role"], "content": m["content"]} for m in messages]
    tool_cost = count(json.dumps(tools, ensure_ascii=False)) if tools else 0
    budget = SETTINGS.num_ctx - SETTINGS.num_predict - SETTINGS.context_framing_reserve - tool_cost
    def total():
        return sum(count(m["content"]) + 12 for m in result)
    while total() > budget and len(result) > 2:
        result.pop(1)
    if total() > budget:
        allowance = budget - count(result[0]["content"]) - 24
        if allowance <= 0:
            raise RuntimeError("Başlangıç talimatı bağlam sınırını aşıyor.")
        tokens = encoder().encode(result[-1]["content"], disallowed_special=())
        result[-1]["content"] = encoder().decode(tokens[:allowance])
    if total() > budget:
        raise RuntimeError("Konuşma bağlamı sınırı aşıldı.")
    return result
