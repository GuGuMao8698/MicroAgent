# CONTRACTS.md

## Scope
Local-only development, observability, and smoke testing. Not for production, CI, or release.

## Local Compose Entrypoint
[compose.local.yml](compose.local.yml)

## Service Graph

| Service | Profile | Image | Ports | Volumes | Depends On |
|---|---|---|---|---|---|
| `infinity` | (base) | `infiniflow/infinity:v0.7.0-dev5` | `127.0.0.1:23817`, `127.0.0.1:23820` | `/tmp/ragflow-lite-infinity-data:/var/infinity` (host tmpfs) | — |
| `app` | `observability` | built from [app/Dockerfile.dev](app/Dockerfile.dev) | `8000` | `..:/workspace` (bind mount) | `infinity` |
| `prometheus` | `observability` | `prom/prometheus:v3.11.1` | `9090` | [prometheus/prometheus.yml](prometheus/prometheus.yml) (ro) | `app` |
| `loki` | `observability` | `grafana/loki:3.6.3` | `3100` | [loki/config.yml](loki/config.yml) (ro), named `loki-data` | — |
| `alloy` | `observability` | `grafana/alloy:latest` | — | [alloy/config.alloy](alloy/config.alloy) (ro), `/var/run/docker.sock` | `loki`, `app` |
| `grafana` | `observability` | `grafana/grafana:latest` | `3000` | named `grafana-data`, [grafana/provisioning](grafana/provisioning) (ro) | `prometheus`, `loki` |

## App Service Details

- **Working dir:** `/workspace`
- **Command:** `sh -lc 'set -a; . data/local.env; set +a; exec uvicorn ragflow_lite.app:app --host 0.0.0.0 --port 8000 --reload'`

## App Environment Variables (source: compose.local.yml)

| Variable | Value | Source |
|---|---|---|
| `PYTHONPATH` | `/workspace/src` | hardcoded |
| `DEEPSEEK_API_KEY` | from `data/local.env` | local env file |
| `ARK_API_KEY` | from `data/local.env` | local env file |
| `ARK_EMBEDDING_MODEL` | from `data/local.env` | local env file |
| `RAGFLOW_LITE_LOG_LEVEL` | `INFO` | hardcoded |
| `RAGFLOW_LITE_LOG_FORMAT` | `json` | hardcoded |
| `RAGFLOW_LITE_METRICS_ENABLED` | `true` | hardcoded |
| `RAGFLOW_LITE_INFINITY_HOST` | `infinity` | service name |
| `RAGFLOW_LITE_INFINITY_PORT` | `23817` | hardcoded |

### Provider Env Note
[src/ragflow_lite/config/settings.py](../src/ragflow_lite/config/settings.py) reads provider credentials from the process environment. The local observability app sources `data/local.env` before starting Uvicorn without committing secrets.

## Grafana Defaults
- Admin user/password: `admin` / `admin`
- Sign-up disabled

## Dockerfile.dev

Local development image only. Based on `python:3.13-slim`, installs `build-essential`, `gfortran`, `libopenblas-dev`, `pkg-config`, copies `pyproject.toml` and `src`, runs `pip install -e .`.

It also sets `NLTK_DATA=/usr/local/share/nltk_data`, downloads `punkt_tab` and
`wordnet`, then verifies both the NLTK resources and a real
`build_chunk_text_fields(...)` call during the image build. The app requires
these resources when `infinity.rag_tokenizer.RagTokenizer` builds `*_tks` chunk
text fields for Infinity full-text indexing.

## Artifact/Secrets Rules
Do not commit `.env`, secrets, compose runtime artifacts, screenshots, or local volume contents.
