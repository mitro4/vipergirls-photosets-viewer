"""vBulletin authentication service.

Logs in to the forum via vBulletin's login.php endpoint and propagates
the auth cookies to the viper.click domain so member-only threads can be
accessed through the vr.php proxy.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

from ..config import get_settings
from .http import get_http

log = logging.getLogger("viper.auth")

_state: dict[str, object] = {"logged_in": False, "username": ""}


def md5_password(plain: str) -> str:
    """Hash a plain-text password to the vBulletin MD5 hex format."""
    return hashlib.md5(plain.encode("utf-8")).hexdigest()


def _auth_file():
    """Path to the persisted-session JSON in DATA_DIR."""
    return get_settings().data_dir / "auth.json"


def _persist_auth(username: str) -> None:
    """Save the current session cookies + username so the next backend start
    can restore the logged-in state without a fresh UI login.

    Best-effort: a failure to persist only means the user re-logs in next
    restart. The file is chmod 0600 because it carries auth cookies.
    """
    cookies = get_http().cookies
    jar = getattr(cookies, "jar", None)
    cookie_list = []
    if jar is not None:
        for cookie in jar:
            if cookie.name and cookie.value and cookie.domain:
                cookie_list.append({
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path or "/",
                })
    try:
        f = _auth_file()
        f.write_text(json.dumps({"username": username, "cookies": cookie_list}))
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
        log.info("Persisted session for %s (%d cookies)", username, len(cookie_list))
    except Exception as exc:
        log.warning("Failed to persist auth session: %s", exc)


async def restore_auth() -> bool:
    """Restore a previously persisted session (cookies + username).

    Optimistic: the session is restored as-is with no startup network probe —
    a probe would either delay app start or risk discarding a still-valid
    session on a transient network blip. A server-side invalidation surfaces
    on the next auth-required action, at which point the user simply re-logs
    in and the store is refreshed.
    """
    try:
        data = json.loads(_auth_file().read_text())
    except Exception:
        return False
    username = data.get("username", "")
    saved = data.get("cookies", [])
    if not username or not saved:
        return False
    cookies = await get_http().get_cookies()
    for c in saved:
        try:
            cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path") or "/")
        except Exception:
            pass
    _state["logged_in"] = True
    _state["username"] = username
    log.info("Restored session for %s (%d cookies)", username, len(saved))
    return True


async def login(username: str, password_md5: str) -> bool:
    """POST to login.php?do=login and propagate cookies to viper.click.

    Returns True if the response cookie jar contains userid + password
    cookies (vBulletin's success indicator).
    """
    settings = get_settings()
    http = get_http()

    from ..services.settings_service import get_forum_base_url
    login_base = await get_forum_base_url()

    login_url = f"{login_base}/login.php?do=login"
    log.info("Attempting vBulletin login as %s via %s", username, login_base)

    resp = await http.post(
        login_url,
        data={
            "vb_login_username": username,
            "cookieuser": "1",
            "do": "login",
            "vb_login_md5password": password_md5,
        },
        referer=login_base + "/",
    )
    log.debug("login response status=%d, len=%d", resp.status_code, len(resp.content))

    cookies = await http.get_cookies()

    # --- Extract userid + password cookies from the jar ---
    userid_name: str | None = None
    userid_val: str | None = None
    pwd_name: str | None = None
    pwd_val: str | None = None

    jar = getattr(cookies, "jar", None)
    if jar is not None:
        for cookie in jar:
            name = cookie.name or ""
            if name.endswith("userid") and cookie.value:
                userid_name = name
                userid_val = cookie.value
            elif name.endswith("password") and cookie.value:
                pwd_name = name
                pwd_val = cookie.value

    if not userid_val or not pwd_val:
        log.warning(
            "Login failed for %s — no userid/password cookies in jar "
            "(status=%d)",
            username,
            resp.status_code,
        )
        _state["logged_in"] = False
        _state["username"] = ""
        return False

    # --- Propagate ALL auth cookies to viper.click domain ---
    # The viper.click proxy needs the same cookies to authenticate us.
    click_domain = settings.click_base_url.removeprefix("https://").removeprefix("http://").rstrip("/")
    to_copy: list[tuple[str, str]] = []
    if jar is not None:
        for cookie in jar:
            if cookie.name and cookie.value:
                to_copy.append((cookie.name, cookie.value))

    for name, value in to_copy:
        cookies.set(name, value, domain=click_domain, path="/")

    log.info(
        "Login successful as %s (cookie=%s); %d cookies propagated to %s",
        username,
        userid_name,
        len(to_copy),
        click_domain,
    )
    _state["logged_in"] = True
    _state["username"] = username
    _persist_auth(username)
    return True


async def logout() -> None:
    """Clear all session cookies and auth state."""
    http = get_http()
    cookies = await http.get_cookies()
    try:
        cookies.clear()
    except Exception:
        # Fallback: iterate and delete
        jar = getattr(cookies, "jar", None)
        if jar is not None:
            jar.clear()
    _state["logged_in"] = False
    _state["username"] = ""
    try:
        _auth_file().unlink()
    except OSError:
        pass
    log.info("Logged out, cookies cleared")


def is_logged_in() -> bool:
    return bool(_state["logged_in"])


def get_username() -> str:
    return str(_state["username"])


def get_auth_status() -> dict:
    return {
        "logged_in": _state["logged_in"],
        "username": _state["username"],
    }


async def auto_login() -> bool:
    """Attempt login on startup: env credentials first, else restore a
    previously persisted session so UI logins survive restarts."""
    settings = get_settings()
    if settings.username and settings.password_md5:
        log.info("Attempting auto-login from env credentials as %s", settings.username)
        try:
            return await login(settings.username, settings.password_md5)
        except Exception as exc:
            log.warning("Auto-login failed: %s", exc)
            return False
    return await restore_auth()
