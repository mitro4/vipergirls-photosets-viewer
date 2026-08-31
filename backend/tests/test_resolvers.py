"""Pure URL-transform resolvers (no HTTP) from hosts/base.py."""
import pytest

from app.hosts.base import (
    _ensure_scheme,
    _filename_from_url,
    resolve_imx,
    resolve_imx_thumb,
    resolve_pixhost,
)


class TestResolveImx:
    def test_thumb_prefix_to_direct(self):
        assert (
            resolve_imx("https://t.imx.to/t/012/abc.jpg")
            == "https://image.imx.to/u/i/012/abc.jpg"
        )

    def test_all_known_prefixes(self):
        prefixes = [
            "https://imx.to/u/t",
            "https://imx.to/upload/small/",
            "https://i.imx.to/t/",
        ]
        for p in prefixes:
            assert resolve_imx(f"{p}file.png").startswith("https://image.imx.to/u/i/")

    def test_http_upgraded_to_https(self):
        assert (
            resolve_imx("http://t.imx.to/t/x.jpg")
            == "https://image.imx.to/u/i/x.jpg"
        )

    def test_already_direct_unchanged(self):
        url = "https://image.imx.to/u/i/pic.jpg"
        assert resolve_imx(url) == url

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            resolve_imx("https://example.com/t/x.jpg")


class TestResolveImxThumb:
    def test_rewrites_to_thumb_cdn(self):
        assert (
            resolve_imx_thumb("https://t.imx.to/t/012/abc.jpg")
            == "https://image.imx.to/u/t/012/abc.jpg"
        )

    def test_already_cdn_unchanged(self):
        url = "https://image.imx.to/u/t/012/abc.jpg"
        assert resolve_imx_thumb(url) == url

    def test_http_upgraded(self):
        assert (
            resolve_imx_thumb("http://imx.to/upload/small/x.jpg")
            == "https://image.imx.to/u/t/x.jpg"
        )

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            resolve_imx_thumb("https://example.com/x.jpg")


class TestResolvePixhost:
    def test_show_page_to_direct(self):
        assert (
            resolve_pixhost("https://pixhost.to/show/abc/1.jpg")
            == "https://img2.pixhost.to/images/abc/1.jpg"
        )

    def test_both_mirrors_and_www(self):
        for prefix in (
            "https://www.pixhost.to/show/",
            "https://pixhost.cc/show/",
            "https://www.pixhost.cc/show/",
        ):
            assert resolve_pixhost(f"{prefix}a/b.jpg") == "https://img2.pixhost.to/images/a/b.jpg"

    def test_already_direct_unchanged(self):
        url = "https://img2.pixhost.to/images/abc/1.jpg"
        assert resolve_pixhost(url) == url
        assert resolve_pixhost("https://img101.pixhost.cc/images/a/1.jpg") == (
            "https://img101.pixhost.cc/images/a/1.jpg"
        )

    def test_http_upgraded_to_https(self):
        assert (
            resolve_pixhost("http://pixhost.to/show/a/1.jpg")
            == "https://img2.pixhost.to/images/a/1.jpg"
        )

    def test_unrecognized_raises(self):
        with pytest.raises(ValueError):
            resolve_pixhost("https://pixhost.to/gallery/abc")


class TestHelpers:
    def test_filename_from_url_strips_query_and_fragment(self):
        assert _filename_from_url("https://h.tld/dir/pic.jpg?x=1#frag") == "pic.jpg"

    def test_filename_from_url_defaults(self):
        assert _filename_from_url("https://h.tld/") == "image"
        assert _filename_from_url("https://h.tld/?x=1") == "image"

    def test_ensure_scheme(self):
        assert _ensure_scheme("//h.tld/x.jpg") == "https://h.tld/x.jpg"
        assert _ensure_scheme("https://h.tld/x.jpg") == "https://h.tld/x.jpg"
        assert _ensure_scheme("http://h.tld/x.jpg") == "http://h.tld/x.jpg"
