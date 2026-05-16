from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_MODEL_NAME = os.getenv("BGE_MODEL_NAME", "BAAI/bge-m3")
DEFAULT_EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))


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

            self._model = SentenceTransformer(self.model_name)
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
        self.database_url = database_url or os.getenv("DATABASE_URL")
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

        if self.store.enabled:
            try:
                results = self.store.hybrid_search(profile, query_embedding, limit=limit)
                if results:
                    return results, "PostgreSQL + pgvector hybrid retrieval"
            except Exception:
                pass

        schemes = deterministic_filter(load_json_schemes(self.json_path), profile)
        ranked = sorted(schemes, key=lambda item: lexical_score(profile.query_text(), item), reverse=True)
        return ranked[:limit], "local JSON deterministic filter with lexical ranking"


class GeminiExplainer:
    def __init__(self, model_name: str = "gemini-1.5-flash") -> None:
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model_name = model_name

    def explain(self, profile: CitizenProfile, schemes: list[dict[str, Any]]) -> str:
        if not schemes:
            return "I could not find a grounded match for this profile. Try widening the state, category, or income criteria."
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
