# Semicolon-Sarathi

Semicolon-Sarathi is a Streamlit application for personalized government scheme discovery. It can run in simple local mode using `schemes.json`, or in full RAG mode using PostgreSQL + pgvector, BGE embeddings, Playwright scraping, and Gemini explanations.

## 1. How To Run The Application

### Step 1: Open PowerShell In The Project Folder

```powershell
cd C:\Users\USER\Documents\semicolon-sarathi-main\semicolon-sarathi-main
```

### Step 2: Create And Activate Virtual Environment

```powershell
python -m venv venv
.\venv\Scripts\activate
```

### Step 3: Install Dependencies

```powershell
pip install -r requirements.txt
playwright install chromium
```

### Step 4: Run The Streamlit App

```powershell
streamlit run app.py
```

The app will open in your browser.

If PostgreSQL is not configured, the app still works using local `schemes.json` fallback data.

## Optional: Run With PostgreSQL + pgvector

Full vector search needs PostgreSQL with the `pgvector` extension.

### Option A: Using Docker Desktop

Install Docker Desktop first. Then run:

```powershell
docker run --name sarathi-pgvector -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=sarathi -p 5432:5432 -d pgvector/pgvector:pg16
```

Set the database URL in the same PowerShell session:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"
```

### Option B: Using Local PostgreSQL

If you already have PostgreSQL installed locally:

1. Start PostgreSQL.
2. Create a database named `sarathi`.
3. Enable `pgvector` in that database.
4. Set `DATABASE_URL` with your actual user, password, host, port, and database.

Example:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"
```

## Seed The Vector Database From Local JSON

Run this to insert the bundled local schemes:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; python -m sarathi.ingest --json schemes.json
```

Check how many schemes are stored:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; python -m sarathi.ingest --count
```

## 2. How To Trigger Web Scraping

Web scraping is triggered through the ingestion module:

```powershell
python -m sarathi.ingest
```

The scraper uses Playwright to load JavaScript-rendered websites, extracts scheme cards/links, normalizes the data, and writes it into PostgreSQL. If embeddings are enabled, it also generates BGE vectors before storing the rows.

### Scrape MyScheme Ministry Pages

The project is configured to scrape these MyScheme ministry pages:

- Ministry Of Micro, Small and Medium Enterprises
- Ministry Of Agriculture and Farmers Welfare
- Ministry of Education
- Ministry Of Health & Family Welfare
- Ministry Of Home Affairs

Test with 10 schemes and skip embeddings:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; python -m sarathi.ingest --myscheme --limit 10 --skip-embeddings
```

Run with embeddings:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; python -m sarathi.ingest --myscheme --limit 10
```

Run without a limit:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; python -m sarathi.ingest --myscheme
```

### Scrape India.gov.in Schemes Page

Test with 10 schemes and skip embeddings:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; python -m sarathi.ingest --india-gov --limit 10 --skip-embeddings
```

Run with embeddings:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; python -m sarathi.ingest --india-gov --limit 10
```

### Scrape From Custom Portal Config

Edit `portals.example.json` with a real government portal URL and CSS selectors.

Then run:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; python -m sarathi.ingest --portals portals.example.json
```

### Continuous Scraping

To keep scraping repeatedly:

```powershell
$env:SCHEME_REFRESH_MINUTES="360"; $env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; python -m sarathi.ingest --myscheme --watch
```

This reruns scraping every 360 minutes.

## Useful Commands

Check database count:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sarathi"; python -m sarathi.ingest --count
```

Run app:

```powershell
streamlit run app.py
```

Stop a stuck command:

```powershell
Ctrl + C
```

## Notes

- `--skip-embeddings` is useful for confirming scraping and database insertion quickly.
- The first embedding run can take several minutes because the BGE model may need to download and load.
- If you see `connection timeout expired`, PostgreSQL is not running or `DATABASE_URL` is wrong.
- If `docker` is not recognized, Docker Desktop is not installed.
