# 🎓 Viva Preparation Guide — Search Typeahead System

This document explains **every** part of the project and, crucially, the
**reasoning** behind each choice — including what was *deliberately not* used and
why. Read it top-to-bottom once, then use the [Rapid-fire Q&A](#15-rapid-fire-qa)
section the night before.

---

## 1. The 30-second elevator pitch

> "It's a Google-style search-suggestion service. As you type, it returns the
> top 10 most-popular queries matching your prefix. It's built in three layers —
> a React frontend, a FastAPI backend with clean API/Service/Repository
> separation, and PostgreSQL. The two interesting systems-design pieces are a
> **distributed cache sharded with consistent hashing** that keeps hot prefixes
> off the database, and a **write-behind batch writer** that collapses thousands
> of per-search count updates into a few bulk database writes. Trending has two
> ranking modes — pure popularity and a recency-weighted score."

If you can say that confidently, you've already passed the first question.

---

## 2. Why this architecture? (Clean / layered architecture)

The backend has four layers, each with one job:

| Layer | File(s) | Responsibility | Knows about |
|---|---|---|---|
| **API** | [api/routes.py](../backend/app/api/routes.py), [api/deps.py](../backend/app/api/deps.py) | HTTP: parse request, call a service, shape response, record latency | HTTP + services |
| **Service** | [services/](../backend/app/services/) | Business logic (cache-aside, write-behind, scoring) | repos + cache + batch |
| **Repository** | [repositories/query_repository.py](../backend/app/repositories/query_repository.py) | **All** SQL / ORM access | the database only |
| **Model** | [models/db_models.py](../backend/app/models/db_models.py) (ORM), [models/schemas.py](../backend/app/models/schemas.py) (Pydantic) | Data shapes | nothing |

**Why layer it this way?**
- **Separation of concerns / testability.** I can unit-test the consistent-hash
  ring or the scoring logic without spinning up a database or HTTP server.
- **Swappability.** SQL lives *only* in the repository. If we moved from
  Postgres to another store, the services and API don't change.
- **The dependency rule points inward.** API depends on services; services
  depend on repositories; nothing inner depends on anything outer. Models are
  pure data and depend on nothing.

**Why two kinds of "model" (ORM vs Pydantic)?**
- ORM models ([db_models.py](../backend/app/models/db_models.py)) map to database
  tables. Pydantic schemas ([schemas.py](../backend/app/models/schemas.py)) are
  the **API contract** (validation + serialization).
- Keeping them separate means the database shape never leaks to clients and
  request validation happens at the edge. If I returned ORM objects directly,
  any internal column rename would become a breaking API change.

---

## 3. Tech-stack justification (why / why-not)

### Backend: FastAPI
- **Why:** async-capable ASGI framework, automatic OpenAPI/Swagger docs at
  `/docs`, and **Pydantic validation built in** so bad input is rejected before
  it reaches business logic. Type hints make it self-documenting.
- **Why not Flask?** Flask is sync-first, needs extensions for validation and
  docs, and has no native typing story. FastAPI gives those for free.
- **Why not Django?** Django is a batteries-included monolith (ORM, admin,
  templating). It's heavy for a focused JSON API and its ORM is less flexible
  than SQLAlchemy for the upsert/window queries we need.

### Database: PostgreSQL
- **Why:** mature, ACID, excellent index support, and critically it has
  **`INSERT … ON CONFLICT DO UPDATE`** (native upsert) which makes the
  "insert-or-increment" atomic in a single statement. Also `ILIKE 'iph%'`
  prefix queries are index-friendly.
- **Why not MySQL?** Comparable, but Postgres's `ON CONFLICT` and expression
  indexes are cleaner for this workload.
- **Why not a NoSQL store (Mongo/Redis as primary)?** The data is small,
  relational, and we want strong consistency on counts and indexed prefix
  scans. A document store gives no advantage here.
- **Why not a trie / Elasticsearch for prefix search?** See
  [§13 honest limitations](#13-known-limitations--what-id-improve). Short answer:
  for the assignment's scale a btree prefix index is simpler and fast enough; a
  real Google-scale system would use a trie/FST or a search engine.

### ORM: SQLAlchemy 2.0
- **Why:** the de-facto Python ORM, supports the Postgres-specific upsert via
  `sqlalchemy.dialects.postgresql.insert`, and its Core lets us push scoring/
  ordering into SQL.
- **Why not raw SQL everywhere?** We do use raw-ish SQL for the upsert, but the
  ORM gives type-safe models, migrations-readiness, and connection pooling.

### Frontend: React + Vite + Tailwind
- **React:** component model fits the search-box / dropdown / trending split and
  manages local UI state (active suggestion index, loading/error) cleanly.
- **Vite (not Create-React-App):** instant dev server, native ES modules, far
  faster builds; CRA is effectively deprecated.
- **Tailwind (not plain CSS / a component library):** utility classes keep
  styling colocated with markup and avoid shipping a heavy component library for
  a small UI. No runtime cost — it's compiled to static CSS.

---

## 4. Database schema deep-dive

```sql
queries(
    id            SERIAL PRIMARY KEY,
    query         TEXT UNIQUE NOT NULL,
    count         BIGINT NOT NULL DEFAULT 0,
    recent_count  BIGINT NOT NULL DEFAULT 0,
    last_searched TIMESTAMP WITH TIME ZONE DEFAULT now()
)
```
See [db/schema.sql](../backend/db/schema.sql) and [db_models.py](../backend/app/models/db_models.py).

**Why each column?**
- `id SERIAL PRIMARY KEY` — surrogate key; stable identity independent of the
  text.
- `query TEXT UNIQUE` — the normalized query string. **UNIQUE is essential**: it
  is the conflict target for `ON CONFLICT (query) DO UPDATE`. Without the unique
  constraint the upsert can't work and we'd get duplicate rows.
- **Why `TEXT` not `VARCHAR(n)`?** In Postgres `TEXT` and `VARCHAR` have
  identical performance; `TEXT` avoids an arbitrary length cap. We still cap
  length at the API layer (Pydantic `max_length=512`).
- `count BIGINT` — all-time popularity. **Why BIGINT not INT?** A popular query
  can exceed the ~2.1 billion INT limit over time; BIGINT is cheap insurance.
- `recent_count BIGINT` — popularity within the recent window, used by the
  recency-aware trending mode and periodically reset.
- `last_searched TIMESTAMPTZ` — when it was last hit; useful for decay jobs and
  debugging. **Why `TIMESTAMP WITH TIME ZONE`?** Always store UTC-aware times to
  avoid timezone ambiguity.

**Why the indexes?**
- `ix_queries_query (query text_pattern_ops)` — a btree with `text_pattern_ops`
  makes **prefix range scans** (`query LIKE 'iph%'`) index-accelerated. A plain
  btree on `text` uses the database's collation and won't be used for `LIKE`
  unless you use `text_pattern_ops`.
- `ix_queries_query_lower (lower(query) text_pattern_ops)` — supports
  **case-insensitive** prefix matching (`ILIKE`) by indexing `lower(query)`.
- `ix_queries_count (count DESC)` — speeds the popularity ORDER BY for trending.
- A functional index on `(count + recent_count*10) DESC` pre-computes the
  recency score order.

**Trade-off of indexes:** they speed reads but slow writes and use disk. That's
exactly why we batch writes (§8) — fewer, larger writes amortize index-update
cost.

---

## 5. The suggestion flow (`GET /suggest`) — cache-aside

Implemented in [suggestion_service.py](../backend/app/services/suggestion_service.py).

**The flow (cache-aside, a.k.a. lazy loading):**
1. Normalize the prefix (`trim().lower()`) so `"IPh "` and `"iph"` share a cache
   entry.
2. Build the cache key `suggest:<prefix>` and ask the ring which node owns it.
3. **Cache hit** → return the cached suggestions (no DB).
4. **Cache miss** → query the DB (`ILIKE 'iph%' ORDER BY count DESC LIMIT 10`),
   store the result in the cache with a TTL, return it.

**Why cache-aside and not write-through / write-back?**
- Cache-aside is the simplest, most resilient pattern: if the cache is empty or
  a node dies, we just fall back to the DB and repopulate. The cache is never
  the source of truth.
- Write-through (write to cache + DB on every write) couples writes to the cache
  and offers no benefit here since our writes are counts, not suggestion lists.
- The suggestion *list* is derived data; caching it lazily on read is the
  natural fit.

**Why normalize the prefix?** Caching, correctness, and hit rate — without
normalization `iPhone`, `iphone`, `iphone ` would be three different cache keys
and three DB reads for the same intent.

**Why escape LIKE wildcards?** In the repository we escape `%` and `_` in user
input ([query_repository.py](../backend/app/repositories/query_repository.py)) so
a user typing `100%` doesn't turn into a wildcard that matches everything.

---

## 6. Consistent hashing — THE key topic (expect deep questions)

Implemented in [consistent_hash.py](../backend/app/cache/consistent_hash.py).

### 6.1 The problem with naive sharding
The obvious way to pick a cache node is `node = hash(key) % N`. The fatal flaw:
when `N` changes (a node is added or one crashes), the modulus changes for
**almost every key**. Going from 3 → 4 nodes re-maps ~75% of keys. Each
re-mapped key is now a **cache miss**, so the whole fleet stampedes the database
simultaneously — a "cache stampede" that can take the DB down.

### 6.2 How consistent hashing fixes it
- Imagine a circle (ring) of hash values `0 … 2³²−1`.
- Hash each **node** to a point on the ring; hash each **key** to a point too.
- A key is owned by the **first node clockwise** from the key's position.
- When a node is removed, only the keys that lived in its arc move — they go to
  the *next* node clockwise. On average that's `K/N` keys (~33% with 3 nodes),
  and **every other key stays exactly where it was**.

I verified this empirically: removing `node2` moved only **33.8%** of keys, and
every non-node2 key was unchanged (see the test below).

### 6.3 Virtual nodes — why and how
**Problem with one point per node:** the ring gets carved into uneven arcs, so
load is lopsided; worse, removing a node dumps its *entire* arc onto a single
neighbor.

**Solution:** hash each physical node to **many** points (here **150** virtual
nodes per physical node, key `node1#vn0`, `node1#vn1`, …). Now each physical
node occupies 150 small arcs scattered around the ring. Effects:
- **Balance:** load evens out to within a few percent (my distribution test
  showed ~3000 keys per node out of 9000).
- **Graceful failure:** a removed node's 150 arcs are adjacent to *different*
  nodes, so its keys spread across **all** survivors, not one.

**Trade-off of more virtual nodes:** more memory for ring points and slightly
slower lookups (the sorted list is longer). 100–200 is the usual sweet spot;
I chose 150.

### 6.4 Implementation details an examiner may probe
- **Data structure:** a sorted list of ring positions (`_ring_keys`) plus a dict
  `position → node`. Lookup uses **`bisect`** (binary search) to find the first
  position clockwise of the key — **O(log V)** where V = total virtual nodes.
- **Hash function: MD5.** Used **purely as a fast, uniformly-distributed hash**,
  not for security. We take the top 32 bits (`int(md5[:8], 16)`).
  - *Why MD5 and not Python's built-in `hash()`?* `hash()` for strings is
    **randomized per process** (PYTHONHASHSEED), so the same key would map
    differently across restarts — unacceptable for a stable ring. MD5 is
    deterministic across processes and machines.
  - *Why not SHA-256?* Slower and we don't need cryptographic strength; we just
    need good distribution.
  - *Is MD5 being "broken" a problem?* No — collision attacks matter for
    signatures, not for hash-based sharding.
- **`add_node` / `remove_node`** insert/remove all 150 virtual points and keep
  `_ring_keys` sorted via `bisect.insort`.
- **`get_node`** wraps around the ring (if the key hashes past the last point it
  belongs to the first node) — that's the `index == len → 0` line.

### 6.5 Proof (cite this in the viva)
[`tests/test_consistent_hash.py`](../backend/tests/test_consistent_hash.py) asserts:
1. same key → same node every time (consistency),
2. balanced distribution with virtual nodes,
3. **< 45% of keys move on node removal and non-affected keys never move** —
   i.e. minimal key movement, the whole point of the technique.

---

## 7. The distributed cache — TTL, invalidation, in-process design

Files: [distributed_cache.py](../backend/app/cache/distributed_cache.py) (the facade
+ ring) and [cache_node.py](../backend/app/cache/cache_node.py) (one node).

**Structure:** `DistributedCache` owns the ring and a dict of `CacheNode`s.
Callers treat it as one cache; internally each key is routed to its node. This
is the **facade pattern** — it hides the sharding.

**TTL (time-to-live):** each entry stores an absolute `expires_at`. On read, if
`expires_at` has passed we delete and report a miss — this is **lazy expiry**
(we don't need a background sweeper for a demo).
- *Why TTL at all?* It bounds staleness. Popularity changes over time; a 60s TTL
  guarantees cached suggestions are at most 60s old even if nothing invalidates
  them.
- *Why 60s?* A tunable (`CACHE_TTL_SECONDS`). Long enough for a high hit rate,
  short enough that popularity stays fresh.

**Invalidation:** when a search is submitted, we proactively invalidate the
cache entries for the prefixes of that query (`search_service.py`) so the next
read reloads fresh popularity, rather than waiting the full TTL.

**Thread-safety:** each `CacheNode` guards its dict with a `threading.Lock`
because the batch-writer thread and request threads can touch the cache
concurrently.

**Why in-process dicts and not real Redis?**
- The assignment asked to **simulate** a distributed cache and demonstrate the
  consistent-hashing routing. In-process nodes let the whole behavior be shown
  and tested with zero external infrastructure.
- In production each `CacheNode` would be replaced by a network client to a real
  Redis/Memcached instance — **the ring and routing logic stay identical**. That
  clean seam is the point.
- *Honest limitation:* because it's in-process, the cache isn't shared across
  multiple backend workers (see §13). That's why `docker-compose` runs 1 uvicorn
  worker.

---

## 8. Batch writes (write-behind) — the second key topic

Implemented in [batch_writer.py](../backend/app/batch/batch_writer.py).

### 8.1 The problem
If `POST /search` wrote to Postgres on every request, each search = one row
update + a commit + a WAL (write-ahead log) flush. Under load the DB becomes the
bottleneck, and most writes are just `count += 1` on the same hot keys.

### 8.2 The solution — buffer + background flush
```python
search_buffer = {}            # {query: pending_increment}, in memory
# on each search:  search_buffer[query] += 1   (no DB hit)
```
A background worker thread flushes the buffer to the DB when **either**:
- **30 seconds** have elapsed (time trigger), or
- the buffer holds **≥ threshold** distinct queries (size trigger).

A flush applies all increments in **one transaction** using
`INSERT … ON CONFLICT DO UPDATE`. So 80 searches across `iphone`/`java` become
**2 upserts** instead of 80 writes.

### 8.3 Concurrency design (examiner favorite)
- The buffer is **swapped out under a lock** at the start of a flush
  (`pending, self._buffer = self._buffer, {}`). New searches immediately
  accumulate into a fresh dict, so **no request ever blocks on the database**.
- A `threading.Event` lets the size trigger wake the worker early instead of
  waiting the full 30s.

### 8.4 Failure handling & recovery
- If the flush raises (DB down), we **roll back** and **merge the un-committed
  counts back into the live buffer**, so they're retried on the next tick —
  **no increments are silently lost**. I tested exactly this: a simulated DB
  outage on the first flush, then the retry persisted everything correctly.
- On shutdown, `stop()` does a **final synchronous flush** so buffered counts are
  persisted on graceful exit.

### 8.5 Trade-offs (state these proactively — examiners love trade-offs)
- **Durability window:** counts held in memory are lost on a *hard* kill
  (SIGKILL / power loss). Acceptable because search counts are **approximate
  popularity signals, not money**. A stricter system would front the DB with a
  durable log/queue (e.g. Kafka) so nothing is lost.
- **Read-your-write lag:** a just-submitted query's count can lag by up to one
  flush interval. The typeahead tolerates slightly stale popularity.
- **Eventual consistency** of the count, in exchange for a huge write-throughput
  win. This is the classic latency/throughput vs. consistency trade.

### 8.6 Why a thread and not asyncio / Celery / a cron?
- A simple `threading.Thread` daemon is enough for an in-process write-behind
  buffer and needs no extra infra.
- *Why not asyncio task?* The DB driver (psycopg2) is synchronous/blocking; a
  thread avoids blocking the event loop. (A fully async stack would use asyncpg.)
- *Why not Celery/cron?* Those add a broker/scheduler dependency. Overkill for an
  in-process buffer; appropriate only if flushes must survive process restarts.

---

## 9. Trending — two ranking modes

Implemented in [trending_service.py](../backend/app/services/trending_service.py).

- **Mode 1 — popularity:** `score = count`. Stable, reflects all-time winners.
  *Trade-off:* slow to react; today's spike can't overtake an established giant.
- **Mode 2 — recency-aware:** `score = count + recent_count * 10`. The `×10`
  weight lets a smaller but **fresh** signal compete with large all-time counts.
  *Trade-offs:*
  - `recent_count` must be **periodically decayed/reset**
    (`QueryRepository.reset_recent_counts`) or it converges back to popularity.
  - The weight `10` is the **tuning knob**: higher = more responsive but noisier;
    lower = more stable but laggier.

**Why compute the score in SQL, not Python?** So ordering and `LIMIT 10` happen
**in the database** and only 10 rows cross the wire — instead of pulling the
whole table into Python and sorting it (which would be O(N log N) over 120k rows
every request).

**Real-world note to mention:** a production "trending" usually uses **time-decay
(exponential decay / sliding windows)** rather than a flat `recent_count`, so old
spikes fade smoothly. The two-mode design here is a deliberately simple,
explainable version of that idea.

---

## 10. Metrics & instrumentation

[utils/metrics.py](../backend/app/utils/metrics.py), exposed at `GET /metrics`.

- **Latency p50/p95 per endpoint** — kept as a bounded **sorted** sample window;
  percentile = index into the sorted list. *Why p95 and not just average?*
  Averages hide tail latency; p95/p99 is what users actually feel.
- **Cache hit rate** = hits / (hits + misses). The headline number proving the
  cache works.
- **DB reads / writes** — shows the batch writer's effect: e.g. 1200 searches but
  only ~24 DB writes.
- **Thread-safe** via a lock since multiple request threads record concurrently.
- *Why in-memory and not Prometheus?* Simplicity for the assignment. The honest
  upgrade path is to export these to Prometheus/StatsD and graph in Grafana.

---

## 11. Frontend deep-dive

### Debouncing ([useDebounce.js](../frontend/src/hooks/useDebounce.js))
- **What:** only fire the suggestion API after the user pauses typing for 300ms.
- **Why:** typing "iphone" would otherwise fire 6 requests. Debounce sends ~1.
  It protects the backend and avoids out-of-order responses.
- **Why 300ms?** Long enough to batch keystrokes, short enough to feel instant.

### AbortController
Each new fetch aborts the previous in-flight request. **Why:** prevents a slow
older response from overwriting a newer one (race condition), and saves
bandwidth.

### Keyboard navigation ([SearchBox.jsx](../frontend/src/components/SearchBox.jsx))
- ↑/↓ move the highlighted suggestion (wrapping around), Enter selects the
  highlighted one or submits if none highlighted, Escape closes the dropdown.
- **Why:** accessibility and the expected "Google" feel — power users never touch
  the mouse.

### Loading / error states
- Loading spinner while fetching; a friendly error row if the backend is down.
- **Why:** never leave the user staring at a frozen box; surface failures.

### Why the `/api` proxy (Vite dev + nginx prod)?
- The frontend calls **relative** `/api/...` URLs. In dev, Vite proxies them to
  `localhost:8000`; in prod, nginx proxies them to the `backend` container.
- **Why:** avoids hardcoding the backend host in the bundle and sidesteps CORS in
  the browser (same-origin requests).

### Why React StrictMode?
Surfaces accidental side-effects/double-effects in development. (It's why the
debounce/abort cleanup must be correct — StrictMode double-invokes effects in
dev.)

---

## 12. Docker & deployment

- **3 services** in [docker-compose.yml](../docker-compose.yml): `postgres`,
  `backend`, `frontend`.
- **Healthcheck + `depends_on: condition: service_healthy`** — the backend waits
  until Postgres is actually accepting connections, not just "container started".
  The [entrypoint.sh](../backend/entrypoint.sh) also polls Postgres before
  starting uvicorn (belt and suspenders).
- **Schema on first boot:** `schema.sql` is mounted into Postgres's
  `docker-entrypoint-initdb.d`, which runs it once when the data volume is empty.
- **Seeding:** `SEED_ON_START=true` makes the backend generate + load ~120k rows
  on first boot.
- **Frontend is a multi-stage build:** Node builds the static bundle, then it's
  copied into a tiny nginx image. *Why:* the final image has no Node/toolchain —
  smaller and more secure.
- **Named volume `pgdata`:** persists the database across `docker compose down`.

---

## 13. Known limitations & what I'd improve (have this ready!)

Examiners respect candidates who know their design's edges:

1. **In-process cache isn't shared across workers.** With multiple uvicorn
   workers each has its own cache, so hit rate drops and the ring is per-process.
   *Fix:* back `CacheNode` with real Redis instances — the ring code is unchanged.
2. **Batch buffer is non-durable.** A hard crash loses buffered counts.
   *Fix:* a durable queue (Kafka) or an append-only WAL before flush.
3. **Prefix search is `ILIKE`, not a trie/FST.** Fine at 120k rows; at Google
   scale you'd use a trie, an FST, or Elasticsearch/`pg_trgm` for fuzzy/typo
   tolerance.
4. **No typo tolerance / fuzzy matching.** Could add `pg_trgm` similarity or
   edit-distance ranking.
5. **No auth / rate limiting** on the API.
6. **`recent_count` has no automatic decay job** wired to a scheduler; the method
   exists but isn't on a timer.
7. **Schema via `create_all`**, not migrations. *Fix:* Alembic for real prod.
8. **No personalization** — Google ranks by user/location/history; this is
   global popularity only.

---

## 14. End-to-end request walkthroughs (be able to narrate these)

**Typing "iph" (cache miss then hit):**
debounce 300ms → `GET /suggest?q=iph` → route records start time → service
normalizes → ring says `node2` → node2 miss → repo runs
`SELECT … ILIKE 'iph%' ORDER BY count DESC LIMIT 10` → service stores result in
node2 with 60s TTL → returns `{suggestions, cache_hit:false, node:"node2"}`.
**Next keystroke-pause for "iph"** → same key → node2 **hit** → no DB.

**Submitting "iphone":**
`POST /search {query:"iphone"}` → service normalizes → `batch_writer.increment`
bumps `buffer["iphone"]` in memory → invalidates `suggest:i`, `suggest:ip`, …
caches → returns `{"message":"Searched"}` immediately. **No DB write on the
request.** Up to 30s later the worker flushes `{"iphone": N, …}` in one
transaction.

---

## 15. Rapid-fire Q&A

**Q: Why consistent hashing over modulo hashing?**
Modulo re-maps ~all keys when node count changes (cache stampede). Consistent
hashing moves only ~K/N keys; the rest stay put.

**Q: What do virtual nodes solve?**
Uneven load and the "all keys land on one neighbor" problem when a node leaves.
They spread each physical node across many ring arcs.

**Q: Why MD5 if it's cryptographically broken?**
We use it only as a fast uniform hash for sharding, not for security. Collision
resistance is irrelevant here; determinism across processes is what matters
(unlike Python's randomized `hash()`).

**Q: Lookup complexity of `get_node`?**
O(log V) via binary search over the sorted ring, V = nodes × virtual_nodes.

**Q: Why batch writes? What's the win?**
Removes the DB from the hot path and collapses many `count+=1` updates into a few
bulk upserts — fewer commits/WAL flushes, far higher write throughput.

**Q: What happens to counts if the server crashes?**
Buffered (unflushed) counts in memory are lost on a hard kill; on graceful
shutdown we flush. Acceptable because counts are approximate; a durable queue
fixes it if needed.

**Q: How do you avoid losing counts when a flush fails?**
We roll back and merge the pending counts back into the live buffer; they retry
next tick. Tested with a simulated outage.

**Q: Cache-aside vs write-through?**
Cache-aside: populate on read-miss, DB is source of truth, resilient to cache
loss. We don't write suggestion lists, so write-through adds coupling with no
benefit.

**Q: How is staleness bounded?**
TTL (60s) + proactive prefix invalidation on search submit.

**Q: Why ON CONFLICT DO UPDATE instead of SELECT-then-INSERT/UPDATE?**
It's atomic — no race between concurrent writers doing read-modify-write, and
it's a single round trip.

**Q: Why BIGINT for count?**
A hot query can exceed INT's ~2.1B ceiling over time.

**Q: Why TEXT UNIQUE on query?**
UNIQUE is the conflict target for the upsert and prevents duplicate rows.

**Q: How does prefix search use an index?**
`text_pattern_ops` btree (and a `lower(query)` functional index for `ILIKE`)
turn `query LIKE 'iph%'` into an index range scan.

**Q: Why debounce on the frontend?**
One request per typing-pause instead of one per keystroke — protects the backend
and avoids wasted/racing requests.

**Q: Why AbortController?**
Cancels stale in-flight suggestion requests so an old slow response can't
overwrite a newer one.

**Q: Why is the cache thread-safe?**
The batch-writer thread and request threads access it concurrently; each node
uses a lock.

**Q: How would you scale this to real Google scale?**
Real Redis cluster behind the same ring; a trie/FST or Elasticsearch for prefix
search; Kafka in front of the count writes; time-decay trending; multiple
stateless API replicas behind a load balancer; per-user personalization.

**Q: Why FastAPI over Flask/Django?**
Built-in validation (Pydantic), auto OpenAPI docs, type hints, async support —
without extra extensions or a heavyweight framework.

**Q: What's the p95 latency and why measure it?**
See `/metrics`; p95 reflects the slow-tail users feel, which averages hide.
