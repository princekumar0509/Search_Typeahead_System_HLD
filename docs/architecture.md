# High-Level Design — Search Typeahead System

## Component Diagram

```mermaid
flowchart TB
    User([👤 User])

    subgraph Frontend["Frontend (React + Vite + Tailwind)"]
        SB[Search Box<br/>debounced 300ms]
        TR[Trending Panel]
    end

    subgraph API["API Layer (FastAPI)"]
        SUG["GET /suggest"]
        SRCH["POST /search"]
        TREND["GET /trending"]
        DBG["GET /cache/debug"]
        MET["GET /metrics"]
    end

    subgraph ServiceLayer["Service Layer"]
        SugSvc[SuggestionService<br/>cache-aside]
        SrchSvc[SearchService<br/>write-behind]
        TrendSvc[TrendingService]
    end

    subgraph CacheLayer["Distributed Cache Layer"]
        Ring{{Consistent Hash Ring<br/>150 virtual nodes/node}}
        N1[(node1)]
        N2[(node2)]
        N3[(node3)]
    end

    subgraph Batch["Batch Writer (background thread)"]
        Buf[[search_buffer<br/>query -> delta]]
        Worker[Flush worker<br/>30s OR threshold]
    end

    Repo[Repository Layer<br/>QueryRepository]
    DB[(PostgreSQL<br/>queries table)]

    User --> SB & TR
    SB -->|/api| SUG & SRCH
    TR -->|/api| TREND

    SUG --> SugSvc
    SRCH --> SrchSvc
    TREND --> TrendSvc
    DBG --> Ring

    SugSvc --> Ring
    Ring --> N1 & N2 & N3
    SugSvc -->|cache miss| Repo

    SrchSvc --> Buf
    Buf --> Worker
    Worker --> Repo

    TrendSvc --> Repo
    Repo --> DB
```

## Data flow summary

| Path | Hot path? | Touches DB? |
|------|-----------|-------------|
| `GET /suggest` (cache hit) | yes | no |
| `GET /suggest` (cache miss) | yes | read |
| `POST /search` | yes | no (buffered) |
| Batch flush (every 30s / threshold) | background | batched write |
| `GET /trending` | warm | read |
| `GET /cache/debug` | cold | no |

## Key design points

- **Cache-aside** on the read path keeps popular prefixes out of the database.
- **Consistent hashing** routes each prefix to a stable cache node and limits
  key movement when the cache topology changes.
- **Write-behind batching** removes the database from the `POST /search` hot
  path, collapsing many increments into a few upserts.
- **Clean layering** (API → Service → Repository → DB) keeps business logic
  independent of transport and storage details.
