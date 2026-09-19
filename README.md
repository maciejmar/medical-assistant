# Logoped Assist

Asystent RAG dla lekarzy logopedów: czat ze źródłami (LangGraph + Qdrant + reranker), dyktowanie notatek (Whisper),
karty pacjentów izolowane per lekarz oraz panel administratora ze statystykami zużycia tokenów.

## Uruchomienie

```bash
cp .env.example .env        # uzupełnij VLLM_*, WHISPER_*, hasła i JWT_SECRET (openssl rand -hex 32)
docker compose up --build
```

- Aplikacja: http://localhost:8080 (port zmienisz w `FRONTEND_PORT`)
- Dokumentacja API (Swagger): http://localhost:8000/docs
- Konto administratora powstaje przy starcie z `ADMIN_EMAIL` / `ADMIN_PASSWORD`. Lekarze rejestrują się sami.
- Baza Qdrant jest zasilana automatycznie przy starcie (`backend/src/seed.py`, ponawianie prób, gdy vLLM jest chwilowo
  niedostępny). Ręcznie: `docker compose exec backend python -m src.seed --force`.
- Pierwsze zapytanie pobiera model rerankera do wolumenu `model_cache` (wymaga internetu). Gdy pobranie się nie uda,
  system wraca do kolejności z wyszukiwania hybrydowego (RRF).
- Nagrywanie mikrofonu działa tylko na `localhost` lub przez HTTPS (wymóg przeglądarek).

## Architektura

| Warstwa | Opis |
| --- | --- |
| `backend/src/graph` | LangGraph: `rewrite_query → retrieve → rerank → generate → report_usage`; brak źródeł lub small talk kieruje do `generate_without_context` |
| `backend/src/llm.py` | Klient `openai` (async) do zewnętrznego vLLM; każde wywołanie zapisuje wiersz w `token_usage` w tle |
| `backend/src/vector_store.py` | Qdrant: wektory gęste + rzadkie, fuzja RRF, filtry po metadanych; Cross-Encoder z `sentence-transformers` |
| `backend/src/api` | `/api/auth`, `/api/patients`, `/api/chat` (SSE), `/api/audio/transcribe`, `/api/admin` |
| `frontend/src/app` | Angular 17 (standalone, Signals), Tailwind, Chart.js / ng2-charts |

## Prywatność i bezpieczeństwo

- Każde zapytanie o pacjentów, notatki i rozmowy filtruje po `user_id` zalogowanego lekarza; cudzy zasób zwraca 404.
- Rola `ROLE_ADMIN` nie ma dostępu do endpointów lekarza. Endpointy admina zwracają tylko zagregowane metryki
  (użytkownicy są oznaczeni numerem), bez treści czatów i danych pacjentów.
- Do zewnętrznego LLM trafia kontekst pacjenta bez imienia i nazwiska (wiek, kod ICD, rozpoznanie, opis).
  Pole „opis” jest wolnym tekstem lekarza – nie wpisuj tam danych identyfikujących.
- Token JWT jest przechowywany w `localStorage`. Przy publicznym wystawieniu aplikacji zalecane są HTTPS, polityka CSP
  i limit prób logowania na reverse proxy.

## Testy

```bash
cd backend  && uv sync && uv run ruff check src tests && uv run pytest
cd frontend && npm install && npx ng test --watch=false && npx ng build
```
