"""Proxy URL composition + log redaction (settings_service)."""
from app.services.settings_service import get_proxy_url, redact_proxy, update_settings


async def _set_proxy(**kw) -> None:
    await update_settings(kw)


async def test_disabled_proxy_returns_empty_even_with_url_stored():
    await _set_proxy(
        proxy_enabled=False, proxy_url="socks5://1.2.3.4:1080",
        proxy_username="u", proxy_password="p",
    )
    assert await get_proxy_url() == ""


async def test_enabled_without_url_returns_empty():
    await _set_proxy(proxy_enabled=True, proxy_url="")
    assert await get_proxy_url() == ""


async def test_bare_host_defaults_to_socks5h():
    await _set_proxy(proxy_enabled=True, proxy_url="127.0.0.1:9050")
    assert await get_proxy_url() == "socks5h://127.0.0.1:9050"


async def test_socks5_normalised_to_socks5h():
    await _set_proxy(proxy_enabled=True, proxy_url="socks5://5.6.7.8:1080")
    assert await get_proxy_url() == "socks5h://5.6.7.8:1080"


async def test_http_scheme_preserved():
    await _set_proxy(proxy_enabled=True, proxy_url="http://corp-proxy:3128")
    assert await get_proxy_url() == "http://corp-proxy:3128"


async def test_socks5h_preserved_as_is():
    await _set_proxy(proxy_enabled=True, proxy_url="socks5h://h:1080")
    assert await get_proxy_url() == "socks5h://h:1080"


async def test_credentials_url_encoded_and_embedded():
    await _set_proxy(
        proxy_enabled=True,
        proxy_url="socks5://proxy.example:1080",
        proxy_username="u ser",
        proxy_password="p@ss:word",
    )
    url = await get_proxy_url()
    assert url == "socks5h://u%20ser:p%40ss%3Aword@proxy.example:1080"


async def test_username_only_without_password():
    await _set_proxy(
        proxy_enabled=True, proxy_url="socks5://h:1080",
        proxy_username="alice", proxy_password="",
    )
    assert await get_proxy_url() == "socks5h://alice@h:1080"


def test_redact_proxy_strips_credentials():
    assert redact_proxy("socks5h://user:pass@host:1080") == "socks5h://host:1080"
    assert redact_proxy("socks5h://user@host:1080") == "socks5h://host:1080"


def test_redact_proxy_keeps_clean_urls():
    assert redact_proxy("socks5h://host:1080") == "socks5h://host:1080"
    assert redact_proxy("") == ""
    assert redact_proxy("notaurl") == "notaurl"


def test_redact_proxy_preserves_path():
    assert (
        redact_proxy("http://u:p@h.tld/some/path?q=1")
        == "http://h.tld/some/path?q=1"
    )
