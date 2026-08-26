# Documentation

The README is the 60-second orientation: what this is, how to run it,
where the code lives. These pages are the design record.

| Document | Contents |
| --- | --- |
| [architecture.md](architecture.md) | Boundary with `computer-use-demo`, runtime topology, session manager, database, streaming, VNC, frontend, Docker |
| [agent-loop.md](agent-loop.md) | What `sampling_loop()` does, its callbacks, and where the worker attaches |
| [api-design.md](api-design.md) | Public HTTP API, SSE event schema, error codes; internal worker API |
| [deployment.md](deployment.md) | Local Compose, production overlay, `ENABLE_DOCS`, secrets, `docker.sock` |

The demo UI is the HTML client at `/`. FastAPI's Swagger UI at `/docs`
is served in local Compose only; production Compose turns it off. The
HTTP contract in [api-design.md](api-design.md) is the source of truth
either way.
