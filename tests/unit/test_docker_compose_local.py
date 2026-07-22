from pathlib import Path


def test_dev_dockerfile_installs_rag_tokenizer_nltk_data() -> None:
    dockerfile = Path("docker/app/Dockerfile.dev").read_text(encoding="utf-8")

    assert "NLTK_DATA=/usr/local/share/nltk_data" in dockerfile
    assert 'nltk.download("punkt_tab"' in dockerfile
    assert 'nltk.download("wordnet"' in dockerfile
    assert 'nltk.data.find("tokenizers/punkt_tab/english")' in dockerfile
    assert 'WordNetLemmatizer().lemmatize("documents")' in dockerfile
    assert "build_chunk_text_fields(" in dockerfile


def test_observability_app_sources_local_env_before_uvicorn() -> None:
    compose = Path("docker/compose.local.yml").read_text(encoding="utf-8")

    assert "data/local.env" in compose
    assert ". data/local.env" in compose
    assert "exec uvicorn ragflow_lite.app:app" in compose
