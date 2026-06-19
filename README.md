# 🔎 Search Typeahead System

A production-style search-suggestion service (like Google's search box), built
to demonstrate clean architecture, a **distributed cache backed by consistent
hashing**, **write-behind batch updates**, and two **trending** ranking modes.

- **Frontend:** React + Vite + Tailwind CSS
- **Backend:** Python + FastAPI (API → Service → Repository layering)
- **Database:** PostgreSQL
- **Cache:** in-process distributed cache sharded over a consistent-hash ring
- **Orchestration:** Docker Compose (frontend + backend + postgres)

---

## Table of contents

1. [Project overview](#project-overview)
2. [Architecture](#architecture)
3. [Folder structure](#folder-structure)
4. [Setup instructions](#setup-instructions)
5. [API documentation](#api-documentation)
6. [Consistent hashing explanation](#consistent-hashing-explanation)
7. [Trending search explanation](#trending-search-explanation)
8. [Batch write explanation](#batch-write-explanation)
9. [Performance metrics](#performance-metrics)
10. [Design decisions & trade-offs](#design-decisions--trade-offs)
11. [Screenshots](#screenshots)

---

## Project overview

The user types into a search box; after a 300 ms debounce the frontend calls
`GET /suggest`, which returns up to **10** suggestions that match the typed
prefix, **sorted by popularity**. Submitting a search calls `POST /search`,
which returns `{"message": "Searched"}` and **increments** that query's count
(inserting it if new) — but the increment is **buffered** and flushed to the
database in batches rather than written per request. A trending panel surfaces
the most popular / most recently hot queries.

### Functional requirements coverage

| Requirement | Where |
|---|---|
| Up to 10 prefix suggestions, popularity-sorted | `suggestion_service.py`, `query_repository.get_suggestions` |
| Search submit returns `{"message":"Searched"}` | `routes.py` → `search_service.py` |
| Increment / insert query on submit | `query_repository.upsert_increment` (via batch) |
| Trending searches (2 modes) | `trending_service.py` |
| Batch writes | `batch/batch_writer.py` |
| Distributed cache + consistent hashing | `cache/consistent_hash.py`, `cache/distributed_cache.py` |
| Cache debug API | `GET /cache/debug` |

---

## Architecture

See **[docs/architecture.md](docs/architecture.md)** for the full Mermaid HLD
and **[docs/sequence-diagrams.md](docs/sequence-diagrams.md)** for sequence
diagrams (suggestion hit/miss, search submit, batch flush, cache debug).

```
User → React frontend → FastAPI API layer → Service layer
                                              ├─ SuggestionService → DistributedCache → ConsistentHashRing → {node1,node2,node3}
                                              │                       └─(miss)→ Repository → PostgreSQL
                                              ├─ SearchService → BatchWriter (buffer) → (background) Repository → PostgreSQL
                                              └─ TrendingService → Repository → PostgreSQL
```

---

## Folder structure

```text
HLD_ASSIGNMENT/
├── backend/
│   ├── app/
│   │   ├── api/            # routes.py, deps.py  (HTTP layer)
│   │   ├── services/       # suggestion / search / trending / dependencies
│   │   ├── repositories/   # query_repository.py (all SQL lives here)
│   │   ├── models/         # db_models.py (ORM), schemas.py (Pydantic)
│   │   ├── cache/          # consistent_hash.py, cache_node.py, distributed_cache.py
│   │   ├── batch/          # batch_writer.py (write-behind worker)
│   │   ├── utils/          # logging.py, metrics.py
│   │   ├── config.py
│   │   ├── database.py
│   │   └── main.py
│   ├── scripts/            # generate_dataset.py, seed_database.py
│   ├── db/schema.sql
│   ├── tests/              # test_consistent_hash.py
│   ├── Dockerfile
│   ├── entrypoint.sh
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/client.js
│   │   ├── hooks/useDebounce.js
│   │   ├── components/     # SearchBox, SuggestionDropdown, Trending
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── Dockerfile + nginx.conf
│   └── package.json, vite/tailwind/postcss configs
├── docs/                   # architecture.md, sequence-diagrams.md (Mermaid)
├── docker-compose.yml
├── Makefile
└── README.md
```

---

## Setup instructions

### Option A — Docker Compose (recommended)

```bash
docker compose up --build
```

This starts PostgreSQL, the backend (which waits for Postgres, **seeds ~120k
queries on first boot**, then serves the API), and the frontend.

- Frontend: <http://localhost:5173>
- Backend API + Swagger docs: <http://localhost:8000/docs>

> First boot seeds 120k rows (`SEED_ON_START=true` in `docker-compose.yml`).
> After the first run you can set it to `false` to skip re-seeding.

### Option B — Run locally

**Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Point at your local Postgres
export DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/typeahead"

# Generate dataset + seed (creates the schema automatically)
python -m scripts.seed_database --rows 120000

uvicorn app.main:app --reload
```

**Frontend**

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (proxies /api -> :8000)
```

**Tests**

```bash
cd backend && pytest -q
```

Convenience targets are in the [Makefile](Makefile): `make up`, `make seed`,
`make test`, `make frontend`.

---

## API documentation

### `GET /suggest?q=<prefix>`

Returns up to 10 popularity-sorted suggestions for a prefix.

```bash
curl "http://localhost:8000/suggest?q=iph"
```

```json
{
  "prefix": "iph",
  "suggestions": [
    {"query": "iphone", "count": 998123},
    {"query": "iphone 15", "count": 845010}
  ],
  "cache_hit": false,
  "node": "node2"
}
```

### `POST /search`

Buffers a count increment and returns the dummy response.

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query":"iphone"}'
```

```json
{ "message": "Searched" }
```

### `GET /trending?mode=<popularity|recency>`

```bash
curl "http://localhost:8000/trending?mode=recency"
```

```json
{
  "mode": "recency",
  "items": [
    {"query": "iphone 16", "count": 500000, "recent_count": 9000, "score": 590000.0}
  ]
}
```

### `GET /cache/debug?prefix=<prefix>`

```bash
curl "http://localhost:8000/cache/debug?prefix=iph"
```

```json
{
  "prefix": "iph",
  "node": "node2",
  "cache_hit": true,
  "ttl_remaining": 52
}
```

### `GET /metrics`

Latency percentiles, cache hit rate, DB read/write counts, per-node cache size.
See [Performance metrics](#performance-metrics).

---

## Consistent hashing explanation

> Implementation: [`backend/app/cache/consistent_hash.py`](backend/app/cache/consistent_hash.py)

### Why consistent hashing?

The naive way to shard a key across `N` cache nodes is `node = hash(key) % N`.
The problem: when `N` changes (a node is added or fails), **almost every key
re-maps** to a different node — going 3 → 4 nodes re-maps ~75% of keys. Every
re-mapped key is a cache miss, so the whole fleet stampedes the database at
once.

**Consistent hashing** places nodes and keys on the same circular keyspace
(`0 … 2³²−1`). A key is owned by the **first node found walking clockwise** from
the key's hash. Adding/removing a node only affects the keys in the arc between
that node and its predecessor.

### How key movement is minimized

When a node is removed, only the keys it owned move — on average `K/N` of all
keys (~33% with 3 nodes) instead of nearly all of them. Keys owned by other
nodes **don't move at all**. This is verified in
[`tests/test_consistent_hash.py`](backend/tests/test_consistent_hash.py)
(`test_minimal_movement_on_node_removal`).

### Virtual nodes

With a single point per physical node the ring is lumpy: one node may own a huge
arc, and removing it dumps all its keys onto **one** neighbour. We place
**150 virtual nodes** per physical node (`CACHE_VIRTUAL_NODES`). Each physical
node therefore occupies 150 small arcs spread around the ring, which:

- balances load to within a few percent (`distribution()` / the balance test), and
- spreads a removed node's keys across **all** remaining nodes, not just one.

```python
ring = ConsistentHashRing(nodes=["node1", "node2", "node3"], virtual_nodes=150)
ring.get_node("suggest:iph")   # -> "node2"
ring.add_node("node4")          # only ~1/4 of keys move
ring.remove_node("node2")       # node2's keys spread across node1/node3/node4
```

---

## Trending search explanation

> Implementation: [`backend/app/services/trending_service.py`](backend/app/services/trending_service.py)

Two ranking modes, selected via `?mode=`:

### Mode 1 — popularity (`score = count`)

Ranks by all-time count. **Stable and predictable**; reflects evergreen head
queries. **Trade-off:** slow to react — a query spiking today can't overtake a
long-established giant, so it misses "what's hot right now".

### Mode 2 — recency-aware (`score = count + recent_count * 10`)

Boosts queries with activity in the recent window. The `×10` weight lets a
smaller-but-fresh signal compete with large all-time counts. **Trade-offs:**

- `recent_count` must be periodically **decayed/reset** by a maintenance job
  (`QueryRepository.reset_recent_counts`), otherwise it slowly converges back to
  pure popularity.
- The weight (`10`) is the key knob: **higher = more responsive but noisier**,
  **lower = more stable but laggy**.

Both modes compute the score and ordering **in SQL** (`get_trending`) so only
the top-N rows leave the database.

---

## Batch write explanation

> Implementation: [`backend/app/batch/batch_writer.py`](backend/app/batch/batch_writer.py)

### The problem

Writing to Postgres on **every** `POST /search` means one row update + commit +
WAL flush per request. Under load the DB becomes the bottleneck, and most writes
are just `count += 1` on the same hot keys.

### The solution — write-behind buffering

```python
search_buffer = {}              # {query: pending_increment}
# on each search:
search_buffer[query] += 1       # in memory, no DB hit

# background worker flushes when EITHER:
#   * 30s elapsed (time trigger), or
#   * buffer holds >= threshold distinct queries (size trigger)
```

A flush swaps the buffer out under a lock and persists everything in **one
transaction** using `INSERT … ON CONFLICT DO UPDATE`. So 80 searches across
`iphone` and `java` collapse into **2 upserts** instead of 80 writes.

### Failure handling & recovery

- The buffer is **swapped out** before flushing, so new searches keep
  accumulating during a flush — no request ever blocks on the DB.
- If a flush throws, the un-committed counts are **merged back** into the live
  buffer and retried on the next tick — **no increments are silently lost**.
- On shutdown, `stop()` performs a **final synchronous flush**.

### Trade-offs

- **Durability window:** counts buffered in memory are lost on a hard kill
  (SIGKILL / power loss). Acceptable because search counts are approximate
  popularity signals, not transactions. A stricter design would put a durable
  queue / WAL (e.g. Kafka) in front of the DB.
- **Read-your-write lag:** a just-submitted query's count can lag by up to one
  flush interval. The typeahead tolerates slightly stale popularity.

---

## Performance metrics

`GET /metrics` returns live instrumentation (see
[`backend/app/utils/metrics.py`](backend/app/utils/metrics.py)).

Example output:

```json
{
  "latency": {
    "/suggest": { "p50_ms": 1.2, "p95_ms": 7.8, "count": 5000 },
    "/search":  { "p50_ms": 0.3, "p95_ms": 1.1, "count": 1200 },
    "/trending":{ "p50_ms": 3.4, "p95_ms": 11.2, "count": 200 }
  },
  "cache": { "hits": 4300, "misses": 700, "hit_rate": 0.86 },
  "database": { "reads": 700, "writes": 24 },
  "cache_node_sizes": { "node1": 240, "node2": 233, "node3": 227 }
}
```

Note how `database.writes` (24 batched flushes) is far below the 1200 searches
served — that is the batch writer doing its job. The cache hit rate keeps most
`/suggest` calls off the database entirely.

---

## Design decisions & trade-offs

| Decision | Why | Trade-off |
|---|---|---|
| Cache-aside (not write-through) | Simple, resilient to cache loss | First request per prefix pays a DB read |
| Consistent hashing + virtual nodes | Stable routing, minimal key movement | Slightly more memory & lookup cost than `% N` |
| In-process cache nodes | No external infra needed to demo the design | Not shared across processes; swap `CacheNode` for a Redis client in prod |
| Write-behind batching | Removes DB from the search hot path | Bounded durability window & read-your-write lag |
| TTL + prefix invalidation | Bounds staleness after popularity changes | Brief window where cached counts are stale |
| Score computed in SQL | Top-N ordering stays in the DB | Recency mode needs a decay job |
| SQLAlchemy `create_all` on startup | Zero-friction for the assignment | Use Alembic migrations in real prod |

---

## Screenshots

_Placeholders — drop images into `docs/screenshots/` and update these links._

| View | Image |
|---|---|
| Typeahead dropdown | `![suggestions](docs/screenshots/suggestions.png)` |
| Keyboard navigation | `![keyboard](docs/screenshots/keyboard.png)` |
| Trending panel (both modes) | `![trending](docs/screenshots/trending.png)` |
| `/metrics` output | `![metrics](docs/screenshots/metrics.png)` |

---

## License

Provided for the system-design assignment. Use freely.
# Search_Typeahead_System_HLD
