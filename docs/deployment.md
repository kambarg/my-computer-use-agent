# Deployment

Requirement 3 asked for Docker for local development **and** remote
deployment. Both use the same images. The production file is an
overlay, not a second architecture.

## Local

```bash
cp .env.example .env
# set ANTHROPIC_API_KEY
docker compose up --build
```

`compose.yaml` starts Postgres and the backend, builds
`computer-use-worker:local`, and exits that one-shot service. The
backend mounts `/var/run/docker.sock` and starts **one container per
session** on the `computer-use_agent` network.

| Published on the host | Not published |
| --- | --- |
| `8000` (backend: demo UI, API, SSE, VNC proxy) | worker `6080` / `5900`, Postgres `5432` |

`ENABLE_DOCS=1`, so Swagger is at `http://localhost:8000/docs`. The
demo client is `/`.

Postgres user/password/database default to `app` / `app` / `app`.

## Production overlay

```bash
cp .env.example .env
# set ANTHROPIC_API_KEY and POSTGRES_PASSWORD
docker compose -f compose.yaml -f compose.prod.yaml up --build -d
```

`compose.prod.yaml` keeps spawn-on-demand and the private worker
network. It changes the things that would be reckless on a shared
host:

| Local | Production overlay |
| --- | --- |
| `ENABLE_DOCS=1` (`/docs`, `/redoc`, `/openapi.json`) | `ENABLE_DOCS=0` (those routes 404) |
| `8000` on all interfaces | `127.0.0.1:8000` only |
| Postgres password `app` | `POSTGRES_PASSWORD` required |
| Blobs live in the backend container | `blobs` volume at `/app/data/blobs` |
| No memory cap | Postgres 512MB, backend 1GB |
| Default json logs | Rotated json-file logs (10MB × 3) |

Put a TLS reverse proxy in front of `127.0.0.1:8000` if the host is
reachable from a network you do not control.

`POSTGRES_PASSWORD` is applied on **first** Postgres boot. Changing it
later does nothing until you remove the `pgdata` volume.

## Environment

| Variable | Default | Role |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | empty | Passed into each spawned worker |
| `API_PROVIDER` | `anthropic` | `anthropic`, `bedrock`, or `vertex` |
| `POSTGRES_PASSWORD` | `app` locally; required in prod | Database password |
| `ENABLE_DOCS` | `1` if unset | FastAPI Swagger / OpenAPI |
| `PROVISION_WORKERS` | `1` in Compose | Spawn via Docker; `0` + `WORKER_URLS` is the test/fake path |
| `WORKER_IMAGE` | `computer-use-worker:local` | Image the backend `docker run`s |
| `WORKER_NETWORK` | `computer-use_agent` | Must match the Compose network name |
| `MAX_WORKERS` | `8` | Safety cap, not a YAML pool |
| `WORKER_READY_TIMEOUT` | `90` | Seconds to wait for `/health` after `docker run` |
| `WORKER_BASE_IMAGE` | upstream `computer-use-demo-latest` | `FROM` for the worker image |
| `DATABASE_URL` | SQLite on the host; Postgres in Compose | SQLAlchemy async URL |
| `BLOB_DIR` | `./data/blobs` | Screenshot store |

Never commit `.env`. `.env.example` is the template.

Pin `WORKER_BASE_IMAGE` to a digest if you need a reproducible worker
image. The published `computer-use-demo-latest` tag is mutable.

## What still needs a host Docker daemon

The backend creates containers. That requires `docker.sock`, which is
effectively host root: anything that can talk to that socket can start
privileged containers and mount the host filesystem.

This overlay does not fix that. Docker-in-Docker or a mediated socket
proxy would. For a single-machine demo it is the same trust model as
"the operator can run Docker." Do not expose the backend's API (or
the socket) to untrusted clients.

Each worker is a full Ubuntu desktop plus Firefox. Budget on the order
of 1–2GB RAM and a share of CPU per concurrent session, on top of the
backend and Postgres limits above. `MAX_WORKERS` is the backstop.

## Without Compose

The pytest suite uses a fake worker and SQLite. To drive the real API
on the host without Docker provisioning:

```bash
ENABLE_DOCS=1 WORKER_URLS=http://127.0.0.1:8001 \
  .venv/bin/uvicorn backend.main:app
```

That path is for tests and UI work. It is not a production topology
and it does not give you Firefox or a desktop.

## Operations notes

- **Delete sessions.** A session holds its worker until `DELETE
  /sessions/{id}`. There is no idle timeout; forgotten rows leak
  desktops until they are deleted or you hit `MAX_WORKERS`.
- **No migrations.** Tables are created with `create_all` on startup.
  Fine for a demo; not fine for a database you already care about.
- **Health.** Backend `GET /health` is liveness only. Worker `/health`
  is what the provisioner waits on before binding the session.
- **Rebuild.** `docker compose up --build` rebuilds backend and the
  worker image. Already-running session containers keep the old image
  until those sessions are deleted.
