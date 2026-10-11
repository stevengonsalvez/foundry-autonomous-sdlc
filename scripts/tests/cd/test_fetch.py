from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from scripts.cd.fetch import cache_busted


def test_every_call_gives_a_url_nobody_has_asked_for_before() -> None:
    urls = {cache_busted("https://o.github.io/r/staging/build.json") for _ in range(200)}
    assert len(urls) == 200
    assert all(urlsplit(u).path == "/r/staging/build.json" for u in urls)
    assert all(len(parse_qs(urlsplit(u).query)["cb"][0]) == 32 for u in urls)


def test_an_existing_query_is_kept_and_a_fragment_stays_last() -> None:
    url = cache_busted("https://x/y?a=1#frag")
    parts = urlsplit(url)
    assert parts.fragment == "frag"
    assert parse_qs(parts.query)["a"] == ["1"] and "cb" in parse_qs(parts.query)
