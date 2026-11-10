"""Web search & web fetch tanpa API pihak ketiga.

Pencarian memakai HTML DuckDuckGo, pengambilan halaman memakai HTTP biasa.
Keduanya tetap dianggap cloud processing, jadi wajib lolos gerbang CLOUD_ENABLED
(lihat set_cloud_gate).
"""

import html as html_lib
import ipaddress
import os
import re
import urllib.parse

import httpx

try:
    WEB_TIMEOUT = max(5.0, min(90.0, float(os.getenv("WEB_FETCH_TIMEOUT", "35") or 35)))
except ValueError:
    WEB_TIMEOUT = 35.0

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class WebError(Exception):
    """Gagal mengambil data web."""


# ----------------------------------------------------------------------- helpers


def _ddg_url(href: str) -> str:
    """DuckDuckGo membungkus link jadi /l/?uddg=...; ambil URL aslinya."""
    href = html_lib.unescape(href or "")
    if href.startswith("//"):
        href = "https:" + href
    if "uddg=" in href:
        query = urllib.parse.urlparse(href).query
        target = urllib.parse.parse_qs(query).get("uddg", [""])[0]
        if target:
            return urllib.parse.unquote(target)
    return href


def _strip_tags(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|section|article)>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html_lib.unescape(raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n\n", raw)
    return raw.strip()


def _ddg_search(query: str, max_results: int) -> list[dict]:
    """Pencarian tanpa API key: DuckDuckGo HTML (tanpa dependency parser)."""
    try:
        with httpx.Client(timeout=WEB_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": _UA, "Accept-Language": "id-ID,id;q=0.9,en;q=0.8"},
            )
        if resp.status_code >= 400:
            return []
        page = resp.text
    except Exception:
        return []

    results: list[dict] = []
    pattern = re.compile(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippets = re.findall(
        r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
        page,
        re.IGNORECASE | re.DOTALL,
    )
    for index, (href, title_html) in enumerate(pattern.findall(page)):
        url = _ddg_url(href)
        if not url.lower().startswith(("http://", "https://")):
            continue
        snippet = snippets[index] if index < len(snippets) else ""
        results.append(
            {
                "title": _strip_tags(title_html)[:200],
                "url": url,
                "content": _strip_tags(snippet)[:1400],
            }
        )
        if len(results) >= max_results:
            break
    return results


def _private_host(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if host in ("localhost", "0.0.0.0", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def _fetch_html(url: str) -> dict:
    try:
        with httpx.Client(timeout=WEB_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={"User-Agent": _UA, "Accept-Language": "id-ID,id;q=0.9,en;q=0.8"},
            )
        if resp.status_code >= 400:
            raise WebError(f"HTTP {resp.status_code} saat mengambil {url}")
        if _private_host(resp.url.host or ""):
            raise WebError("redirect ke alamat lokal/privat diblokir")
        raw = resp.text
    except WebError:
        raise
    except Exception as e:
        raise WebError(f"gagal mengambil {url}: {e}") from e

    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    title = _strip_tags(title_match.group(1)) if title_match else url
    links = []
    for href in re.findall(r'href=["\'](https?://[^"\']+)', raw, re.IGNORECASE):
        href = html_lib.unescape(href)
        if href not in links:
            links.append(href)
        if len(links) >= 40:
            break
    return {
        "title": title[:200] or url,
        "url": str(resp.url),
        "content": _strip_tags(raw)[:12000],
        "links": links,
    }


# --------------------------------------------------------------------- web tools


# The app wires this to PrivacyManager.allows_cloud(). Until then it fails closed.
_cloud_allowed = lambda: False


def set_cloud_gate(fn) -> None:
    """Connect web search to the cloud policy (CLOUD_ENABLED). Queries sent out are cloud processing."""
    global _cloud_allowed
    _cloud_allowed = fn


def _require_cloud(what: str) -> None:
    try:
        allowed = bool(_cloud_allowed())
    except Exception:
        allowed = False
    if not allowed:
        raise WebError(f"{what} memakai layanan cloud, tetapi CLOUD_ENABLED=false di .env.")


def web_search(query: str, max_results: int = 5) -> dict:
    """Cari di web lewat DuckDuckGo. Hanya jika cloud diizinkan (CLOUD_ENABLED).

    Return: {"query", "source", "results": [{"title","url","content"}]}
    """
    _require_cloud("Pencarian web")
    q = str(query or "").strip()
    if not q:
        raise WebError("query kosong")
    if len(q) > 500:
        q = q[:500]
    try:
        limit = max(1, min(10, int(max_results or 5)))
    except (TypeError, ValueError):
        limit = 5

    results = _ddg_search(q, limit)
    if not results:
        raise WebError("pencarian web tidak mengembalikan hasil")

    return {"query": q, "source": "duckduckgo", "results": results[:limit]}


def web_fetch(url: str) -> dict:
    """Ambil isi satu halaman web (judul, teks, link)."""
    target = str(url or "").strip()
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise WebError("hanya URL http/https yang diizinkan")
    if _private_host(parsed.hostname or ""):
        raise WebError("URL lokal/privat tidak diizinkan untuk web_fetch")

    page = _fetch_html(target)
    page["source"] = "html"
    return page
