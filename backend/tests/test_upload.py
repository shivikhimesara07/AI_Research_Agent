PDF_A = b"%PDF-1.7\nfake paper A\n%%EOF"
PDF_B = b"%PDF-1.7\nfake paper B\n%%EOF"


def _upload(client, data, name="paper.pdf"):
    return client.post("/api/papers/upload", files={"file": (name, data, "application/pdf")})


def test_duplicate_upload_returns_existing_paper(client, fake_llm):
    first = _upload(client, PDF_A)
    assert first.status_code == 201

    second = _upload(client, PDF_A, name="renamed-copy.pdf")
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert len(client.get("/api/papers").json()) == 1
    # The duplicate is detected before extraction, so the LLM isn't called a second time.
    assert [c[0] for c in fake_llm.calls] == ["extract_metadata"]


def test_different_pdfs_create_separate_papers(client):
    a = _upload(client, PDF_A)
    b = _upload(client, PDF_B)
    assert (a.status_code, b.status_code) == (201, 201)
    assert a.json()["id"] != b.json()["id"]
    assert len(client.get("/api/papers").json()) == 2


def test_reupload_after_delete_creates_new_paper(client):
    first = _upload(client, PDF_A)
    assert client.delete(f"/api/papers/{first.json()['id']}").status_code == 204
    again = _upload(client, PDF_A)
    assert again.status_code == 201
    assert len(client.get("/api/papers").json()) == 1
