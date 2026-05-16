# Tools Used In Semicolon-Sarathi

This document explains the tools, libraries, and services used in the project, why they are used, how they are used, and where they are used in the codebase.

## Summary

| Tool | Purpose | Used In |
| --- | --- | --- |
| Python | Main programming language | Entire project |
| Streamlit | Web application UI | `app.py` |
| Playwright | Web scraping browser automation | `sarathi/scraper.py` |
| BeautifulSoup | HTML parsing after scraping | `sarathi/scraper.py` |
| PostgreSQL | Main structured database | `sarathi/rag.py`, `db_schema.sql` |
| pgvector | Vector storage and similarity search | `db_schema.sql`, `sarathi/rag.py` |
| Sentence Transformers | Embedding generation | `sarathi/rag.py` |
| BAAI BGE model | Semantic embedding model | `sarathi/rag.py` |
| Gemini 1.5 Flash | Grounded AI explanation and chat | `sarathi/rag.py`, `app.py` |
| JSON | Local fallback scheme storage | `schemes.json`, `sarathi/rag.py` |
| PowerShell | Local command execution on Windows | Setup and run commands |

## Python

### Why It Is Used

Python is used because the project needs:

- Fast backend development
- Streamlit UI support
- AI/ML library support
- Web scraping support
- PostgreSQL integration

Python has mature libraries for all of these.

### Where It Is Used

Python is used across the entire project:

```text
app.py
sarathi/rag.py
sarathi/scraper.py
sarathi/ingest.py
```

### How It Is Used

Python runs:

- The Streamlit web app
- The scraping scripts
- The RAG retrieval logic
- The embedding generation
- The database ingestion commands
- The Gemini API calls

## Streamlit

### Why It Is Used

Streamlit is used to build the user-facing portal quickly using Python. It avoids needing a separate React frontend and backend API.

### Where It Is Used

```text
app.py
```

### How It Is Used

Streamlit creates:

- Landing page
- Login page
- Profile creation wizard
- Dashboard
- Eligible scheme cards
- AI chat tab

The user enters details one at a time. Streamlit stores temporary session data in:

```python
st.session_state
```

This is used for:

- User profile
- Temporary username/password
- Login state
- Retrieved schemes
- Chat messages

## Playwright

### Why It Is Used

Playwright is used because websites like MyScheme are JavaScript-rendered. A simple HTTP request may not return the final scheme cards.

Playwright opens the page like a real browser, waits for JavaScript to render, scrolls the page, and then extracts the HTML content.

### Where It Is Used

```text
sarathi/scraper.py
```

### How It Is Used

Playwright is used in scraper functions such as:

```python
scrape_myscheme_pages()
scrape_india_gov_schemes()
scrape_portal()
```

For MyScheme, the scraper:

1. Opens ministry/state search pages.
2. Waits for rendering.
3. Scrolls the page to load results.
4. Extracts scheme links and visible card text.
5. Returns normalized scheme records.

## BeautifulSoup

### Why It Is Used

BeautifulSoup is used to parse HTML after Playwright loads a page.

It is useful when we need to select headings, links, and sections from rendered HTML.

### Where It Is Used

```text
sarathi/scraper.py
```

### How It Is Used

BeautifulSoup is mainly used for pages like India.gov.in where the HTML structure can be parsed after loading:

```python
BeautifulSoup(html, "html.parser")
```

It helps extract:

- Featured scheme headings
- Scheme links
- Scheme titles

## PostgreSQL

### Why It Is Used

PostgreSQL is used as the main database because the project needs:

- Structured scheme storage
- SQL eligibility filtering
- Stable local database support
- pgvector extension support

### Where It Is Used

```text
db_schema.sql
sarathi/rag.py
sarathi/ingest.py
```

### How It Is Used

PostgreSQL stores the `government_schemes` table.

It stores:

- Scheme ID
- Name
- Description
- State
- Gender
- Age range
- Category
- Income limit
- Apply URL
- Source portal
- Search text
- Vector embedding

The app queries PostgreSQL when:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"
```

is set.

## pgvector

### Why It Is Used

pgvector is used to store embeddings directly inside PostgreSQL and perform semantic similarity search.

This lets the system combine:

- SQL filtering
- Vector search

inside one database.

### Where It Is Used

```text
db_schema.sql
sarathi/rag.py
```

### How It Is Used

The schema defines:

```sql
embedding vector(1024)
```

The retrieval query uses vector similarity:

```sql
1 - (embedding <=> query_embedding)
```

This ranks schemes by semantic closeness to the user's stated need.

## Sentence Transformers

### Why It Is Used

Sentence Transformers provides an easy way to load embedding models and generate vector embeddings from text.

### Where It Is Used

```text
sarathi/rag.py
```

### How It Is Used

The class:

```python
BGEEmbedder
```

loads a Sentence Transformer model and converts text into embeddings:

```python
model.encode(payload, normalize_embeddings=True)
```

It embeds:

- Scheme text during ingestion
- User query/profile text during retrieval

## BAAI BGE Embedding Model

### Why It Is Used

BGE is used for semantic retrieval. It helps match meaning, not just exact words.

Example:

```text
small business loan
```

can match schemes about:

- MSME support
- entrepreneurship
- credit assistance
- startup funding

### Where It Is Used

```text
sarathi/rag.py
```

### How It Is Used

Default model:

```text
BAAI/bge-m3
```

Configured in:

```python
DEFAULT_MODEL_NAME = os.getenv("BGE_MODEL_NAME", "BAAI/bge-m3")
```

The first run may take time because the model may need to download.

## Gemini 1.5 Flash

### Why It Is Used

Gemini is used to generate human-friendly explanations and AI chat responses.

It is not used as the source of scheme data.

### Where It Is Used

```text
sarathi/rag.py
app.py
```

### How It Is Used

The class:

```python
GeminiExplainer
```

receives:

- User profile
- Retrieved schemes from local database or JSON fallback

Then it generates:

- Personalized recommendations
- Explanation of why each scheme fits
- Follow-up AI chat answers

The prompt instructs Gemini:

```text
Use only the grounded schemes below.
Do not invent benefits, deadlines, eligibility rules, or links.
```

So Gemini explains retrieved local data. It does not directly search the web or database.

## JSON

### Why It Is Used

JSON is used as a simple fallback and demo data source.

If PostgreSQL is not configured, the app still works using:

```text
schemes.json
```

### Where It Is Used

```text
schemes.json
sarathi/rag.py
```

### How It Is Used

The function:

```python
load_json_schemes()
```

loads local schemes and applies deterministic eligibility filtering.

This keeps the app usable even without PostgreSQL or pgvector.

## PowerShell

### Why It Is Used

PowerShell is used because the project is being run on Windows.

### Where It Is Used

PowerShell is used for local commands such as:

```powershell
streamlit run app.py
python -m sarathi.ingest --myscheme
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"
```

### How It Is Used

PowerShell sets environment variables and runs project commands.

Example:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; streamlit run app.py
```

## Tool Flow

```mermaid
flowchart TD
    A["PowerShell command"] --> B["Python ingestion module"]
    B --> C["Playwright browser scraping"]
    C --> D["BeautifulSoup / DOM extraction"]
    D --> E["Scheme normalization"]
    E --> F["Sentence Transformers"]
    F --> G["BGE embeddings"]
    G --> H["PostgreSQL + pgvector"]
    H --> I["Streamlit app"]
    I --> J["Hybrid retrieval"]
    J --> K["Gemini explanation"]
    K --> L["Dashboard and AI chat"]
```

## Where Each Tool Fits In The User Journey

```mermaid
sequenceDiagram
    participant Admin
    participant Scraper as Playwright Scraper
    participant DB as PostgreSQL + pgvector
    participant User
    participant UI as Streamlit UI
    participant AI as Gemini

    Admin->>Scraper: Trigger scraping command
    Scraper->>DB: Insert schemes and vectors
    User->>UI: Create profile
    UI->>DB: Fetch eligible schemes
    DB-->>UI: Return matching schemes
    UI->>AI: Send retrieved schemes for explanation
    AI-->>UI: Return grounded answer
    UI-->>User: Show scheme cards and AI chat
```

## Important Clarification

Gemini does not scrape schemes.

Gemini does not search the database directly.

Gemini does not decide which schemes exist.

The local system retrieves schemes first. Gemini only explains those retrieved schemes in a user-friendly way.
