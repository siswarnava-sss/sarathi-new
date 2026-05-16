from __future__ import annotations

import json
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_MODEL_NAME = os.getenv("BGE_MODEL_NAME", "BAAI/bge-m3")
DEFAULT_EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/sarathi"

INTENT_TERMS: dict[str, dict[str, tuple[str, ...]]] = {
    "medical_health": {
        "need": ("health", "medical", "mediclaim", "hospital", "treatment", "insurance", "ayushman"),
        "positive": (
            "health insurance",
            "medical",
            "mediclaim",
            "hospital",
            "treatment",
            "healthcare",
            "ayushman",
            "disease",
            "patient",
        ),
        "negative": (
            "soil health",
            "plant health",
            "crop",
            "crops",
            "agri",
            "agriculture",
            "farmer",
            "farmers",
            "animal",
            "animals",
            "fodder",
            "livestock",
        ),
    },
    "farming": {
        "need": ("farming", "farmer", "agriculture", "crop", "kisan", "livestock"),
        "positive": (
            "agri",
            "agriculture",
            "farmer",
            "farmers",
            "crop",
            "crops",
            "kisan",
            "soil health",
            "livestock",
            "animal husbandry",
            "fodder",
        ),
        "negative": ("mediclaim", "hospital", "patient", "medical treatment"),
    },
}


def _clean_text(value: Any, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    return re.sub(r"\s+", " ", text)


def _clean_int(value: Any, fallback: int) -> int:
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return fallback


def _clean_categories(value: Any) -> list[str]:
    if isinstance(value, list):
        categories = value
    elif isinstance(value, str):
        categories = re.split(r"[,/|]", value)
    else:
        categories = ["General"]
    cleaned = [_clean_text(item) for item in categories if _clean_text(item)]
    return cleaned or ["General"]


def normalize_scheme(raw: dict[str, Any]) -> dict[str, Any]:
    name = _clean_text(raw.get("name") or raw.get("scheme_name"))
    description = _clean_text(raw.get("description") or raw.get("details"))
    categories = _clean_categories(raw.get("category") or raw.get("categories"))
    scheme_id = _clean_text(raw.get("id") or re.sub(r"[^A-Z0-9]+", "-", name.upper())[:48])
    search_text = " ".join(
        [
            name,
            description,
            _clean_text(raw.get("state"), "All"),
            _clean_text(raw.get("gender"), "All"),
            " ".join(categories),
        ]
    )
    return {
        "id": scheme_id,
        "name": name,
        "description": description,
        "state": _clean_text(raw.get("state"), "All"),
        "gender": _clean_text(raw.get("gender"), "All"),
        "age_min": _clean_int(raw.get("age_min"), 0),
        "age_max": _clean_int(raw.get("age_max"), 120),
        "category": categories,
        "income_limit_inr": _clean_int(raw.get("income_limit_inr"), 9999999),
        "apply_url": _clean_text(raw.get("apply_url") or raw.get("url") or "#"),
        "source_url": _clean_text(raw.get("source_url") or raw.get("apply_url")),
        "source_portal": _clean_text(raw.get("source_portal")),
        "language": _clean_text(raw.get("language"), "en"),
        "search_text": _clean_text(search_text),
    }


def load_json_schemes(path: str | Path = "schemes.json") -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        return [normalize_scheme(item) for item in json.load(handle)]


@dataclass
class CitizenProfile:
    age: int
    gender: str
    state: str
    category: str
    income: int
    need: str = ""

    @classmethod
    def from_session(cls, user_data: dict[str, Any]) -> "CitizenProfile":
        return cls(
            age=_clean_int(user_data.get("age"), 0),
            gender=_clean_text(user_data.get("gender"), "All"),
            state=_clean_text(user_data.get("state"), "All"),
            category=_clean_text(user_data.get("category"), "General"),
            income=_clean_int(user_data.get("income"), 9999999),
            need=_clean_text(user_data.get("need")),
        )

    def query_text(self) -> str:
        return (
            f"{self.need}. Citizen is {self.age} years old, {self.gender}, "
            f"from {self.state}, category {self.category}, family income INR {self.income}."
        )


class BGEEmbedder:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        self.model_name = model_name
        self._model = None

    @property
    def available(self) -> bool:
        try:
            self._load()
            return True
        except Exception:
            return False

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            local_files_only = os.getenv("BGE_LOCAL_FILES_ONLY", "1").lower() not in {"0", "false", "no"}
            self._model = SentenceTransformer(self.model_name, local_files_only=local_files_only)
        return self._model

    def embed(self, texts: str | Iterable[str]) -> list[float] | list[list[float]]:
        model = self._load()
        single = isinstance(texts, str)
        payload = [texts] if single else list(texts)
        vectors = model.encode(payload, normalize_embeddings=True)
        values = vectors.tolist()
        return values[0] if single else values


class SchemeStore:
    def __init__(self, database_url: str | None = None, embedding_dim: int = DEFAULT_EMBEDDING_DIM) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL
        self.embedding_dim = embedding_dim

    @property
    def enabled(self) -> bool:
        return bool(self.database_url)

    def _connect(self, register_vectors: bool = True) -> Any:
        import psycopg

        kwargs = {}
        if "connect_timeout" not in self.database_url:
            kwargs["connect_timeout"] = int(os.getenv("PGCONNECT_TIMEOUT", "8"))
        conn = psycopg.connect(self.database_url, **kwargs)
        if register_vectors:
            from pgvector.psycopg import register_vector

            register_vector(conn)
        return conn

    def initialize(self) -> None:
        if not self.enabled:
            return
        schema = Path("db_schema.sql").read_text(encoding="utf-8")
        if self.embedding_dim != 1024:
            schema = schema.replace("vector(1024)", f"vector({self.embedding_dim})")
        with self._connect(register_vectors=False) as conn:
            conn.execute(schema)

    def count_schemes(self) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        with self._connect() as conn:
            return int(conn.execute("SELECT count(*) FROM government_schemes;").fetchone()[0])

    def user_exists(self, username: str) -> bool:
        if not self.enabled:
            return False
        self.initialize()
        with self._connect(register_vectors=False) as conn:
            row = conn.execute(
                "SELECT 1 FROM app_users WHERE username = %s;",
                (username,),
            ).fetchone()
        return row is not None

    def create_user(self, username: str, password: str, profile: dict[str, Any]) -> None:
        if not self.enabled:
            return
        self.initialize()
        salt = secrets.token_hex(16)
        password_hash = _hash_password(password, salt)
        with self._connect(register_vectors=False) as conn:
            conn.execute(
                """
                INSERT INTO app_users (username, password_hash, salt, profile)
                VALUES (%s, %s, %s, %s::jsonb);
                """,
                (username, password_hash, salt, json.dumps(profile)),
            )

    def authenticate_user(self, username: str, password: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        self.initialize()
        with self._connect(register_vectors=False) as conn:
            row = conn.execute(
                """
                SELECT password_hash, salt, profile
                FROM app_users
                WHERE username = %s;
                """,
                (username,),
            ).fetchone()
            if not row:
                return None
            password_hash, salt, profile = row
            if not hmac.compare_digest(password_hash, _hash_password(password, salt)):
                return None
            conn.execute(
                "UPDATE app_users SET last_login_at = now() WHERE username = %s;",
                (username,),
            )
        return dict(profile)

    def upsert_many(self, schemes: list[dict[str, Any]], embedder: BGEEmbedder | None = None) -> None:
        if not self.enabled:
            return
        self.initialize()
        texts = [scheme["search_text"] for scheme in schemes]
        vectors = embedder.embed(texts) if embedder else [None for _ in schemes]
        sql = """
            INSERT INTO government_schemes (
                id, name, description, state, gender, age_min, age_max, category,
                income_limit_inr, apply_url, source_url, source_portal, language,
                search_text, embedding, updated_at, last_scraped_at
            )
            VALUES (
                %(id)s, %(name)s, %(description)s, %(state)s, %(gender)s,
                %(age_min)s, %(age_max)s, %(category)s, %(income_limit_inr)s,
                %(apply_url)s, %(source_url)s, %(source_portal)s, %(language)s,
                %(search_text)s, %(embedding)s, now(), now()
            )
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                state = EXCLUDED.state,
                gender = EXCLUDED.gender,
                age_min = EXCLUDED.age_min,
                age_max = EXCLUDED.age_max,
                category = EXCLUDED.category,
                income_limit_inr = EXCLUDED.income_limit_inr,
                apply_url = EXCLUDED.apply_url,
                source_url = EXCLUDED.source_url,
                source_portal = EXCLUDED.source_portal,
                language = EXCLUDED.language,
                search_text = EXCLUDED.search_text,
                embedding = EXCLUDED.embedding,
                updated_at = now(),
                last_scraped_at = now();
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                for scheme, vector in zip(schemes, vectors):
                    cur.execute(sql, {**scheme, "embedding": vector})

    def hybrid_search(
        self,
        profile: CitizenProfile,
        query_embedding: list[float] | None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        vector_score = "0.0"
        vector_order = "name"
        params: dict[str, Any] = {
            "age": profile.age,
            "gender": profile.gender.lower(),
            "state": profile.state.lower(),
            "category": profile.category,
            "income": profile.income,
            "limit": limit,
        }
        if query_embedding:
            vector_score = "1 - (embedding <=> %(embedding)s::vector)"
            vector_order = "semantic_score DESC NULLS LAST, name"
            params["embedding"] = query_embedding

        sql = f"""
            SELECT id, name, description, state, gender, age_min, age_max,
                   category, income_limit_inr, apply_url, source_url, source_portal,
                   language, search_text, {vector_score} AS semantic_score
            FROM government_schemes
            WHERE (%(age)s BETWEEN age_min AND age_max)
              AND (lower(gender) = 'all' OR lower(gender) = %(gender)s)
              AND (lower(state) = 'all' OR lower(state) = %(state)s)
              AND EXISTS (
                  SELECT 1 FROM unnest(category) c
                  WHERE lower(c) = lower(%(category)s)
              )
              AND (%(income)s <= income_limit_inr)
            ORDER BY {vector_order}
            LIMIT %(limit)s;
        """
        with self._connect() as conn:
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()
            columns = [item.name for item in cursor.description]
        return [dict(zip(columns, row)) for row in rows]


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    )
    return digest.hex()


def deterministic_filter(schemes: list[dict[str, Any]], profile: CitizenProfile) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    category = profile.category.lower()
    for scheme in schemes:
        categories = [item.lower() for item in scheme["category"]]
        if scheme["gender"].lower() not in {"all", profile.gender.lower()}:
            continue
        if scheme["state"].lower() not in {"all", profile.state.lower()}:
            continue
        if not scheme["age_min"] <= profile.age <= scheme["age_max"]:
            continue
        if category not in categories:
            continue
        if profile.income > scheme["income_limit_inr"]:
            continue
        matches.append(scheme)
    return matches


def lexical_score(query: str, scheme: dict[str, Any]) -> float:
    query_terms = set(re.findall(r"[a-z0-9]+", query.lower()))
    doc_terms = set(re.findall(r"[a-z0-9]+", scheme["search_text"].lower()))
    if not query_terms:
        return 0.0
    return len(query_terms & doc_terms) / len(query_terms)


def _scheme_text(scheme: dict[str, Any]) -> str:
    return " ".join(
        [
            _clean_text(scheme.get("name")),
            _clean_text(scheme.get("description")),
            _clean_text(scheme.get("search_text")),
            _clean_text(scheme.get("source_portal")),
            _clean_text(scheme.get("source_url")),
        ]
    ).lower()


def profile_intent(profile: CitizenProfile) -> str | None:
    need = profile.need.lower()
    for intent, terms in INTENT_TERMS.items():
        if any(term in need for term in terms["need"]):
            return intent
    return None


def intent_score(profile: CitizenProfile, scheme: dict[str, Any]) -> float:
    intent = profile_intent(profile)
    if not intent:
        return 0.0

    text = _scheme_text(scheme)
    terms = INTENT_TERMS[intent]
    positive = intent_positive_count(profile, scheme)
    negative = sum(1 for term in terms["negative"] if term in text)
    score = min(positive, 4) * 0.35
    if positive == 0 and negative:
        score -= 1.25
    else:
        score -= min(negative, 3) * 0.2
    return score


def intent_positive_count(profile: CitizenProfile, scheme: dict[str, Any]) -> int:
    intent = profile_intent(profile)
    if not intent:
        return 0
    text = _scheme_text(scheme)
    return sum(1 for term in INTENT_TERMS[intent]["positive"] if term in text)


def relevance_score(profile: CitizenProfile, scheme: dict[str, Any]) -> float:
    semantic = float(scheme.get("semantic_score") or 0.0)
    lexical = lexical_score(profile.query_text(), scheme)
    return semantic + lexical + intent_score(profile, scheme)


def rerank_schemes(profile: CitizenProfile, schemes: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    intent = profile_intent(profile)
    if intent:
        schemes = [scheme for scheme in schemes if intent_positive_count(profile, scheme) > 0]
    return sorted(schemes, key=lambda item: relevance_score(profile, item), reverse=True)[:limit]


class HybridRetriever:
    def __init__(self, json_path: str | Path = "schemes.json") -> None:
        self.json_path = json_path
        self.store = SchemeStore()
        self.embedder = BGEEmbedder()

    def search(self, profile: CitizenProfile, limit: int = 8) -> tuple[list[dict[str, Any]], str]:
        query_embedding = None
        try:
            query_embedding = self.embedder.embed(profile.query_text())
        except Exception:
            query_embedding = None

        db_was_available = self.store.enabled
        if self.store.enabled:
            try:
                candidate_limit = max(limit * 6, 30)
                results = self.store.hybrid_search(profile, query_embedding, limit=candidate_limit)
                if results:
                    ranked = rerank_schemes(profile, results, limit)
                    if ranked:
                        return ranked, "PostgreSQL + pgvector hybrid retrieval + intent reranking"
            except Exception:
                pass

        scraped = self._scrape_on_miss(profile, limit=limit)
        if scraped:
            mode = "live website scrape fallback"
            if db_was_available:
                mode = "PostgreSQL miss + live website scrape fallback"
            return scraped, mode

        seeded = self._seed_curated_schemes(profile, limit=limit)
        if seeded:
            return seeded, "curated sample seed fallback with intent reranking"

        return [], "no grounded results - AI chatbot fallback"

    def _scrape_on_miss(self, profile: CitizenProfile, limit: int) -> list[dict[str, Any]]:
        if os.getenv("SARATHI_SCRAPE_ON_MISS", "1").lower() in {"0", "false", "no"}:
            return []

        scrape_limit = _clean_int(os.getenv("SARATHI_SCRAPE_ON_MISS_LIMIT"), max(limit, 8))
        scrape_limit = max(1, min(scrape_limit, 25))
        scraped: list[dict[str, Any]] = []

        try:
            from .scraper import (
                PortalConfig,
                scrape_india_gov_schemes_sync,
                scrape_myscheme_pages_sync,
                scrape_portal_sync,
            )
        except Exception:
            return []

        scrapers = [
            lambda: scrape_myscheme_pages_sync(limit=scrape_limit, max_scrolls=4),
            lambda: scrape_india_gov_schemes_sync(limit=scrape_limit),
        ]
        scrapers.extend(self._configured_portal_scrapers(PortalConfig, scrape_portal_sync, scrape_limit))

        for scrape in scrapers:
            try:
                scraped.extend(scrape())
            except Exception:
                continue

        if not scraped:
            return []

        unique_by_id = {scheme["id"]: normalize_scheme(scheme) for scheme in scraped}
        normalized = list(unique_by_id.values())
        if self.store.enabled:
            try:
                self.store.upsert_many(normalized, embedder=None)
            except Exception:
                pass

        matches = deterministic_filter(normalized, profile)
        return rerank_schemes(profile, matches, limit)

    def _configured_portal_scrapers(self, portal_config: Any, scrape_portal: Any, limit: int) -> list[Any]:
        config_path = Path(os.getenv("SARATHI_PORTALS_CONFIG", "portals.example.json"))
        if not config_path.exists():
            return []
        try:
            configs = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return [
            lambda item=item: scrape_portal(portal_config(**item), limit=limit)
            for item in configs
            if isinstance(item, dict)
        ]

    def _seed_curated_schemes(self, profile: CitizenProfile, limit: int) -> list[dict[str, Any]]:
        try:
            curated = load_json_schemes(self.json_path)[:15]
        except (FileNotFoundError, json.JSONDecodeError):
            return []

        if self.store.enabled:
            try:
                self.store.upsert_many(curated, embedder=None)
            except Exception:
                pass

        matches = deterministic_filter(curated, profile)
        return rerank_schemes(profile, matches, limit)


class GeminiExplainer:
    def __init__(self, model_name: str = "gemini-1.5-flash") -> None:
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model_name = model_name

    def explain(self, profile: CitizenProfile, schemes: list[dict[str, Any]]) -> str:
        if not schemes:
            return self._general_recommendations(profile)
        if not self.api_key:
            return self._fallback(profile, schemes)
        try:
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model_name)
            prompt = self._prompt(profile, schemes)
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception:
            return self._fallback(profile, schemes)

    def _prompt(self, profile: CitizenProfile, schemes: list[dict[str, Any]]) -> str:
        grounded = json.dumps(schemes, ensure_ascii=False, indent=2)
        return f"""
You are Sarathi, a government scheme assistant. Use only the grounded schemes below.
Explain why each recommendation fits the citizen profile. Do not invent benefits,
deadlines, eligibility rules, or links. If a detail is missing, say it is not available.

Citizen profile:
- Age: {profile.age}
- Gender: {profile.gender}
- State: {profile.state}
- Category: {profile.category}
- Annual family income: INR {profile.income}
- Stated need: {profile.need or "Not specified"}

Grounded retrieved schemes:
{grounded}

        Return concise, personalized recommendations in Markdown.
"""

    def _general_recommendations(self, profile: CitizenProfile) -> str:
        if not self.api_key:
            return self._general_fallback(profile)
        try:
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model_name)
            response = model.generate_content(self._general_prompt(profile))
            return response.text.strip()
        except Exception:
            return self._general_fallback(profile)

    def _general_prompt(self, profile: CitizenProfile) -> str:
        return f"""
You are Sarathi, a government scheme assistant. No verified local scheme rows matched this citizen.
Give general, non-final recommendations for likely Indian government scheme categories to check.
Do not invent exact eligibility, benefit amounts, deadlines, or application links.
Tell the user to verify details on official portals such as myScheme, National Health Authority,
National Scholarship Portal, state government portals, or the relevant ministry website.

Citizen profile:
- Age: {profile.age}
- Gender: {profile.gender}
- State: {profile.state}
- Category: {profile.category}
- Annual family income: INR {profile.income}
- Stated need: {profile.need or "Not specified"}

Return concise Markdown with 3-5 likely directions and what documents/details to verify.
"""

    def _general_fallback(self, profile: CitizenProfile) -> str:
        need = profile.need.lower()
        if any(term in need for term in ("health", "medical", "mediclaim", "hospital", "insurance", "ayushman")):
            focus = [
                "Ayushman Bharat / PM-JAY or your state's health assurance scheme",
                "state health insurance or cashless treatment schemes",
                "accident and life insurance schemes for low-income households",
            ]
        elif any(term in need for term in ("farming", "farmer", "agriculture", "crop", "kisan")):
            focus = [
                "PM-KISAN or state farmer income-support schemes",
                "crop insurance and disaster compensation schemes",
                "agriculture equipment, irrigation, and credit subsidy schemes",
            ]
        else:
            focus = [
                "central schemes on myScheme.gov.in for your stated need",
                "your state government's welfare portal",
                "scholarship, insurance, housing, employment, or business-support schemes based on your need",
            ]
        items = "\n".join(f"- {item}" for item in focus)
        return (
            "I could not find a verified local match yet, so treat these as general directions to verify on official portals:\n"
            f"{items}\n\n"
            "Keep Aadhaar, income certificate, caste/category certificate if applicable, bank details, and state residency proof ready."
        )

    def _fallback(self, profile: CitizenProfile, schemes: list[dict[str, Any]]) -> str:
        lines = [
            "Here are grounded recommendations based on your profile and the available scheme data:"
        ]
        for scheme in schemes[:5]:
            income = scheme["income_limit_inr"]
            cap = "no listed income limit" if income >= 9999999 else f"income up to INR {income:,}"
            lines.append(
                f"- **{scheme['name']}**: fits because it supports {scheme['state']} residents "
                f"or all India, allows {scheme['gender']} applicants, covers age "
                f"{scheme['age_min']}-{scheme['age_max']}, includes {', '.join(scheme['category'])}, "
                f"and has {cap}. {scheme['description']}"
            )
        return "\n".join(lines)
