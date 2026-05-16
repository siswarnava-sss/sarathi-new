# Semicolon-Sarathi Architecture

This document explains the full system architecture, class structure, application flow, retrieval pipeline, AI model usage, and how recommendations are displayed on the portal.

## High-Level Architecture

```mermaid
flowchart TD
    A["User opens Streamlit portal"] --> B["Create profile or login"]
    B --> C["Profile wizard collects details one by one"]
    C --> D["Temporary username and password are generated"]
    D --> E["User enters dashboard"]
    E --> F["CitizenProfile object is created"]
    F --> G["HybridRetriever.search"]
    G --> H{"DATABASE_URL configured?"}
    H -->|Yes| I["PostgreSQL eligibility filtering"]
    I --> J["Optional pgvector semantic ranking"]
    H -->|No| K["schemes.json fallback filtering"]
    J --> L["Eligible scheme matches"]
    K --> L
    L --> M["GeminiExplainer"]
    M --> N["Grounded AI explanation"]
    L --> O["Scheme cards displayed on dashboard"]
    N --> P["AI chat and recommendation text displayed"]
```

## Data Ingestion Flow

```mermaid
flowchart TD
    A["Run python -m sarathi.ingest"] --> B{"Source selected"}
    B -->|--json| C["Read schemes.json"]
    B -->|--myscheme| D["Playwright opens myScheme pages"]
    B -->|--india-gov| E["Playwright opens India.gov.in"]
    B -->|--portals| F["Read custom portal config"]
    D --> G["Extract scheme links/cards"]
    E --> G
    F --> G
    C --> H["Normalize scheme fields"]
    G --> H
    H --> I{"--skip-embeddings?"}
    I -->|Yes| J["Insert schemes without vectors"]
    I -->|No| K["Generate BGE embeddings"]
    K --> L["Store vectors in pgvector"]
    J --> M["Upsert rows into PostgreSQL"]
    L --> M
```

## Class Diagram

```mermaid
classDiagram
    class CitizenProfile {
        +int age
        +str gender
        +str state
        +str category
        +int income
        +str need
        +from_session(user_data)
        +query_text()
    }

    class HybridRetriever {
        +SchemeStore store
        +BGEEmbedder embedder
        +search(profile, limit)
    }

    class SchemeStore {
        +str database_url
        +int embedding_dim
        +enabled
        +initialize()
        +count_schemes()
        +upsert_many(schemes, embedder)
        +hybrid_search(profile, query_embedding, limit)
    }

    class BGEEmbedder {
        +str model_name
        +available
        +embed(texts)
    }

    class GeminiExplainer {
        +str api_key
        +str model_name
        +explain(profile, schemes)
    }

    class PortalConfig {
        +str name
        +str url
        +str card_selector
        +str name_selector
        +str description_selector
        +validate()
    }

    CitizenProfile --> HybridRetriever
    HybridRetriever --> SchemeStore
    HybridRetriever --> BGEEmbedder
    SchemeStore --> BGEEmbedder
    GeminiExplainer --> CitizenProfile
    GeminiExplainer --> SchemeStore
    PortalConfig --> SchemeStore
```

## Main Components

### 1. Streamlit Portal

File:

```text
app.py
```

The portal handles the user interface. It has five main stages:

1. Landing page
2. Login page
3. Profile creation wizard
4. Profile created page
5. Dashboard

The first page gives two options:

- Login with temporary credentials
- Create a new profile

During profile creation, the user provides details one at a time:

- Name
- Age
- Gender
- State
- Category
- Annual family income
- Need, such as education, health, farming, housing, jobs, or business

After the profile is created, the app generates a temporary username and password. The user can copy the credentials or go directly to the dashboard.

The profile and credentials are stored only in Streamlit session state. They are temporary and not persisted permanently.

### 2. Citizen Profile

File:

```text
sarathi/rag.py
```

Class:

```python
CitizenProfile
```

This class converts user-provided profile details into a structured object used by the retriever.

Example:

```python
CitizenProfile(
    age=22,
    gender="Female",
    state="West Bengal",
    category="General",
    income=150000,
    need="education scholarship"
)
```

It also creates a semantic search query using `query_text()`.

Example query text:

```text
education scholarship. Citizen is 22 years old, Female, from West Bengal, category General, family income INR 150000.
```

This text is embedded using the BGE model when vector search is enabled.

### 3. Web Scraper

Files:

```text
sarathi/scraper.py
sarathi/ingest.py
```

The scraper uses Playwright because websites like MyScheme are JavaScript-rendered.

Supported scraping commands:

```powershell
python -m sarathi.ingest --myscheme
python -m sarathi.ingest --india-gov
python -m sarathi.ingest --portals portals.example.json
```

The scraper:

1. Opens the target website with Playwright.
2. Waits for the page to render.
3. Scrolls to load more results.
4. Extracts scheme links, names, and visible text.
5. Normalizes the data.
6. Sends the schemes to PostgreSQL.

### 4. Normalization

Function:

```python
normalize_scheme()
```

Raw scraped data is inconsistent across websites, so this function converts every scheme into one standard format:

```python
{
    "id": "...",
    "name": "...",
    "description": "...",
    "state": "All",
    "gender": "All",
    "age_min": 0,
    "age_max": 120,
    "category": ["General", "OBC", "SC", "ST", "Minority"],
    "income_limit_inr": 9999999,
    "apply_url": "...",
    "source_url": "...",
    "source_portal": "...",
    "language": "en",
    "search_text": "..."
}
```

The `search_text` field is important because it is converted into a vector embedding.

### 5. PostgreSQL + pgvector

File:

```text
db_schema.sql
```

Table:

```sql
government_schemes
```

The database stores:

- Scheme metadata
- Eligibility fields
- Source URL
- Search text
- Vector embedding

The vector column is:

```sql
embedding vector(1024)
```

This is used for semantic similarity search.

### 6. BGE Embedding Model

Class:

```python
BGEEmbedder
```

Default model:

```text
BAAI/bge-m3
```

The BGE model converts scheme text and user need text into numerical vectors. Similar meanings produce vectors that are close to each other.

Example:

```text
User need: "loan for small business"
```

This can semantically match schemes about:

- MSME support
- entrepreneurship
- credit guarantee
- startup assistance

even if the exact words are different.

If schemes are inserted with:

```powershell
--skip-embeddings
```

then the rows are inserted without vectors. Eligibility filtering still works, but semantic ranking is not meaningful until embeddings are generated.

### 7. Hybrid Retrieval

Class:

```python
HybridRetriever
```

The retrieval pipeline combines:

1. Deterministic SQL eligibility filtering
2. Semantic vector ranking

The SQL filter checks:

- Age
- Gender
- State
- Category
- Income

Then pgvector ranks matching schemes by semantic similarity.

```mermaid
flowchart LR
    A["Citizen profile"] --> B["SQL eligibility filter"]
    B --> C["Eligible scheme subset"]
    C --> D["Vector similarity ranking"]
    D --> E["Top matching schemes"]
```

If PostgreSQL is not configured, the app falls back to local `schemes.json`.

### 8. Gemini AI Model

Class:

```python
GeminiExplainer
```

Model:

```text
gemini-1.5-flash
```

Gemini does not directly search the internet or database.

The local retriever first returns eligible schemes. Then only those retrieved schemes are passed to Gemini.

Gemini's job is to:

- Explain why each scheme matches the user
- Personalize the recommendation
- Answer follow-up questions in the AI chat
- Avoid inventing schemes that were not retrieved

The prompt explicitly says:

```text
Use only the grounded schemes below.
Do not invent benefits, deadlines, eligibility rules, or links.
```

So the AI model works as a grounded explanation layer, not as the source of scheme data.

## Dashboard Display Flow

```mermaid
sequenceDiagram
    participant User
    participant App as Streamlit App
    participant Retriever as HybridRetriever
    participant DB as PostgreSQL/pgvector
    participant Gemini as GeminiExplainer

    User->>App: Submit profile details
    App->>Retriever: search(CitizenProfile)
    Retriever->>DB: SQL eligibility + vector ranking
    DB-->>Retriever: Matching schemes
    Retriever-->>App: Scheme list
    App->>Gemini: explain(profile, schemes)
    Gemini-->>App: Grounded explanation
    App-->>User: Dashboard scheme cards + AI chat
```

The dashboard has two tabs:

1. Eligible schemes
2. AI chat

### Eligible Schemes Tab

Each scheme is displayed as a card showing:

- Scheme name
- Description
- State
- Income cap
- Eligibility summary
- Official application link

### AI Chat Tab

The user can ask follow-up questions like:

```text
Which scheme is best for education?
```

or:

```text
What documents may I need?
```

The chat answer is generated using Gemini, but grounded in the schemes already retrieved for the user's profile.

## End-To-End Flow

```mermaid
flowchart TD
    A["Scrape schemes"] --> B["Normalize data"]
    B --> C["Generate embeddings"]
    C --> D["Store in PostgreSQL + pgvector"]
    E["User creates profile"] --> F["Build CitizenProfile"]
    F --> G["Filter by eligibility"]
    G --> H["Rank by semantic similarity"]
    H --> I["Send retrieved schemes to Gemini"]
    I --> J["Generate grounded explanation"]
    J --> K["Show dashboard and AI chat"]
```

## Important Behavior

- The scraper is not triggered automatically when a user opens the app.
- Scraping is triggered manually using `python -m sarathi.ingest`.
- The app reads from PostgreSQL if `DATABASE_URL` is set.
- If PostgreSQL is unavailable, the app uses `schemes.json`.
- Gemini does not decide which schemes exist.
- Gemini explains only the schemes retrieved from local storage.
- Temporary credentials are kept only in the browser session.

## Key Commands

Run the app:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; streamlit run app.py
```

Scrape MyScheme:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; python -m sarathi.ingest --myscheme
```

Scrape without embeddings for quick testing:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; python -m sarathi.ingest --myscheme --limit 10 --skip-embeddings
```

Check database count:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; python -m sarathi.ingest --count
```
