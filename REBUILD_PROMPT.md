# Prompt odtworzenia projektu „Logoped Assist”

> Ten plik jest **samowystarczalnym promptem** dla agenta AI (np. Claude Code), z którego można zbudować
> projekt od zera. Opisuje docelowy stan aplikacji, decyzje architektoniczne i ich uzasadnienie.
> **Utrzymanie:** każda zmiana funkcjonalności, modelu danych, API, konfiguracji lub wdrożenia musi być
> odzwierciedlona w odpowiedniej sekcji poniżej oraz dopisana do „Historii zmian” na końcu pliku.
>
> Ostatnia aktualizacja: 2026-11-06

---

## 1. Zadanie

Zbuduj aplikację webową **Logoped Assist** – asystenta AI dla logopedów (lekarzy logopedów) z czatem RAG
opartym na bazie wiedzy logopedycznej, kartami pacjentów, dyktowaniem notatek, panelem pacjenta i panelem
administratora. Cały interfejs, komunikaty API, komentarze i dokumentacja – **po polsku**.

Wymagania ogólne:

- monorepo: `backend/` (Python, FastAPI), `frontend/` (Angular), `deploy/`, `docker-compose*.yml`, `.github/workflows/`;
- LLM i embeddingi z **zewnętrznego serwera vLLM** (API zgodne z OpenAI), transkrypcja z **zewnętrznego API Whisper**;
- dane osobowe pacjentów nie mogą trafiać do LLM (anonimizacja – sekcja 6);
- każda odpowiedź asystenta ma mieć **źródła** z bazy wiedzy;
- testy backendu (pytest) i frontendu (Karma/Jasmine) dla każdej funkcji; lint `ruff` (długość linii 100).

## 2. Stos technologiczny

| Warstwa | Technologie |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLModel/SQLAlchemy async (asyncpg; testy: aiosqlite), pydantic-settings, PyJWT, bcrypt, `openai` (AsyncOpenAI → vLLM), httpx, LangGraph, qdrant-client, sentence-transformers (Cross-Encoder), pypdf, Pillow, pytesseract, python-multipart; menedżer pakietów **uv** (`pyproject.toml` + `uv.lock`, torch CPU z indeksu pytorch-cpu) |
| Frontend | Angular 17.3 (standalone components, Signals, `ChangeDetectionStrategy.OnPush`, nowa składnia `@if/@for`), Tailwind CSS 3.4, Chart.js 4 + ng2-charts 6, RxJS 7.8 |
| Dane | PostgreSQL 16, Qdrant 1.12 (wektory gęste + rzadkie) |
| OCR | Tesseract 5 z językiem `pol` (pakiety `tesseract-ocr tesseract-ocr-pol` w obrazie backendu) |
| Infrastruktura | Docker, docker compose, nginx (frontend + reverse proxy `/api`), GitHub Actions → GHCR → SSH deploy |

## 3. Role i uprawnienia

| Rola (`users.role`) | W UI | Dostęp |
| --- | --- | --- |
| `ROLE_ADMIN` | Administrator | panel admina (`/admin`, `/admin/knowledge`, `/admin/llm`) **oraz** wszystko co lekarz (własni pacjenci, czat) |
| `ROLE_DOCTOR` | Użytkownik (logopeda) | własni pacjenci, notatki, zalecenia, powiadomienia, asystent |
| `ROLE_PATIENT` | Pacjent | wyłącznie panel pacjenta `/patient` (`GET /api/portal/me`) |

- Zależności FastAPI: `CurrentDoctor = require_roles(DOCTOR, ADMIN)`, `CurrentAdmin`, `CurrentPatient`.
- Każde zapytanie o pacjentów/notatki/rozmowy filtruje po `user_id` zalogowanego; cudzy zasób → **404**.
- Rejestracja publiczna tworzy `ROLE_DOCTOR`. Konto z `ADMIN_EMAIL` jest tworzone przy starcie
  (`ADMIN_PASSWORD`), a jeśli już istnieje – dostaje rolę admina (hasło bez zmian).
- `python -m src.manage sole-admin [email]` – zostawia admina tylko temu kontu, pozostałym adminom daje `ROLE_DOCTOR`.
- JWT (HS256, `sub`=id, `role`, `exp`), token w `localStorage`; nieaktywne konto → 401 nawet z ważnym tokenem.
  Rola jest sprawdzana z bazy przy każdym żądaniu.

## 4. Model danych (PostgreSQL, `SQLModel.metadata.create_all` przy starcie – bez Alembica)

Nowe funkcje dodawaj **nowymi tabelami**, a nie kolumnami w istniejących (brak migracji).

| Tabela | Najważniejsze pola |
| --- | --- |
| `users` | email (unique, lowercase), full_name, hashed_password, role, is_active, created_at |
| `patients` | user_id (lekarz), first_name, last_name, birth_date, icd_code, diagnosis, description (do 5000 zn.) |
| `patient_notes` | user_id, patient_id, content, source (`typed`/`dictated`) |
| `chat_history` | user_id, conversation_id (uuid), patient_id (nullable), role (`user`/`assistant`), content, sources (JSON), total_tokens |
| `token_usage` | user_id (nullable = system), model_name, operation, prompt/completion/total_tokens, timestamp |
| `patient_accounts` | patient_id (unique) ↔ user_id (unique) – powiązanie karty z kontem pacjenta |
| `patient_recommendations` | user_id, patient_id, title, content, created_at, updated_at |
| `patient_notifications` | user_id, patient_id, recipient, subject, body, status (`sent`/`failed`), error |
| `llm_calls` | user_id, operation, model_name, request (JSON – wiadomości **po anonimizacji**), response, status, error, tokeny, duration_ms |
| `kb_documents` | title, filename, category, audience, icd10, icd11, tags, text (pełny odczytany tekst), chunks, status (`pending`/`indexed`/`error`), error, uploaded_by, source_path (import z katalogu), content_hash, pages, created_at, indexed_at |
| `kb_private_documents` | document_id (PK → kb_documents), owner_id (→ users) – dokument prywatny; brak wpisu = wiedza wspólna |
| `kb_ocr_pages` | sha256 (PK obrazu), text, confidence – pamięć podręczna OCR |

Usuwanie konta usuwa też jego prywatne materiały bazy wiedzy (wiersze i punkty w Qdrant), a w materiałach
wspólnych zeruje `uploaded_by`. Usuwanie pacjenta (`purge_patients`) kasuje notatki, zalecenia, powiadomienia i powiązanie konta,
a w `chat_history` zeruje `patient_id`. Usuwanie użytkownika robi to dla wszystkich jego pacjentów
i zeruje `user_id` w `token_usage` i `llm_calls`.

## 5. Czat RAG (LangGraph)

Graf: `rewrite_query → retrieve → rerank → generate | generate_without_context → report_usage`.

1. **rewrite_query** – LLM (temperatura 0) przepisuje pytanie (+ 4 ostatnie wiadomości historii
   + kontekst pacjenta) na samodzielne zapytanie wyszukiwawcze po polsku i proponuje opcjonalne filtry
   `category ∈ {disorder, icd, technique, diagnostics}`, `audience ∈ {children, adults}`; zwraca wyłącznie JSON
   (odporny parser `parse_rewrite_output`, fallback = oryginalne pytanie). Do zapytania zawsze dopinane są
   rozpoznanie i kod ICD z kontekstu pacjenta (`with_clinical_terms`).
   **Baza jest przeszukiwana zawsze** (brak trybu „bez wyszukiwania”) – każda odpowiedź ma mieć źródła.
2. **retrieve** – embedding zapytania (vLLM), wyszukiwanie hybrydowe w Qdrant ograniczone filtrem widoczności
   (`search_filter`: fragmenty bez pola `owner_id` – wspólne i wbudowane – lub z `owner_id` = pytający): wektor gęsty + wektor rzadki
   (hash tokenów przyciętych do 6 znaków, IDF po stronie Qdrant) z fuzją **RRF**, `RETRIEVAL_TOP_K=12`.
   Filtr kategorii/grupy **nie wyklucza** dokumentów: wyniki z filtrem i bez filtra są łączone (`merge_candidates`),
   o kolejności decyduje reranker. Gdy brak wyników – ponowna próba z oryginalnym pytaniem.
3. **rerank** – lokalny Cross-Encoder `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (rozgrzewany przy starcie;
   gdy nie da się go wczytać – kolejność RRF). Zwraca `RERANK_TOP_N=4` fragmenty z wynikiem ≥ `RERANK_MIN_SCORE`;
   gdy żaden nie przekracza progu – `RERANK_FALLBACK_N=2` najlepsze z flagą `low_relevance` (UI: „luźno związane”,
   prompt: zaznacz słabe dopasowanie). Wysyła zdarzenie `sources`.
4. **generate** – strumieniowanie odpowiedzi; prompt systemowy: rzeczowo, po polsku, **każde merytoryczne
   stwierdzenie z odnośnikiem [n]**, bez zmyślania, decyzje kliniczne należą do lekarza, wskazuj skierowania,
   wykorzystaj wszystkie cechy pacjenta, znaczniki anonimizacji traktuj jak zwykłe odniesienia.
   Kontekst pacjenta: wiek (u dzieci „6 lat 3 mies. (6;3)”), płeć (z imienia), ICD, rozpoznanie, **pełny opis**.
5. **report_usage** – suma tokenów ze wszystkich węzłów (reducer `merge_usage`).

API `POST /api/chat` zwraca **SSE**: `meta`, `status`, `sources`, `token`, `usage`, `error`, `done`;
wiadomości zapisywane w `chat_history`. Frontend czyta strumień przez `fetch` + `ReadableStream`
(EventSource nie obsługuje POST/Authorization). Czat obsługuje `?conversation=…&patient=…`.

## 6. Prywatność i anonimizacja (`src/anonymizer.py`, wywoływana centralnie w `src/llm.py`)

Każdy tekst wysyłany do LLM (czat, przepisywanie, embedding zapytań) przechodzi przez anonimizator –
**usuwane są wyłącznie**:

- imiona i nazwiska **wszystkich pacjentów zalogowanego lekarza** (z tabeli `patients`), także w odmianie
  (rdzenie + polskie końcówki, formy żeńskie nazwisk -owa/-ówna), bez względu na wielkość liter;
  imię → `[IMIĘ PACJENTA]` / `[IMIĘ PACJENTKI]` (płeć z końcówki „-a”, wyjątki: Kuba, Barnaba…), nazwisko → `[NAZWISKO]`;
- PESEL (11 cyfr) → `[PESEL]`, telefon (9 cyfr, opcjonalnie +48) → `[TELEFON]`,
  adres (`ul./al./os./pl.` + do 3 słów z wielkiej litery + numer) i kod pocztowy → `[ADRES]`.

**Nie** anonimizuj wieku, płci, rozpoznania, ICD, cech szczególnych, dat ani liczb – nie wolno osłabiać
jakości odpowiedzi. Do embeddingu idzie wersja bez znaczników (`for_search`). Log LLM zapisuje wersję
zanonimizowaną. Treści systemowe (seed bazy wiedzy, `user_id=None`) nie są anonimizowane.

## 7. Funkcje lekarza

- **Dashboard** – lista pacjentów z wyszukiwarką, dodawanie pacjenta, ostatnie notatki; tło: półprzezroczysta
  grafika `logoped-monochrome.png` przyklejona do dołu nad stopką; stała stopka 48 px (`h-12`, `#02121c`)
  z „© 2026 Webaby” i ikonami social media (WhatsApp, Facebook, Instagram, X).
- **Karta pacjenta** – edycja danych, nowa notatka (wpisywana lub **dyktowana**: `MediaRecorder` →
  `POST /api/audio/transcribe` → Whisper, język `pl`, limit 25 MB, dozwolone formaty audio), lista notatek.
- **Historia pacjenta** – zakładki „Sesje i notatki” oraz „Pytania do asystenta” (`GET /api/patients/{id}/chat-history`:
  wiadomości z `patient_id` pacjenta, łączone w pary pytanie–odpowiedź, link „Otwórz rozmowę”).
- **Konto pacjenta, zalecenia, powiadomienia** (komponent `patient-care`): utworzenie/powiązanie konta pacjenta
  (`PUT /api/patients/{id}/account` – istniejące konto musi mieć `ROLE_PATIENT` i nie być powiązane z inną kartą;
  nowe wymaga hasła), odłączenie; CRUD zaleceń z opcją „powiadom e-mailem”; wysyłka powiadomień e-mail
  (SMTP z biblioteki standardowej w wątku; brak konfiguracji → zapis ze statusem `failed`).
- **Asystent** – czat ze źródłami (rozwijana lista, trafność, znacznik „luźno związane”), wybór pacjenta,
  lista rozmów, licznik tokenów; tło `logoped-sepia.png`.

## 8. Panel pacjenta (`/patient`)

Rozpoznanie, ICD, wiek, logopeda prowadzący (mailto), zalecenia i powiadomienia. **Bez notatek lekarza.**
Konto niepowiązane z kartą → komunikat 404.

## 9. Panel administratora

- **`/admin`** – statystyki zużycia tokenów (per dzień – wykres słupkowy skumulowany, per model – doughnut,
  per użytkownik, per operacja; zakres 7/30/90/365 dni), kafelki (tokeny, zapytania, konta, **fragmenty** w bazie wiedzy)
  z gradientowym tłem i paskiem akcentu. Styl wykresów w `admin-panel/chart-style.ts`: paleta kategorialna
  w stałej kolejności `#0d9488, #4f7cff, #f59e0b, #e4572e, #8b5cf6, #db2777` (zweryfikowana walidatorem palet –
  jasność, nasycenie, rozróżnialność przy daltonizmie; powyżej 6 modeli reszta w „Inne”), gradient trzybarwny
  (ciemniejszy odcień serii przy osi → kolor serii → brąz `#a0612f` zmieszany w 85% z kolorem serii), rozpięty
  od osi do najwyższej wartości na wykresie (nie do końca osi), słupki ≤ 24 px z zaokrąglonym końcem, 2 px odstępu
  w kolorze tła między segmentami, stonowana siatka 1 px, skrócone liczby na osi (tys./mln), tooltipy pl-PL, zarządzanie kontami:
  tworzenie (`POST /api/admin/users` z rolą), zmiana roli z listy (opcje z `[selected]`, nie `[value]` na select –
  inaczej przeglądarka pokazuje zawsze pierwszą opcję), nowe hasło, blokowanie, usuwanie; własnego konta nie można zmienić.
- **`/admin/llm`** – log zapytań LLM: lista (filtr operacji i statusu, stronicowanie po 50) i szczegóły
  (wiadomości wysłane do modelu i odpowiedź). Retencja `LLM_LOG_RETENTION_DAYS` (czyszczenie przy starcie).
- **`/admin/knowledge`** – baza wiedzy RAG (sekcja 10).

## 10. Baza wiedzy RAG

**Widoczność:** każdy materiał jest **wspólny** (dla wszystkich użytkowników, w odpowiedziach dla każdego)
albo **prywatny** (tylko dla konta, które go dodało – w panelu i w jego rozmowach z asystentem). Wybór przy
dodawaniu pliku i folderu (domyślnie wspólna) oraz w edycji. Fragmenty prywatne mają w Qdrant pole `owner_id`
(indeks INTEGER), wspólne – nie mają go wcale. Cudze materiały prywatne są niewidoczne w panelu, a operacje
na nich zwracają 404. Pliki prywatne leżą w `prywatne/<id konta>/…` katalogu materiałów (także przy rsync);
upload „wspólny” do folderu `prywatne/` jest odrzucany; konto z nieistniejącym id → błąd importu.
Deduplikacja działa w obrębie zakresu (ten sam plik może być wspólny i czyimś prywatnym). Widoczność ustalona
przy utworzeniu nie jest nadpisywana przez kolejne importy (zmiana tylko w panelu).

Źródła: 23 **hasła wbudowane** (`seed_data.py`: jednostki chorobowe, kodowanie ICD-10/11, normy rozwoju mowy,
techniki terapii – zasilane przy starcie, `python -m src.seed [--force]`) oraz **materiały administratora**.

**Katalog materiałów** – na serwerze `/opt/logoped-kb`, w kontenerze `/kb` (zapis dozwolony; lokalnie
domyślnie `../laryngolog`, zmienna `KB_SOURCE_HOST_DIR`). Import (`src/kb_import.py`, idempotentny):

- pliki tekstowe `.pdf` (z warstwą tekstową – skany odrzucane), `.docx`, `.odt`, `.md`, `.txt` → po jednym dokumencie;
- zdjęcia stron `.jpg/.png/…` → **podkatalog = jeden dokument** (strony w kolejności EXIF DateTimeOriginal);
  zdjęcia luzem w katalogu głównym dzielone na dokumenty wg sesji (przerwa > `KB_SESSION_GAP_MINUTES=30`);
- duplikaty (SHA-256) przetwarzane raz: dla plików tekstowych wygrywa kopia położona najpłycej, dla zdjęć – z podkatalogu;
- pliki i katalogi ukryte (kropka) są pomijane (`.pominiete/` = wykluczone materiały, pliki tymczasowe uploadu);
- dokument pomijany tylko gdy `content_hash` się nie zmienił **i** `status == indexed` (przerwany import jest ponawiany);
- tytuł dokumentu ze zdjęć = pierwsza sensowna linia OCR; tytuł/metadane ustawione w panelu zostają przy aktualizacji;
- usunięcie w panelu nie usuwa pliku – dokument wróci przy synchronizacji, jeśli plik nadal jest w katalogu.

**OCR** (`src/ocr.py`): Tesseract `pol+eng`, tylko druk – słowa z pewnością < `OCR_MIN_WORD_CONFIDENCE=60`
odrzucane, linia zostaje gdy większość słów jest pewna (pismo odręczne odpada); orientacja: najpierw 0°,
jeśli pewność < 75 lub < 15 słów – próba 90/270/180° na miniaturze 1600 px i wybór najlepszego; strona
skalowana do `OCR_MAX_SIDE_PX=2600`; strony zapisane z nagłówkiem `# Strona N`.

**Indeksowanie** (`src/knowledge.py`): podział na fragmenty ~`KB_CHUNK_CHARS=1500` po akapitach, nagłówek `#`
zaczyna nowy fragment, krótki ostatni akapit jako zakładka; tytuł fragmentu „Tytuł (cz. i/n)”; embedding partiami
po 16; payload z `kb_document_id`; ponowne indeksowanie usuwa stare punkty dokumentu. `seed --force` odtwarza
w Qdrant także wszystkie materiały z `kb_documents`.

**Sposoby dodawania:** (1) panel → „Wgraj folder z komputera” (`webkitdirectory`, pliki wysyłane pojedynczo
`POST /api/admin/knowledge/files` z `relative_path`, walidacja ścieżki: bez `..`, ukrytych elementów, maks. 4 poziomy,
dozwolone rozszerzenia; zapis atomowy przez ukryty plik tymczasowy) → automatyczny start importu;
(2) rsync na serwer → **automatyczne wykrywanie zmian** co `KB_SCAN_INTERVAL_SECONDS=300` (odcisk katalogu
ze ścieżek/rozmiarów/mtime; import startuje, gdy katalog różni się od ostatnio zaimportowanego i nie zmienił się
od poprzedniego sprawdzenia); (3) „Synchronizuj katalog” / `python -m src.kb_import [/kb] [--dry-run]`;
(4) pojedynczy plik w panelu (zapisywany tylko w bazie, nie w katalogu). Edycja metadanych (PATCH) przeindeksowuje dokument.

**Wskaźnik postępu** (`import-progress` component, odpytywanie co 2 s): etapy Wysyłanie → Skanowanie →
Odczyt/OCR → Embedding → Gotowe, procent ważony liczbą stron (zdjęcia: 85% OCR / 15% embedding; pliki: 20/80),
szacowany czas do końca (po 3% pracy), bieżący dokument z paskiem „OCR: strona x z y” / „Embedding: fragment x z y”,
liczniki (nowe/zaktualizowane/bez zmian/błędy), lista 10 ostatnio przetworzonych dokumentów.

## 11. API (prefiks `/api`)

- `auth`: `POST /register`, `POST /login`, `GET /me`
- `patients`: `GET|POST /patients`, `GET /patients/notes/recent`, `GET|PUT|DELETE /patients/{id}`,
  `GET|POST /patients/{id}/notes`, `DELETE /patients/{id}/notes/{note_id}`, `GET /patients/{id}/chat-history`,
  `GET|PUT|DELETE /patients/{id}/account`, `GET|POST /patients/{id}/recommendations`,
  `PUT|DELETE /patients/{id}/recommendations/{rid}`, `GET|POST /patients/{id}/notifications`
- `portal`: `GET /portal/me`
- `chat`: `POST /chat` (SSE), `GET /chat/conversations`, `GET|DELETE /chat/conversations/{id}`
- `audio`: `POST /audio/transcribe`
- `admin`: `GET /admin/usage?days=`, `GET /admin/stats`, `GET|POST /admin/users`, `PATCH|DELETE /admin/users/{id}`,
  `GET /admin/llm-calls`, `GET /admin/llm-calls/{id}`
- `admin/knowledge` (pola formularza i PATCH z `visibility`: `shared`/`private`): `GET|POST ""`, `POST /files`, `GET|POST /import`, `PATCH|DELETE /{id}`, `POST /{id}/reindex`
- `GET /api/health`

## 12. Frontend – struktura

`core/` (serwisy: auth, admin, patients, chat, portal, audio-recording; guardy: `doctorGuard` = lekarz lub admin,
`adminGuard`, `patientGuard`, `guestGuard`; interceptor JWT z wylogowaniem przy 401),
`features/` (auth, dashboard, patient-info + patient-care, chat, admin-panel + llm-logs + knowledge-base +
import-progress, patient-portal), `shared/` (modele, navbar, utils). Trasy ładowane leniwie; `homeRoute()`:
admin → `/admin`, pacjent → `/patient`, lekarz → `/dashboard`. Kolory marki: `brand-50…900` (teal, `#237d75`
jako 600); tło `body` – gradient `#c8e4dd → #1f052e`; karty dashboardu/asystenta półprzezroczyste z gradientem.

## 13. Konfiguracja (zmienne środowiskowe)

`VLLM_BASE_URL`, `VLLM_API_KEY`, `VLLM_CHAT_MODEL` (np. Qwen/Qwen2.5-7B-Instruct), `VLLM_EMBEDDING_MODEL`
(np. BAAI/bge-m3), `WHISPER_API_URL`, `WHISPER_API_KEY`, `WHISPER_MODEL`, `POSTGRES_USER/PASSWORD/DB` (DB_URL
budowany w compose), `JWT_SECRET` (≥ 32 zn.), `ACCESS_TOKEN_EXPIRE_MINUTES`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`,
`CORS_ORIGINS`, `RERANKER_MODEL`, `RETRIEVAL_TOP_K`, `RERANK_TOP_N`, `RERANK_MIN_SCORE`, `RERANK_FALLBACK_N`,
`LLM_LOG_ENABLED`, `LLM_LOG_RETENTION_DAYS`, `SMTP_HOST/PORT/USER/PASSWORD/FROM/STARTTLS/SSL`, `APP_PUBLIC_URL`,
`KB_SOURCE_HOST_DIR`, `KB_SCAN_INTERVAL_SECONDS`, `KB_SESSION_GAP_MINUTES`, `OCR_*`, `SEED_ON_STARTUP`.
Wzorce: `.env.example` (dev) i `deploy/logoped-assist.env.example` (serwer: `/opt/logoped-assist.env`, chmod 600).

## 14. Uruchomienie i wdrożenie

- Dev: `docker compose up --build` (postgres, qdrant, backend :8000, frontend nginx :8080; wolumeny danych,
  `model_cache` dla rerankera; katalog materiałów montowany jako `/kb`).
- Backend Dockerfile: wieloetapowy (uv sync `--no-dev` → `python:3.12-slim`), Tesseract z językiem polskim,
  użytkownik `app` (UID 1000 – musi mieć zapis w katalogu materiałów), `uvicorn --proxy-headers`.
- Frontend: build Angulara + nginx (`client_max_body_size 30m`, proxy `/api` bez buforowania dla SSE,
  timeout 300 s, nagłówki bezpieczeństwa, `Permissions-Policy: microphone=(self)`).
- Prod: GitHub Actions `deploy.yml` na push do **`master`**: build i push obrazów do GHCR
  (`ghcr.io/maciejmar/logoped-assist-{backend,frontend}:latest`), scp `docker-compose.prod.yml`, SSH:
  `mkdir -p /opt/logoped-assist /opt/logoped-kb`, `docker compose --env-file /opt/logoped-assist.env pull && up -d`.
  Kontenery `lg_postgres`, `lg_qdrant`, `lg_backend` (127.0.0.1:8092), `lg_frontend`. Zmiana `.env` wymaga
  odtworzenia kontenera (`docker compose … up -d backend`), samo `restart` nie wczyta nowych zmiennych.
- Materiały na serwer: `rsync -avh --partial` z WSL (SSH port 2222) lub przez panel.

## 15. Testy i jakość

- Backend: `cd backend && uv run ruff check src tests && uv run ruff format --check src tests && uv run pytest -q`
  (conftest: SQLite w katalogu tymczasowym, fikstury `client`, `make_headers`, `fake_index` – podstawione
  embeddingi i Qdrant). Testy obejmują: izolację danych między lekarzami, role, admina, portal pacjenta,
  anonimizację (odmiany, płeć, wzorce, zachowanie treści klinicznej, zapis do logu), RAG (parser, filtry,
  źródła, fallback trafności), bazę wiedzy (formaty, skany, chunking, OCR – logika linii i orientacji,
  sesje, duplikaty, bezpieczeństwo ścieżek, idempotencja, ponawianie, postęp).
- Frontend: `npx ng test --watch=false --browsers=ChromeHeadlessNoSandbox && npx ng build`.

---

## Historia zmian

Nowe wpisy dopisuj na górze listy (data, co i dlaczego).

- **2026-11-06** – Gradienty wykresów wyrazistsze i trzybarwne (z brązem), rozpięte do najwyższej wartości.
- **2026-11-06** – Gradientowe wykresy i kafelki w panelu administratora (nowa, zweryfikowana paleta; poprzedni
  turkus był za mało nasycony, a 7. kolor był szary); kafelek pokazuje „Fragmenty w bazie wiedzy” (to liczba fragmentów
  w Qdrant, nie dokumentów).

- **2026-11-06** – Wiedza wspólna lub prywatna: wybór przy dodawaniu pliku/folderu i w edycji, filtr widoczności
  w wyszukiwaniu (pole `owner_id` w Qdrant, tabela `kb_private_documents`), katalog `prywatne/<id>/`, ukrywanie
  cudzych materiałów prywatnych w panelu; usunięcie konta usuwa jego prywatną wiedzę. Naprawiono błąd klucza obcego
  przy usuwaniu konta, które wgrało materiały (`kb_documents.uploaded_by`).

- **2026-10-19** – Filtr kategorii w wyszukiwaniu tylko wzmacnia wyniki (łączenie wyników z filtrem i bez):
  materiały administratora (kategoria „Techniki terapii”) znikały przy pytaniach zawężonych do „jednostek chorobowych”.
  Utworzono ten plik promptu odtworzenia.
- **2026-10-18** – Baza wiedzy RAG z katalogu: import (PDF/DOCX/ODT/MD/TXT + zdjęcia), OCR Tesseract (tylko druk),
  wgrywanie folderów z panelu, automatyczne wykrywanie zmian, wskaźnik postępu, edycja metadanych, pamięć
  podręczna OCR, ponawianie przerwanych dokumentów, deduplikacja.
- **2026-10-17** – Anonimizacja danych dla LLM (tylko imię, nazwisko, PESEL, telefon, adres; pełny opis i wiek
  w miesiącach w kontekście pacjenta); źródła zawsze w odpowiedzi (wyszukiwanie zawsze, fallback „luźno związane”,
  kontekst pacjenta w przepisywaniu zapytania); historia pytań do asystenta w karcie pacjenta; poprawka wyświetlania
  ról w panelu admina; panel administratora (log LLM, zarządzanie kontami), rola pacjenta, panel pacjenta,
  zalecenia i powiadomienia e-mail.
- **wcześniej** – Wersja bazowa: czat RAG (LangGraph, Qdrant hybrydowo, reranker), karty pacjentów, dyktowanie
  notatek (Whisper), statystyki tokenów, wdrożenie Docker + GitHub Actions.
