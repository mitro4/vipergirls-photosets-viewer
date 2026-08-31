"""Host identification via URL substring (hosts/registry.py)."""
from app.hosts.registry import HOST_TABLE, identify_host


def test_all_hosts_identified():
    for host_id, name, substr in HOST_TABLE:
        assert identify_host(f"https://{substr}/some/page.html") == name
        assert identify_host(f"https://www.{substr}/img/1.jpg") == name


def test_pixhost_substring_covers_both_mirrors():
    assert identify_host("https://pixhost.to/show/abc/1.jpg") == "pixhost.to"
    assert identify_host("https://pixhost.cc/show/abc/1.jpg") == "pixhost.to"
    assert identify_host("https://img2.pixhost.to/images/abc/1.jpg") == "pixhost.to"
    assert identify_host("https://t2.pixhost.cc/thumbs/abc/1.jpg") == "pixhost.to"


def test_unknown_host_returns_empty():
    assert identify_host("https://example.com/image.jpg") == ""
    assert identify_host("") == ""


def test_no_cross_substring_collisions():
    # Every substring must be unique — identify_host returns the FIRST match.
    subs = [s for _, _, s in HOST_TABLE]
    assert len(subs) == len(set(subs))
    assert len(HOST_TABLE) == 16
