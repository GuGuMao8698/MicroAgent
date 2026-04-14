"""Dataset API 集成测试。"""

from __future__ import annotations

from uuid import uuid4

_CONTENT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
}


class FakeArkClient:
    def __init__(self) -> None:
        self.multimodal_embeddings = FakeArkMultimodalEmbeddingsAPI()


class FakeArkMultimodalEmbeddingsAPI:
    def __init__(self) -> None:
        self.calls: list = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = kwargs["input"][0]["text"]
        dimensions = kwargs.get("dimensions")
        size = dimensions or 8
        vector = [0.0] * size
        vector[0] = 4.0
        vector[1] = 1.0
        return type(
            "FakeResponse",
            (),
            {"data": type("FakeData", (), {"embedding": vector})()},
        )()


def _install_fake_ark_client(client):
    services = client.app.state.services
    services.ingestion_pipeline.embedder.client = FakeArkClient()


def _unique_key() -> str:
    return f"key-{uuid4().hex}"


def _upload_txt(client, content: bytes = b"hello world", name: str = "test.txt"):
    return client.post(
        "/api/v0/documents",
        files={"file": (name, content, "text/plain")},
        headers={"Idempotency-Key": _unique_key()},
    )


# ---------------------------------------------------------------------------
# Dataset CRUD
# ---------------------------------------------------------------------------


def test_create_dataset(client) -> None:
    response = client.post(
        "/api/v0/datasets",
        json={"name": "测试数据集", "description": "描述"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["dataset_id"].startswith("ds_")
    assert payload["name"] == "测试数据集"
    assert payload["description"] == "描述"
    assert payload["created_at"]


def test_create_dataset_duplicate_name_returns_409(client) -> None:
    client.post("/api/v0/datasets", json={"name": "唯一", "description": ""})
    response = client.post("/api/v0/datasets", json={"name": "唯一", "description": ""})
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_create_dataset_blank_name_returns_422(client) -> None:
    response = client.post("/api/v0/datasets", json={"name": "   ", "description": ""})
    assert response.status_code == 422


def test_list_datasets(client) -> None:
    client.post("/api/v0/datasets", json={"name": "A", "description": ""})
    client.post("/api/v0/datasets", json={"name": "B", "description": ""})

    response = client.get("/api/v0/datasets")
    assert response.status_code == 200
    names = {ds["name"] for ds in response.json()["datasets"]}
    assert names == {"A", "B"}


def test_list_datasets_empty(client) -> None:
    response = client.get("/api/v0/datasets")
    assert response.status_code == 200
    assert response.json() == {"datasets": []}


def test_get_dataset(client) -> None:
    create_response = client.post(
        "/api/v0/datasets", json={"name": "查询", "description": "描述"}
    )
    dataset_id = create_response.json()["dataset_id"]

    response = client.get(f"/api/v0/datasets/{dataset_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "查询"


def test_get_dataset_not_found_returns_404(client) -> None:
    response = client.get("/api/v0/datasets/ds_nonexistent")
    assert response.status_code == 404


def test_delete_dataset(client) -> None:
    create_response = client.post(
        "/api/v0/datasets", json={"name": "删除", "description": ""}
    )
    dataset_id = create_response.json()["dataset_id"]

    response = client.delete(f"/api/v0/datasets/{dataset_id}")
    assert response.status_code == 204

    # 确认已删除
    assert client.get(f"/api/v0/datasets/{dataset_id}").status_code == 404


def test_delete_non_empty_dataset_returns_409(client) -> None:
    _install_fake_ark_client(client)
    create_response = client.post(
        "/api/v0/datasets", json={"name": "非空", "description": ""}
    )
    dataset_id = create_response.json()["dataset_id"]

    # 上传并绑定文档
    upload_response = _upload_txt(client)
    document_id = upload_response.json()["document_id"]
    client.patch(
        f"/api/v0/documents/{document_id}/dataset",
        json={"dataset_id": dataset_id},
    )

    response = client.delete(f"/api/v0/datasets/{dataset_id}")
    assert response.status_code == 409
    assert "not empty" in response.json()["detail"].lower()


def test_delete_dataset_not_found_returns_404(client) -> None:
    response = client.delete("/api/v0/datasets/ds_nonexistent")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Upload with dataset binding
# ---------------------------------------------------------------------------


def test_upload_document_with_dataset_binding(client) -> None:
    _install_fake_ark_client(client)
    create_response = client.post(
        "/api/v0/datasets", json={"name": "上传绑定", "description": ""}
    )
    dataset_id = create_response.json()["dataset_id"]

    upload_response = client.post(
        "/api/v0/documents",
        data={"dataset_id": dataset_id},
        files={"file": ("test.txt", b"hello world", "text/plain")},
        headers={"Idempotency-Key": _unique_key()},
    )
    assert upload_response.status_code == 202
    payload = upload_response.json()
    document_id = payload["document_id"]
    assert upload_response.headers["Location"] == f"/api/v0/documents/{document_id}"
    assert payload["status"] == "queued"
    assert payload["dataset_id"] == dataset_id


def test_upload_document_without_dataset_binding(client) -> None:
    _install_fake_ark_client(client)
    upload_response = _upload_txt(client)
    assert upload_response.status_code == 202
    assert upload_response.json()["dataset_id"] is None


# ---------------------------------------------------------------------------
# Document dataset rebind / unbind
# ---------------------------------------------------------------------------


def test_rebind_document_to_different_dataset(client) -> None:
    _install_fake_ark_client(client)
    ds1 = client.post(
        "/api/v0/datasets", json={"name": "旧", "description": ""}
    ).json()["dataset_id"]
    ds2 = client.post(
        "/api/v0/datasets", json={"name": "新", "description": ""}
    ).json()["dataset_id"]

    upload_response = _upload_txt(client)
    document_id = upload_response.json()["document_id"]

    # 绑定到 ds1
    client.patch(
        f"/api/v0/documents/{document_id}/dataset",
        json={"dataset_id": ds1},
    )
    doc = client.get(f"/api/v0/documents/{document_id}").json()
    assert doc["dataset_id"] == ds1

    # 重绑到 ds2
    client.patch(
        f"/api/v0/documents/{document_id}/dataset",
        json={"dataset_id": ds2},
    )
    doc = client.get(f"/api/v0/documents/{document_id}").json()
    assert doc["dataset_id"] == ds2


def test_unbind_document_from_dataset(client) -> None:
    _install_fake_ark_client(client)
    ds = client.post(
        "/api/v0/datasets", json={"name": "解绑", "description": ""}
    ).json()["dataset_id"]

    upload_response = _upload_txt(client)
    document_id = upload_response.json()["document_id"]

    client.patch(
        f"/api/v0/documents/{document_id}/dataset",
        json={"dataset_id": ds},
    )
    # 解绑
    client.patch(
        f"/api/v0/documents/{document_id}/dataset",
        json={"dataset_id": None},
    )
    doc = client.get(f"/api/v0/documents/{document_id}").json()
    assert doc["dataset_id"] is None


# ---------------------------------------------------------------------------
# GET /documents?dataset_id= filter
# ---------------------------------------------------------------------------


def test_list_documents_filtered_by_dataset(client) -> None:
    _install_fake_ark_client(client)
    ds = client.post(
        "/api/v0/datasets", json={"name": "过滤", "description": ""}
    ).json()["dataset_id"]

    # 上传两份文档，只绑定第一份
    r1 = _upload_txt(client, b"doc1 content", "a.txt")
    r2 = _upload_txt(client, b"doc2 content", "b.txt")
    doc1_id = r1.json()["document_id"]
    _ = r2.json()["document_id"]

    client.patch(
        f"/api/v0/documents/{doc1_id}/dataset",
        json={"dataset_id": ds},
    )

    response = client.get(f"/api/v0/documents?dataset_id={ds}")
    assert response.status_code == 200
    docs = response.json()["documents"]
    assert len(docs) == 1
    assert docs[0]["document_id"] == doc1_id


def test_list_documents_filter_unknown_dataset_returns_404(client) -> None:
    response = client.get("/api/v0/documents?dataset_id=ds_nonexistent")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Document list/detail response includes dataset_id
# ---------------------------------------------------------------------------


def test_document_list_response_includes_dataset_id(client) -> None:
    _install_fake_ark_client(client)
    ds = client.post(
        "/api/v0/datasets", json={"name": "列表", "description": ""}
    ).json()["dataset_id"]

    r = _upload_txt(client)
    doc_id = r.json()["document_id"]
    client.patch(
        f"/api/v0/documents/{doc_id}/dataset",
        json={"dataset_id": ds},
    )

    response = client.get("/api/v0/documents")
    docs = response.json()["documents"]
    target = [d for d in docs if d["document_id"] == doc_id]
    assert len(target) == 1
    assert target[0]["dataset_id"] == ds


def test_document_detail_response_includes_dataset_id(client) -> None:
    _install_fake_ark_client(client)
    ds = client.post(
        "/api/v0/datasets", json={"name": "详情", "description": ""}
    ).json()["dataset_id"]

    r = _upload_txt(client)
    doc_id = r.json()["document_id"]
    client.patch(
        f"/api/v0/documents/{doc_id}/dataset",
        json={"dataset_id": ds},
    )

    response = client.get(f"/api/v0/documents/{doc_id}")
    assert response.status_code == 200
    assert response.json()["dataset_id"] == ds


def test_document_detail_unbound_has_null_dataset_id(client) -> None:
    _install_fake_ark_client(client)
    r = _upload_txt(client)
    doc_id = r.json()["document_id"]

    response = client.get(f"/api/v0/documents/{doc_id}")
    assert response.status_code == 200
    assert response.json()["dataset_id"] is None
