import httpx
import pytest

from app.services.s2_client import (
    PAPER_FIELDS,
    S2AuthError,
    S2BadRequest,
    S2Client,
    S2NotFound,
    S2TransientError,
    _parse_retry_after,
)

BASE = "https://s2.test/graph/v1"
REAL_BACKOFF = S2Client._backoff  # captured before the autouse fixture patches it


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    """Record backoff requests instead of sleeping between retries."""
    delays = []

    def fake_backoff(attempt, retry_after):
        delays.append((attempt, retry_after))
        return 0

    monkeypatch.setattr(S2Client, "_backoff", staticmethod(fake_backoff))
    return delays


def make_client(responses, api_key=None, max_attempts=3):
    """responses: list of httpx.Response or exception classes, returned in order. Records requests."""
    seen = []

    def handler(request):
        seen.append(request)
        item = responses[min(len(seen), len(responses)) - 1]
        if isinstance(item, type) and issubclass(item, Exception):
            raise item("simulated", request=request)
        return item

    client = S2Client(BASE, api_key, min_interval=0, max_attempts=max_attempts,
                      transport=httpx.MockTransport(handler))
    return client, seen


async def test_search_returns_data_and_sends_query_params():
    client, seen = make_client([httpx.Response(200, json={"data": [{"paperId": "p1"}]})])
    assert await client.search("graph transformers", limit=5) == [{"paperId": "p1"}]
    params = seen[0].url.params
    assert seen[0].url.path == "/graph/v1/paper/search"
    assert params["query"] == "graph transformers" and params["limit"] == "5"
    assert params["fields"] == PAPER_FIELDS


async def test_search_with_missing_data_returns_empty_list():
    client, _ = make_client([httpx.Response(200, json={"total": 0})])
    assert await client.search("nothing") == []


async def test_lookup_uses_identifier_in_path():
    client, seen = make_client([httpx.Response(200, json={"paperId": "x"})])
    await client.lookup("arXiv:2106.09685")
    assert seen[0].url.path == "/graph/v1/paper/arXiv:2106.09685"


async def test_api_key_header_sent_only_when_set():
    with_key, seen_with = make_client([httpx.Response(200, json={})], api_key="secret")
    without, seen_without = make_client([httpx.Response(200, json={})])
    await with_key.get("/x")
    await without.get("/x")
    assert seen_with[0].headers["x-api-key"] == "secret"
    assert "x-api-key" not in seen_without[0].headers


async def test_retries_429_then_succeeds_and_honours_retry_after(no_backoff):
    client, seen = make_client([
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(200, json={"ok": True}),
    ])
    assert await client.get("/x") == {"ok": True}
    assert len(seen) == 2
    assert no_backoff == [(1, 7.0)]


@pytest.mark.parametrize(
    "responses, reason",
    [
        ([httpx.Response(429)], "s2_rate_limited"),
        ([httpx.Response(503)], "s2_http_503"),
        ([httpx.ReadTimeout], "s2_timeout"),
        ([httpx.ConnectError], "s2_network_error"),
    ],
)
async def test_transient_failures_exhaust_retries(responses, reason):
    client, seen = make_client(responses, max_attempts=3)
    with pytest.raises(S2TransientError) as exc:
        await client.get("/x")
    assert exc.value.reason == reason
    assert len(seen) == 3


@pytest.mark.parametrize(
    "status, error",
    [(401, S2AuthError), (403, S2AuthError), (404, S2NotFound), (400, S2BadRequest), (422, S2BadRequest)],
)
async def test_client_errors_raise_immediately_without_retry(status, error):
    client, seen = make_client([httpx.Response(status, text="nope")])
    with pytest.raises(error):
        await client.get("/x")
    assert len(seen) == 1


def test_backoff_grows_and_respects_retry_after():
    # Requirement (HW1 plan): exponential backoff, honouring Retry-After.
    backoff = REAL_BACKOFF
    first, second, third = backoff(1, None), backoff(2, None), backoff(3, None)
    assert 0 < first < second < third                     # waits grow between attempts
    assert backoff(1, 10) >= 10                           # a server-requested wait is respected
    # Not asserted: the exact base delays, the jitter, and the cap on very long Retry-After values.
    # The requirement doesn't specify them; they are the code's choices.


@pytest.mark.parametrize("value, expected", [("5", 5.0), ("1.5", 1.5), (None, None), ("", None),
                                             ("Wed, 21 Oct 2026 07:28:00 GMT", None)])
def test_parse_retry_after(value, expected):
    assert _parse_retry_after(value) == expected


async def test_throttle_spaces_out_calls(monkeypatch):
    from app.services import s2_client

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(s2_client.asyncio, "sleep", fake_sleep)
    client = S2Client(BASE, min_interval=1.0)
    await client._throttle()
    await client._throttle()
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 1.0
