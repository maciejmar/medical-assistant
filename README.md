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

## Baza wiedzy RAG – dodawanie materiałów

Źródła wiedzy asystenta (wszystkie trafiają do Qdrant i są cytowane w odpowiedziach):

- **hasła wbudowane** – `backend/src/seed_data.py` (zmiana wymaga wdrożenia),
- **katalog z materiałami** – na serwerze `/opt/logoped-kb` (lokalnie domyślnie `../laryngolog`), montowany
  w kontenerze backendu jako `/kb` (tylko do odczytu); ścieżkę hosta zmienia `KB_SOURCE_HOST_DIR`,
- **pojedyncze pliki** wgrane w panelu *Baza wiedzy* (`/admin/knowledge`).

### Gdy dochodzą nowe materiały

1. Panel admina → *Baza wiedzy* → **Wgraj folder z komputera** → *Wyślij na serwer i zaindeksuj*. Pliki trafiają
   do katalogu materiałów na serwerze (`/opt/logoped-kb/<nazwa folderu>/`), po czym startuje import.
   Alternatywnie skopiuj pliki na serwer (np. `rsync -avh --partial ./laryngolog/ serwer:/opt/logoped-kb/`) –
   aplikacja sama wykrywa nowe i zmienione pliki (co `KB_SCAN_INTERVAL_SECONDS`, domyślnie 5 min; import startuje,
   gdy katalog przestanie się zmieniać).
   - pliki tekstowe (PDF z warstwą tekstową, DOCX, ODT, MD, TXT) – każdy plik to jeden dokument,
   - zdjęcia stron / zrzuty slajdów (JPG/PNG) – **każdy materiał w osobnym folderze** (folder = jeden dokument,
     strony w kolejności wykonania zdjęć). Zdjęcia luzem w katalogu głównym są dzielone na dokumenty według sesji
     fotografowania (przerwa > `KB_SESSION_GAP_MINUTES`, domyślnie 30 min).
2. Import (OCR → podział na fragmenty → embeddingi → Qdrant) dodaje nowe i zmienione materiały, pomija niezmienione
   i duplikaty (suma SHA-256; z kopii dokumentu tekstowego liczy się ta położona najpłycej). Ręcznie: przycisk
   **Synchronizuj katalog** albo `docker compose exec backend python -m src.kb_import [--dry-run]`.
3. Popraw w panelu tytuły i metadane (kategoria, grupa wiekowa, ICD, słowa kluczowe) – tytuł dokumentu ze zdjęć
   jest brany z pierwszej linii rozpoznanego tekstu. Zmiany zostają przy kolejnych synchronizacjach.

**OCR zdjęć:** Tesseract (lokalnie w kontenerze, obrazy nie opuszczają serwera), wyłącznie druk – słowa z niską
pewnością rozpoznania (pismo odręczne) są odrzucane. Obrócone zdjęcia są wykrywane automatycznie. Wynik OCR każdego
zdjęcia jest zapamiętywany (`kb_ocr_pages`), więc ponowna synchronizacja nie powtarza OCR. Pierwszy import kilkuset
zdjęć trwa długo (kilka sekund na stronę).

**Usuwanie:** dokument usunięty w panelu wróci przy kolejnej synchronizacji, jeśli jego plik nadal jest w katalogu –
usuń też plik. Skany PDF bez warstwy tekstowej są odrzucane (zamiast nich użyj zdjęć stron albo transkrypcji `.md`).

Tekst materiałów jest przechowywany w PostgreSQL (`kb_documents`), więc indeks można odtworzyć:
`python -m src.seed --force` (lub automatycznie przy starcie na pustym Qdrant) indeksuje ponownie hasła wbudowane
i wszystkie materiały. Nie umieszczaj w bazie wiedzy materiałów zawierających dane pacjentów.

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
- Każdy tekst wysyłany do LLM (pytanie, historia rozmowy, kontekst pacjenta, zapytanie do embeddingu) przechodzi
  przez `backend/src/anonymizer.py`: imiona i nazwiska pacjentów lekarza (z odmianą) zastępowane są przez
  `[IMIĘ PACJENTA]`/`[IMIĘ PACJENTKI]` i `[NAZWISKO]`, a PESEL, telefon i adres (z kodem pocztowym) – znacznikami.
  Nic poza tym nie jest usuwane: wiek (u dzieci z miesiącami), płeć, ICD, rozpoznanie, pełny opis z cechami
  szczególnymi, daty i liczby trafiają do modelu bez zmian. Model jest poinstruowany, jak traktować znaczniki,
  a do wyszukiwania w bazie wiedzy trafia tekst bez znaczników. Log LLM w panelu administratora zawiera już
  wersję zanonimizowaną.
- Ograniczenie: imiona osób spoza kart pacjentów (np. rodziców) wpisane wolnym tekstem nie są wykrywane.
- Nagrania do dyktowania notatek trafiają do zewnętrznego API Whisper w oryginale (głosu nie da się
  zanonimizować) – do pełnej ochrony danych Whisper powinien działać na własnej infrastrukturze.
- Token JWT jest przechowywany w `localStorage`. Przy publicznym wystawieniu aplikacji zalecane są HTTPS, polityka CSP
  i limit prób logowania na reverse proxy.

## Testy * 

```bash
cd backend  && uv sync && uv run ruff check src tests && uv run pytest
cd frontend && npm install && npx ng test --watch=false && npx ng build
```
