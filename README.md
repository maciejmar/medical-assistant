# Logoped Assist

Asystent RAG dla lekarzy logopedów: czat ze źródłami (LangGraph + Qdrant + reranker), dyktowanie notatek (Whisper),
karty pacjentów izolowane per lekarz, panel pacjenta z zaleceniami i powiadomieniami e-mail oraz panel
administratora (statystyki zużycia, zarządzanie kontami, log zapytań LLM).

## Uruchomienie

```bash
cp .env.example .env        # uzupełnij VLLM_*, WHISPER_*, hasła i JWT_SECRET (openssl rand -hex 32)
docker compose up --build
```

- Aplikacja: http://localhost:8080 (port zmienisz w `FRONTEND_PORT`)
- Dokumentacja API (Swagger): http://localhost:8000/docs
- Konto administratora powstaje przy starcie z `ADMIN_EMAIL` / `ADMIN_PASSWORD`; jeśli konto z tym e-mailem już
  istnieje, otrzymuje rolę administratora (hasło bez zmian). Aby pozostałym administratorom odebrać tę rolę:
  `docker compose exec backend python -m src.manage sole-admin`.
- Użytkownicy (logopedzi) rejestrują się sami lub zakłada ich administrator. Konto pacjenta zakłada administrator
  albo lekarz prowadzący w karcie pacjenta (sekcja „Konto pacjenta”).
- Powiadomienia e-mail wymagają `SMTP_HOST` i `SMTP_FROM` (np. Gmail: `smtp.gmail.com`, port 587, hasło aplikacji).
  Bez SMTP powiadomienie zapisuje się w panelu pacjenta ze statusem „błąd wysyłki”.
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

## Role

| Rola | Dostęp |
| --- | --- |
| `ROLE_ADMIN` | Panel administratora (`/admin`, `/admin/llm`) oraz – jak użytkownik – własni pacjenci i asystent |
| `ROLE_DOCTOR` (w UI „Użytkownik”) | Własni pacjenci, notatki, zalecenia, powiadomienia, asystent |
| `ROLE_PATIENT` | Panel pacjenta (`/patient`): rozpoznanie, zalecenia, powiadomienia – bez notatek lekarza |

## Prywatność i bezpieczeństwo

- Każde zapytanie o pacjentów, notatki i rozmowy filtruje po `user_id` zalogowanego lekarza; cudzy zasób zwraca 404.
- Administrator nie widzi kart pacjentów ani notatek innych lekarzy. Widzi natomiast log zapytań LLM (`llm_calls`):
  pełną treść promptów (w tym pytania lekarzy i zanonimizowany kontekst pacjenta) oraz odpowiedzi modelu. Logi starsze
  niż `LLM_LOG_RETENTION_DAYS` są usuwane przy starcie; `LLM_LOG_ENABLED=false` wyłącza zapisywanie.
- Do zewnętrznego LLM trafia kontekst pacjenta bez imienia i nazwiska (wiek, kod ICD, rozpoznanie, opis).
  Pole „opis” jest wolnym tekstem lekarza – nie wpisuj tam danych identyfikujących.
- Token JWT jest przechowywany w `localStorage`. Przy publicznym wystawieniu aplikacji zalecane są HTTPS, polityka CSP
  i limit prób logowania na reverse proxy.

## Testy * 

```bash
cd backend  && uv sync && uv run ruff check src tests && uv run pytest
cd frontend && npm install && npx ng test --watch=false && npx ng build
```
