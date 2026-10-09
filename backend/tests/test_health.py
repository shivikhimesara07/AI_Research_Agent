def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_search_uses_injected_service(client, fake_search):
    # /health touches no dependency, so this is the test that proves the override seam works.
    resp = client.get("/api/search", params={"q": "transformers"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "semantic_scholar"
    assert body["results"][0]["title"] == "Attention Is All You Need"
    assert fake_search.calls == [("transformers", 20)]
