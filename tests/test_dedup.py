from dedup.url import normalize_url, url_hash


def test_normalize_strips_trailing_slash_and_fragment() -> None:
    assert normalize_url("https://Example.com/a/") == "https://example.com/a"
    assert url_hash("https://a.com/x/") == url_hash("https://a.com/x")


def test_different_paths_different_hash() -> None:
    assert url_hash("https://a.com/1") != url_hash("https://a.com/2")
