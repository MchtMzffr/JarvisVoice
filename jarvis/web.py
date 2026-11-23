"""Search requests go only to the fixed Ollama HTTPS API. No local URL fetch."""
import asyncio
import ipaddress
from urllib.parse import urlsplit
import httpx
from .config import SETTINGS


class WebUnavailable(Exception):
    pass


def public_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme != "https" or parts.username or parts.password or not host or parts.port not in (None, 443):
            return False
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "." not in host:
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


async def _post(client, path: str, payload: dict):
    async with client.stream("POST", path, json=payload) as response:
        if response.status_code != 200:
            raise WebUnavailable("İnternet servisine ulaşılamadı; anahtarı veya kullanım sınırını kontrol et.")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > 1024 * 1024:
                raise WebUnavailable("İnternet yanıtı uygulama sınırını aştı.")
        import json
        return json.loads(body)


async def research(query: str, api_key: str):
    query = query.strip()
    if not query or len(query) > SETTINGS.web_query_max_chars:
        raise WebUnavailable("Arama sorgusu boş veya çok uzun.")
    try:
        async with httpx.AsyncClient(base_url="https://ollama.com", headers={"Authorization": f"Bearer {api_key}"}, timeout=SETTINGS.web_timeout_s, follow_redirects=False, trust_env=False) as client:
            result = await _post(client, "/api/web_search", {"query": query, "max_results": 3})
            candidates = [r for r in result.get("results", []) if isinstance(r, dict) and public_url(str(r.get("url", "")))][:SETTINGS.web_max_fetches]
            if not candidates:
                raise WebUnavailable("Bu sorgu için kullanılabilir internet kaynağı bulunamadı.")
            sources, blocks = [], []
            for index, source in enumerate(candidates, 1):
                content = str(source.get("content", ""))
                quality = "arama özeti; sayfanın tamamı alınamadı"
                try:
                    fetched = await _post(client, "/api/web_fetch", {"url": source["url"]})
                    if isinstance(fetched, dict) and fetched.get("content"):
                        content = str(fetched["content"])
                        quality = "alınan sayfa metninden kısa bölüm"
                except (WebUnavailable, httpx.HTTPError, ValueError):
                    pass
                title = str(source.get("title", source["url"]))[:180]
                sources.append({"id": index, "title": title, "url": source["url"], "kind": quality})
                blocks.append(f"[{index}] {title}\nKaynak durumu: {quality}\n{content[:SETTINGS.web_page_max_chars]}")
            return sources, "\n\n".join(blocks)
    except WebUnavailable:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise WebUnavailable("İnternet araştırması tamamlanamadı; güncel bilgiyi doğrulayamadım.") from None
