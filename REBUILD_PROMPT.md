# Prompt odtworzenia projektu „Logoped Assist”

> Ten plik jest **samowystarczalnym promptem** dla agenta AI (np. Claude Code), z którego można zbudować
> projekt od zera. Opisuje docelowy stan aplikacji, decyzje architektoniczne i ich uzasadnienie.
> **Utrzymanie:** każda zmiana funkcjonalności, modelu danych, API, konfiguracji lub wdrożenia musi być
> odzwierciedlona w odpowiedniej sekcji poniżej oraz dopisana do „Historii zmian” na końcu pliku.
>
> Ostatnia aktualizacja: 2026-11-07

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
| `interview_templates` | id=1 (jeden wiersz), questions (JSON – lista pytań, „## ” = nagłówek sekcji), updated_by, updated_at; brak wiersza = domyślny szablon z pliku `src/interview_template.txt` |
| `patient_interviews` | patient_id (PK), user_id, status (`draft`/`approved`), approved_items (JSON – migawka [{question, answer}] z chwili zatwierdzenia), approved_at |
| `patient_interview_items` | patient_id, position, question, answer, created_at, updated_at |
| `patient_interview_audio` | item_id (PK → items), patient_id, content_type, data (LargeBinary – nagranie w bazie, bez wolumenu), size |
| `patient_plans` | patient_id (PK), include_in_context (bool, domyślnie false), updated_at |
| `patient_plan_steps` | patient_id, position, title (≤200), description, status (`planned`/`completed`/`suspended`/`infeasible`), created_at, updated_at |
| `patient_events` | patient_id, type (`visit`/`consultation`/`stage_start`/`stage_end`/`other`), title, starts_at, ends_at (nullable), all_day, location, description, plan_step_id (nullable, bez FK), created_by + created_by_role (`doctor`/`patient`, bez FK), created_at, updated_at |
| `user_subscriptions` | user_id (PK), started_at (początek okien), monthly_limit_pln, updated_at; brak wiersza = data założenia konta i `BILLING_DEFAULT_LIMIT_PLN` |
| `credit_topups` | user_id, amount_pln, status (`pending`/`confirmed`/`rejected`/`cancelled`), reference (`LOGOPED-<user>-<id>` = tytuł przelewu, ręczne `RECZNE-…`), note, created_at, confirmed_at, confirmed_by |
| `payment_sessions` | topup_id (→ credit_topups), user_id (bez FK), provider (`stripe`), session_id (unique), status (`open`/`paid`/`failed`/`expired`), payment_method (blik/card/p24), amount_pln, created_at, completed_at |
| `goldset_items` | position, title, question, reference_answer – goldset (poza bazą wiedzy RAG) |
| `goldset_runs` | started_by, status (`running`/`done`/`failed`/`cancelled`), total, done, errors, note, settings (JSON – migawka: modele, reranker, top_k), avg_score, avg_similarity, avg_latency_ms, total_tokens, started_at, finished_at |
| `goldset_results` | run_id, item_id, title/question (kopie), answer, sources (JSON), verdict (JSON sędziego), score 0–5, similarity, latency_ms, tokens, judge_tokens, status, error |
| `llm_calls` | user_id, operation, model_name, request (JSON – wiadomości **po anonimizacji**), response, status, error, tokeny, duration_ms |
| `kb_documents` | title, filename, category, audience, icd10, icd11, tags, text (pełny odczytany tekst), chunks, status (`pending`/`indexed`/`error`), error, uploaded_by, source_path (import z katalogu), content_hash, pages, created_at, indexed_at |
| `kb_private_documents` | document_id (PK → kb_documents), owner_id (→ users) – dokument prywatny; brak wpisu = wiedza wspólna |
| `kb_ocr_results` | (sha256 obrazu, engine = klucz silnika z parametrami) PK, text, confidence – pamięć podręczna OCR per silnik |
| `kb_ocr_pages` | sha256, text, confidence – pierwotna pamięć OCR Tesseracta (tylko odczyt; traktowana jak wyniki klucza `tesseract:pol+eng:c60`) |

Usuwanie konta usuwa też jego prywatne materiały bazy wiedzy (wiersze i punkty w Qdrant), a w materiałach
wspólnych zeruje `uploaded_by`. Usuwanie pacjenta (`purge_patients`) kasuje wydarzenia kalendarza, wywiad (nagrania, pytania, stan), plan działania (kroki, ustawienia; usunięcie kroku zeruje `plan_step_id` w wydarzeniach), notatki, zalecenia, powiadomienia i powiązanie konta,
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
  grafika `logoped-monochrome.png` przyklejona do dołu nad stopką.
- **Stopka całej aplikacji** (`shared/footer.component.ts`, także na stronie logowania): stała, 48 px (`h-12`, `#02121c`),
  logo Webaby (`webabylogo-mark.png` – przycięty `webabylogo.png`, czarny znak odwrócony filtrem `invert` do bieli),
  „© <rok> Webaby. Wszelkie prawa zastrzeżone.”, link https://webaby.io, `mailto:contact@webaby.io` (na telefonie „Kontakt”),
  ikony social media (WhatsApp, Facebook, Instagram, X); `main` ma `pb-16`, żeby stopka nie zasłaniała treści.
  Logo Webaby (64 px, w stopce 36 px) także po prawej stronie paska nawigacji, jako link do webaby.io.
- **Karta pacjenta** – edycja danych, nowa notatka (wpisywana lub **dyktowana**: `MediaRecorder` →
  `POST /api/audio/transcribe` → Whisper, język `pl`, limit 25 MB, dozwolone formaty audio), lista notatek;
  każda notatka ma okrągły przycisk z ikoną głośnika „Odsłuchaj” (w trakcie odczytu ikona stop na wypełnionym tle) – odczyt syntezatorem przeglądarki (Web Speech API,
  `core/speech.service.ts`), polski głos lokalny systemu preferowany (np. Paulina w Windows; głosy sieciowe wysyłają
  tekst na zewnątrz), tekst dzielony na zdania ≤ 200 znaków (Chrome przerywa długie wypowiedzi); bez backendu. Odporność na błędy
  Chrome: fragmenty odtwarzane po kolei (następny w `onend` poprzedniego), bieżąca wypowiedź trzymana w polu (GC),
  `cancel()` tylko gdy coś gra i nowy `speak()` po 150 ms, `resume()` przed startem, oczekiwanie na `voiceschanged`.
- **Historia pacjenta** – zakładki „Sesje i notatki” oraz „Pytania do asystenta” (`GET /api/patients/{id}/chat-history`:
  wiadomości z `patient_id` pacjenta, łączone w pary pytanie–odpowiedź, link „Otwórz rozmowę”).
- **Wywiad pacjenta** (komponent `patient-interview`, w `patient-care` przed „Zalecenia i wskazania do leczenia”):
  tabela Pytanie | Odpowiedź. Przy pierwszym otwarciu (`GET /api/patients/{id}/interview`) wywiad jest zakładany
  z bieżącego szablonu (zmiana szablonu nie rusza istniejących wywiadów); lekarz dodaje własne pytania i usuwa zbędne.
  Przy pytaniu: ikona mikrofonu – nagranie odpowiedzi pacjenta w gabinecie (`AudioRecordingService` → `PUT …/items/{iid}/audio`) –
  serwer zapisuje nagranie (zastępuje poprzednie) i zwraca transkrypcję Whisper (`pl`), którą frontend **dokleja** do pola
  odpowiedzi (`mergeTranscript`; serwer odpowiedzi nie nadpisuje; przy błędzie transkrypcji nagranie i tak zostaje),
  ikona głośnika – odsłuch nagrania (w trakcie: pauza) (blob przez HttpClient z JWT → `Audio`), usuwanie nagrania. „Zapisz szkic” (`PUT …/interview`)
  i „Zatwierdź” (`POST …/interview/approve`) – zatwierdzenie zapisuje migawkę `approved_items`. Status `approved` tylko,
  gdy treść = migawka (poprawka po zatwierdzeniu → `draft`, cofnięcie → znów `approved`); znacznik „Niezapisane zmiany”.
  Szablon domyślny: `backend/src/interview_template.txt` (formularz „Wywiad logopedyczny i ocena anatomiczno-funkcjonalna –
  pierwsza konsultacja dziecka”, 11 sekcji + pytania dodatkowe, badanie 9A–9G, podsumowanie, zalecenia; ~90 pytań),
  jedno pytanie w wierszu, `## ` = nagłówek sekcji, `# ` = komentarz; pola wyboru z formularza jako opcje w nawiasie
  („(siłami natury / cesarskie cięcie planowane / …)”); imię, nazwisko i data urodzenia pominięte (są w karcie pacjenta).
  Nagłówki w tabeli – wiersz sekcji bez pola odpowiedzi i nagrywania, numeracja pytań pomija sekcje. „Wczytaj aktualny
  szablon” (`POST …/interview/reset`) zastępuje pytania (usuwa odpowiedzi i nagrania; zatwierdzona migawka zostaje do
  ponownego zatwierdzenia).
  **Do LLM trafia wyłącznie zatwierdzona migawka**: `describe_patient(patient, interview)` dopisuje sekcję
  „Wywiad z pacjentem / opiekunem (zatwierdzony przez lekarza):” z parami `- pytanie / Odpowiedź: …` (tylko pytania
  z odpowiedzią), pogrupowanymi nagłówkami `[sekcja]` (tylko sekcje z co najmniej jedną odpowiedzią), dzięki czemu wywiad trafia też do kroku przepisywania zapytania; `ANSWER_SYSTEM` każe odnosić
  zalecenia do wywiadu i cytować fakty o pacjencie jako „(wywiad)”/„(opis pacjenta)”, nie numerem źródła.
  Anonimizacja jak dla reszty kontekstu (centralnie w `src/llm.py`).
- **Plan działania** (komponent `patient-plan`, między wywiadem a zaleceniami): poziomy diagram (`<ol>` z przewijaniem
  w poziomie) kart-kroków 192 px: „Krok N”, nazwa (max 3 linie), status z ikoną i etykietą (kolor nigdy sam):
  zaplanowany (`circle`, szary – domyślny dla nowego kroku), zakończony (`check-circle`, zielony), zawieszony
  (`pause-circle`, bursztynowy), niewykonalny (`x-circle`, czerwony); karty mają wspólne lekko beżowe tło `#f3e8d4` z ramką `#dccbad` (nie zlewają się z białą sekcją), a lewa
krawędź 4 px ma kolor statusu (sky-400/emerald/amber/red-500); karta „+” na tle slate-50; między kartami
  szewron, na końcu pusta karta z przerywaną ramką i „+” = nowy krok. Kliknięcie karty otwiera natywny `<dialog>`
  (`showModal`, Esc zamyka, tło przyciemnione): nazwa, status (4 przyciski), opis; „Usuń krok” (z potwierdzeniem),
  strzałki zmiany kolejności (`PUT …/plan/order` – pełna lista id), „Zapisz”/„Dodaj krok”. Przełącznik
  „Uwzględniaj plan w odpowiedziach asystenta” (`PUT …/plan/settings`) – gdy włączony, `describe_patient` dopisuje
  „Plan działania (kolejne kroki terapii):” z listą `N. nazwa – status: …` i opisem (`plan_for_context`).
- **Propozycja następnego kroku planu** (`src/plan_advisor.py`, `api/plan_suggest.py`, `POST /patients/{id}/plan/suggest`):
  po kliknięciu „Nowy krok” okno od razu prosi asystenta o propozycję (fioletowy panel „Propozycja asystenta”, spinner,
  „Inna propozycja”). Kontekst: `describe_patient` (dane + zatwierdzony wywiad), wszystkie kroki planu ze statusami
  (zawsze, niezależnie od przełącznika kontekstu czatu), 5 ostatnich notatek lekarza (≤ 800 zn.), fragmenty bazy wiedzy
  (zapytanie: rozpoznanie, ICD, ostatnie kroki, początek opisu → `llm.embed` + `hybrid_search` z filtrem widoczności +
  `reranker`). Prompt każe najpierw ocenić braki diagnostyczne (słuch, laryngolog, ortodonta, neurolog, wędzidełko, SI),
  inaczej zaproponować kolejny etap terapii wynikający z kroków zakończonych, bez powtarzania zaplanowanych i bez
  ponawiania zawieszonych/niewykonalnych; odpowiedź wyłącznie JSON `{kind: diagnostics|therapy, title, description,
  rationale, sources:[n]}` (`parse_suggestion` toleruje blok ```json, filtruje numery źródeł; nieczytelna → 502).
  Operacja `plan_suggestion` (liczona w kredytach; po wyczerpaniu – model zastępczy). „Użyj propozycji” wypełnia nazwę
  i opis (opis + „Uzasadnienie: …” + „Źródła: [n] tytuł”), status „zaplanowany”; nic nie zapisuje się bez „Dodaj krok”.
  W edycji istniejącego kroku panelu nie ma.
  Anonimizacja: oba wywołania (`llm.embed` zapytania i `llm.chat_complete`) idą przez centralny anonimizator – test
  `test_suggestion_prompt_and_search_are_anonymized` sprawdza, że imię (z odmianą), nazwisko, PESEL i telefon z opisu,
  kroków planu i notatek nie wychodzą do API ani do logu LLM, a treść kliniczna zostaje.
- **Kalendarz lekarza – zakładka „Kalendarz”** (`/kalendarz`, `features/calendar/doctor-calendar.component.ts`,
  `GET /api/calendar/events?start&end` – wydarzenia wszystkich pacjentów lekarza z `patient_id`/`patient_name`, filtr
  `patients.user_id`). Widok **tygodnia**: siatka 7:00–20:00 (1,2 px/min), szare tło poza godzinami pracy i w weekend,
  czerwona linia „teraz”, wydarzenia całodniowe nad siatką, bloki wg czasu (brak końca → 45 min) z torami dla nakładań
  (`layoutLanes`), kliknięcie wolnego miejsca → nowe wydarzenie o tej godzinie (15 min). Widok **miesiąca** (klik dnia →
  jego tydzień). **Odróżnianie pacjentów:** ikona = typ wydarzenia (jak w kalendarzu pacjenta), pacjent = kółko z
  inicjałami w kolorze z palety kategorialnej wykresów (`PATIENT_COLORS`, 6 barw, kolor = id pacjenta mod 6 – stały przy
  filtrowaniu; inicjały zapewniają rozróżnienie przy powtórzeniach koloru i dla daltonistów; kolor tekstu wg luminancji
  `textOn`) + lewa krawędź bloku w kolorze pacjenta. Legenda pacjentów z liczbą wydarzeń i filtrem pokaż/ukryj, legenda typów.
  **Najbliższe wolne terminy** (`freeSlots`): 14 dni od dziś, pon–pt, godziny pracy Od/Do i długość wizyty (30/45/60/90 min)
  ustawiane w panelu, sloty co 15 min, zajętość tylko z `visit` i `other` (konsultacje u specjalistów i etapy nie zajmują
  czasu lekarza); klik → nowe wydarzenie w tym terminie. Okno wydarzenia: wybór pacjenta (wymagany przy nowym), rodzaj,
  tytuł, data, od–do, cały dzień, miejsce, opis; w edycji link do karty pacjenta; ostrzeżenie o kolizji z innym zajmującym
  czas wydarzeniem (nie blokuje zapisu). Zapis przez istniejące `/patients/{id}/events` (te same uprawnienia).
- **Kalendarz pacjenta** (wspólny komponent `shared/patient-calendar.component.ts`; w karcie pacjenta po planie działania,
  w panelu pacjenta jako „Mój kalendarz”). Jedna tabela `patient_events` = jeden kalendarz widziany przez lekarza i pacjenta
  (synchronizacja z definicji). Widok miesiąca (pon–niedz, `calendar-utils.ts`, czas lokalny, nazwy przez `Intl` pl-PL):
  dni spoza bieżącego miesiąca szaroniebieskie (`.cal-outside` tło `#e3e9f1`, `.cal-outside-number` `#7a8aa3` w `styles.css`),
  dzień dzisiejszy w kółku, w komórkach kafelki z ikoną typu, godziną i tytułem (na telefonie same ikony, max 3 + „+N więcej”),
  klik dnia → lista wydarzeń dnia obok, dwuklik → nowe wydarzenie; panel „Najbliższe wydarzenia” jako oś czasu (5 pozycji).
  Typy (ikona + etykieta + kolor pomocniczy): wizyta (`calendar-check`, brand), konsultacja u specjalisty (`hospital`, violet),
  początek etapu (`flag`, sky), koniec etapu (`flag-fill`, amber), inne (`pin`, slate); legenda nad siatką. Okno `<dialog>`:
  rodzaj, tytuł, data, od–do / cały dzień, miejsce, opis, a u lekarza dla etapów – powiązanie z krokiem planu działania.
  Uprawnienia: lekarz – tylko własni pacjenci (`get_owned_patient`), pełna edycja (też wpisów pacjenta, oznaczonych „dodane przez
  pacjenta”); pacjent – tylko swoja karta (przez `patient_accounts`), dodaje wyłącznie `consultation`/`other`, edytuje i usuwa
  tylko własne wpisy (403), wpisy logopedy widzi w trybie tylko do odczytu. Walidacja: koniec ≥ początek (422), krok planu
  musi należeć do pacjenta. Lista filtrowana `start` ≤ starts_at < `end` (zakres siatki), limit 1000.
- **Konto pacjenta, zalecenia, powiadomienia** (komponent `patient-care`): utworzenie/powiązanie konta pacjenta
  (`PUT /api/patients/{id}/account` – istniejące konto musi mieć `ROLE_PATIENT` i nie być powiązane z inną kartą;
  nowe wymaga hasła), odłączenie; CRUD zaleceń z opcją „powiadom e-mailem”; wysyłka powiadomień e-mail
  (SMTP z biblioteki standardowej w wątku; brak konfiguracji → zapis ze statusem `failed`).
- **Formatowanie odpowiedzi** – odpowiedzi asystenta (czat i zakładka „Pytania do asystenta”) renderowane z Markdownu:
  `shared/markdown.pipe.ts` (`marked` 12.0.2, GFM, `breaks: true`; surowy HTML z odpowiedzi escapowany, linki w nowej karcie,
  wynik przez sanitizer Angulara w `[innerHTML]`), odnośniki `[1]`, `[1, 2]` → `<sup class="md-cite">` (poza kodem);
  typografia w klasie `.md` w `styles.css` (nagłówki, listy z kolorowymi markerami, cytaty, tabele, kod) – bez wtyczki
  typography. Pytania lekarza zostają zwykłym tekstem.
- **Asystent** – czat ze źródłami (rozwijana lista, trafność, znacznik „luźno związane”), wybór pacjenta,
  lista rozmów, licznik tokenów; tło `logoped-sepia.png`.

## 8. Panel pacjenta (`/patient`)

Rozpoznanie, ICD, wiek, logopeda prowadzący (mailto), zalecenia, **„Mój kalendarz”** (ten sam kalendarz co u lekarza) i powiadomienia. **Bez notatek lekarza.**
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
- **Szablon wywiadu** (komponent `interview-template` na dole `/admin`): textarea „jedno pytanie w wierszu”,
  „Zapisz szablon” (`PUT /api/admin/interview-template` – białe znaki scalane, puste wiersze pomijane),
  „Przywróć domyślny” (`DELETE`). Domyślnie 16 pytań wywiadu logopedycznego (powód zgłoszenia, przebieg trudności,
  ciąża i poród, rozwój ruchowy i mowy, karmienie, oddychanie, słuch, choroby/operacje, zgryz i nawyki, wywiad rodzinny,
  środowisko językowe, lateralizacja, dotychczasowa terapia, funkcjonowanie emocjonalno-społeczne, oczekiwania).
- **`/admin/testy` – Testy jakości (goldset)** (`src/goldset.py`, `api/goldset.py`, `goldset.component.ts`):
  import goldsetu z wklejonego tekstu (`parse_goldset`: najpierw pytania „N. Tytuł” + treść, potem druga numeracja od 1 =
  odpowiedzi wzorcowe; nagłówek = numer zgodny z oczekiwanym, spacja po kropce, w części odpowiedzi bez kropki na końcu;
  kroki „1.<TAB>…” są treścią i zamieniane na „1. …”; tytuł łamany na dwie linie sklejany; łamane wiersze pytań łączone
  w akapity) → podgląd → „Zapisz goldset” (zastępuje; wyniki historyczne zostają, bo mają kopie pytań); edycja/usuwanie
  pozycji. „Uruchom test” (jeden naraz, w tle, `asyncio` task; postęp przez odpytywanie co 3 s; „Zatrzymaj”; przebieg
  „running” bez zadania po restarcie → `failed`): każde pytanie (tytuł + treść) przez prawdziwy `rag_graph` jak czat lekarza
  (bez kontekstu pacjenta, bez zapisu w `chat_history`), potem LLM-sędzia (`goldset_judge`, temp. 0, JSON: score 0–5,
  covered, missing, order_ok, errors, comment – liczy się zgodność kluczowych kroków i kolejność, dodatkowe poprawne
  treści nie obniżają oceny) i podobieństwo cosinusowe embeddingów odpowiedzi i wzorca (`goldset_similarity`); błąd
  pytania nie przerywa testu. Historia przebiegów (średnia ocena, podobieństwo, czas, tokeny, model, notatka), wyniki
  od najsłabszych z rozwijanymi szczegółami (odpowiedź vs wzorzec obok siebie, braki/błędy/pokryte punkty, źródła),
  „Porównaj z” innym przebiegiem (▲/▼ różnica oceny per pytanie). Koszt w kredytach administratora.
  Goldset nigdy nie trafia do `/kb` (zawyżyłby wyniki).
- **`/admin/llm`** – log zapytań LLM: lista (filtr operacji i statusu, stronicowanie po 50) i szczegóły
  (wiadomości wysłane do modelu i odpowiedź). Retencja `LLM_LOG_RETENTION_DAYS` (czyszczenie przy starcie).
- **`/admin/knowledge`** – baza wiedzy RAG (sekcja 10).

## 9a. Kredyty (zł), subskrypcja i model zastępczy (`src/billing.py`, `api/billing.py`)

- **Przelicznik:** koszt = (tokeny wejścia × cena wejścia + tokeny wyjścia × cena wyjścia) / 1 mln × `BILLING_USD_PLN_RATE`
  × `BILLING_MARGIN` – standard rozliczeń API (cennik dostawcy w USD za 1 mln tokenów). Cennik `DEFAULT_PRICES`
  (gpt-4o-mini 0,15/0,60; gpt-4o 2,50/10; gpt-4.1*; text-embedding-3-small 0,02; whisper-1 – 1 „token” = 1 s nagrania,
  100 USD/1 mln s = 0,006 USD/min), nazwy z datą wersji dopasowywane najdłuższym prefiksem, nadpisanie `BILLING_PRICES_JSON`;
  model spoza cennika (lokalna Gemma) = 0 zł. `stt.py` zapisuje sekundy z `usage: {type: duration}` odpowiedzi Whisper.
- **Okno:** miesięczne od `started_at` (rocznica liczona zawsze od daty startu – bez dryfu; 31. → ostatni dzień krótszego
  miesiąca). Zużycie = suma `token_usage` użytkownika w oknie, więc limit „zeruje się” sam z początkiem nowego okna.
  Dostępne = limit + doładowania potwierdzone w tym oknie.
- **Po wyczerpaniu:** `llm._create_chat` → `billing.use_local_model(user_id)` (cache 30 s, `invalidate()` po zmianach)
  kieruje czat (przepisanie zapytania i odpowiedź) do `LOCAL_LLM_BASE_URL`/`LOCAL_LLM_MODEL` (Ollama, OpenAI-compatible);
  gdy model lokalny nie odpowiada – awaryjnie model podstawowy. Embeddingi (wymiar wektorów Qdrant) i transkrypcja
  zostają u dostawcy. Użytkownik widzi tylko: „Wykorzystano limit kredytów – przechodzimy na tańsze modele.”
  (`EXHAUSTED_MESSAGE`; baner w czacie i na stronie Kredyty). Bez `LOCAL_LLM_BASE_URL` – tylko ostrzeżenie.
- **Doładowanie:** `/kredyty` – kwoty `BILLING_TOPUP_AMOUNTS` (20/50/100 zł) → zamówienie `pending` z danymi przelewu
  (`TOPUP_RECIPIENT`, `TOPUP_BANK_ACCOUNT`, tytuł = reference), e-mail do `ADMIN_EMAIL` (w tle, jeśli SMTP), max 3
  oczekujące, anulowanie. Admin potwierdza wpływ („Wpłata zaksięgowana”) lub odrzuca; może też doładować ręcznie.
- **Płatność online (`src/payments.py`, Stripe Checkout przez httpx, bez SDK):** `POST /billing/checkout` tworzy
  zamówienie (`note="online"`) i sesję Checkout w PLN – **bez `payment_method_types`** (API Stripe od 2026-10-28 odrzuca
  ten parametr; metody wybiera panel *Settings → Payment methods*, `STRIPE_PAYMENT_METHODS` to tylko opis w UI); `locale=pl`, `client_reference_id`/`metadata` = reference/topup_id, wygasa po 31 min), frontend przekierowuje na `url`.
  Webhook `POST /api/payments/stripe/webhook` – podpis `Stripe-Signature` (HMAC-SHA256 z `t.payload`, tolerancja 300 s,
  `STRIPE_WEBHOOK_SECRET`): `checkout.session.completed`/`async_payment_succeeded` z `payment_status=paid` i zgodną kwotą
  → zamówienie `confirmed` (idempotentnie – sesja rozliczana raz), `expired` → `cancelled`, `async_payment_failed` →
  `rejected`. Powrót `/kredyty?payment=success&session_id=…` → `POST /billing/checkout/sync` (odczyt sesji z API, gdy
  webhook się spóźnia), `payment=cancelled` → komunikat; parametry usuwane z adresu. Zamówienia online nie liczą się
  do limitu 3 oczekujących przelewów i nie trafiają na listę „do potwierdzenia” admina. Bez `STRIPE_SECRET_KEY`
  (`online_enabled=false`) – tylko przelew tradycyjny. UI: wybór kwoty (20/50/100) + „Zapłać online” / „Przelew tradycyjny”.
- **Wskaźnik:** `shared/credit-ring.component.ts` – kółko SVG z procentem w środku (łuk ∝ zużyciu, śladowe zużycie jako
  kropka i „<1%”, `role=img` z opisem kwot) oraz `shared/credit-meter.component.ts` – pasek + „zużyte / dostępne zł”;
  kolor obu: brand < 75% ≤ amber < 100% ≤ red. W pasku nawigacji kółko 40 px + „KREDYTY / zużyte / dostępne zł”,
  na stronie Kredyty kółko 140 px + kwota + pasek;
  w pasku nawigacji lekarza/admina (link do `/kredyty`, odświeżany przy każdej nawigacji i po odpowiedzi czatu),
  na stronie Kredyty i w panelu admina (`billing-admin.component.ts`: doładowania do potwierdzenia, tabela kont lekarzy
  i adminów z wykorzystaniem, oknem, edycją limitu i daty startu subskrypcji, doładowaniem ręcznym). Pacjenci – bez wskaźnika.
- **Ollama na serwerze:** kontener `gemma4` (ollama/ollama, modele m.in. `gemma4:12b`, CPU 8 rdzeni, bez GPU – wolne
  odpowiedzi), współdzielony z botem `babetrade-hermes`, nasłuch w sieci `babetrade-hermes_default` i 127.0.0.1:11434 hosta.
  Backend widzi go po podłączeniu: `docker network connect logoped-assist_logoped_net gemma4` →
  `LOCAL_LLM_BASE_URL=http://gemma4:11434/v1`. Pomiar 2026-11-08: zimny start 204 s, generowanie ~3,9 tok/s, przetwarzanie
  promptu ~26 tok/s (odpowiedź RAG ≈ kilka minut) – dlatego model zastępczy może też być tanim modelem w chmurze
  (`LOCAL_LLM_BASE_URL` + `LOCAL_LLM_API_KEY` + `LOCAL_LLM_MODEL`, dowolny endpoint OpenAI-compatible).

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

**Silniki OCR** (`src/ocr.py`): rejestr `ENGINES` (protokół `OcrEngine`: `name`, `label`, `key()` – identyfikuje silnik
razem z parametrami, `read(bytes)`), domyślny z `OCR_ENGINE`. Dziś jeden silnik – Tesseract; kolejny (np. model
wizyjny – zgodnie z decyzją ma czytać druk i pismo odręczne) = nowa klasa w rejestrze, bez zmian w reszcie systemu. Instrukcja z przykładem
kodu silnika wizyjnego (API zgodne z OpenAI): README, „Podłączenie nowego silnika OCR”.
Pamięć podręczna OCR jest per silnik, więc wyniki różnych silników nie nadpisują się.

**Tesseract**: `pol+eng`, tylko druk – słowa z pewnością < `OCR_MIN_WORD_CONFIDENCE=60`
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

**Przetwarzanie od nowa** (oryginały w katalogu są zawsze zachowane): `POST /admin/knowledge/reprocess`
`{engine, force_ocr, rebuild_index}` – wszystkie dokumenty: OCR wybranym silnikiem (od nowa albo z pamięci tego
silnika), fragmenty, embedding; tytuły/metadane/widoczność zostają; `rebuild_index` usuwa kolekcję Qdrant,
indeksuje hasła wbudowane i odtwarza z zapisanego tekstu dokumenty bez oryginału. `POST /{id}/reprocess` – jeden
dokument (409, gdy brak oryginału). Zadania w tle, jedno naraz (`ImportJob.label` opisuje zadanie w panelu).
Pojedynczy plik wgrany w panelu zapisuje oryginał w `pojedyncze/<nazwa>-<sha8>/<plik>` (z prefiksem `prywatne/<id>/`),
z `source_path` i `content_hash` zgodnymi z importem (import traktuje go jako niezmieniony).

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
- `billing`: `GET /billing/me`, `POST /billing/topups`, `DELETE /billing/topups/{id}`, `POST /billing/checkout`,
  `POST /billing/checkout/sync`, `POST /payments/stripe/webhook` (bez JWT, podpis Stripe); admin: `GET /admin/billing/users`,
  `PATCH /admin/billing/users/{id}` (limit, start subskrypcji), `POST /admin/billing/users/{id}/topups` (ręczne),
  `GET /admin/billing/topups?status_filter=`, `POST /admin/billing/topups/{id}/confirm|reject`
- `calendar`: `GET /calendar/events` (zbiorczy kalendarz lekarza), `GET|POST /patients/{id}/events` (`?start=&end=` ISO), `PUT|DELETE /patients/{id}/events/{eid}`;
  `GET|POST /portal/events`, `PUT|DELETE /portal/events/{eid}` (pacjent)
- `plan`: `POST /patients/{id}/plan/suggest` (propozycja kroku), `GET /patients/{id}/plan`, `PUT /patients/{id}/plan/settings`, `POST /patients/{id}/plan/steps`,
  `PUT|DELETE /patients/{id}/plan/steps/{sid}`, `PUT /patients/{id}/plan/order`
- `interview`: `GET|PUT /patients/{id}/interview`, `POST /patients/{id}/interview/approve`, `POST /patients/{id}/interview/reset`,
  `POST /patients/{id}/interview/items`, `DELETE /patients/{id}/interview/items/{iid}`,
  `GET|PUT|DELETE /patients/{id}/interview/items/{iid}/audio` (PUT multipart `audio`, walidacja jak `/audio/transcribe`
  – wspólna funkcja `read_audio_upload`); `GET|PUT|DELETE /admin/interview-template` (tylko admin)
- `portal`: `GET /portal/me`
- `chat`: `POST /chat` (SSE), `GET /chat/conversations`, `GET|DELETE /chat/conversations/{id}`
- `audio`: `POST /audio/transcribe`
- `admin`: `GET /admin/usage?days=`, `GET /admin/stats`, `GET|POST /admin/users`, `PATCH|DELETE /admin/users/{id}`,
  `GET /admin/llm-calls`, `GET /admin/llm-calls/{id}`
- `admin/goldset`: `GET|PUT ""`, `POST /parse`, `PUT|DELETE /{id}`, `GET|POST /runs`, `GET|DELETE /runs/{id}`, `POST /runs/{id}/cancel`
- `admin/knowledge` (pola formularza i PATCH z `visibility`: `shared`/`private`): `GET|POST ""`, `POST /files`, `GET|POST /import`, `PATCH|DELETE /{id}`, `POST /{id}/reindex`, `POST /reprocess`, `POST /{id}/reprocess`
- `GET /api/health`

## 12. Frontend – struktura

`core/` (serwisy: auth, admin, patients, chat, portal, audio-recording, speech, interview, plan, calendar, billing; guardy: `doctorGuard` = lekarz lub admin,
`adminGuard`, `patientGuard`, `guestGuard`; interceptor JWT z wylogowaniem przy 401),
`features/` (auth, dashboard, patient-info + patient-care + patient-interview + patient-plan, chat, admin-panel + llm-logs + knowledge-base +
import-progress + interview-template, patient-portal), `shared/` (modele, navbar, utils). Trasy ładowane leniwie; `homeRoute()`:
admin → `/admin`, pacjent → `/patient`, lekarz → `/dashboard`. Logo: `assets/images/logopedic-logo-384.png` (zmniejszona, docięta do koła kopia `logopedic-logo.png`, białe tło),
Ikony: `shared/icon.component.ts` (`<app-icon name="…" [size]>`) – ścieżki SVG z Bootstrap Icons 1.11.3
(MIT) wklejone inline (volume-up, mic, stop, pause, trash, plus, check, check-circle, pause-circle, x-circle, circle,
arrow-left, arrow-right, close, chevron-right, lightbulb, refresh, calendar-check, hospital, flag, flag-fill, pin, chevron-left, geo, clock, person), `currentColor`, `aria-hidden` – opis daje przycisk;
nowe ikony kopiuj z `icons/<nazwa>.svg` paczki bootstrap-icons. Emoji nie używamy jako ikon przycisków.
Logo wyświetlane jako okrągła plakietka (`rounded-full bg-white`) – 120 px w pasku nawigacji, 192 px na stronie logowania; obok logo w nawigacji nazwa w dwóch liniach: „Logoped” (text-2xl, pogrubione)
i pod nim „Assistant” (text-sm).
Kolory marki: `brand-50…900` (teal, `#237d75`
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
- Host nginx (poza Dockerem) przyjmuje `logopeda-assist.webaby.io` i kieruje `/api/` → `127.0.0.1:8092` (bez buforowania,
  SSE), `/` → `127.0.0.1:8081`; HTTPS z certbota. Healthcheck frontendu: `wget http://127.0.0.1/` (nie `localhost` –
  w alpine to `::1`, a nginx nasłuchuje na IPv4).
- **Migracja na nowy serwer:** katalogi `/opt/logoped-assist`, `/opt/logoped-kb` (właściciel UID 1000) i plik
  `/opt/logoped-assist.env` (600) zakłada root; materiały – rsync serwer→serwer (agent SSH); dane – `pg_dump -Fc` →
  `pg_restore --no-owner`; Qdrant odbudowuje się sam przy starcie z pustym indeksem (hasła wbudowane + `kb_documents`);
  przy migracji rotuj `JWT_SECRET` i hasło bazy (`ALTER USER` w istniejącym klastrze); przełączenie: stop starego
  backendu → końcowy zrzut i rsync → DNS (TTL 5 min) → nginx + certbot → sekrety `SSH_*` w GitHub Actions.

## 15. Testy i jakość

- Backend: `cd backend && uv run ruff check src tests && uv run ruff format --check src tests && uv run pytest -q`
  (conftest: SQLite w katalogu tymczasowym, fikstury `client`, `make_headers`, `fake_index` – podstawione
  embeddingi i Qdrant). Testy obejmują: izolację danych między lekarzami, role, admina, portal pacjenta,
  kalendarz (wspólny widok lekarz–pacjent, uprawnienia pacjenta, izolacja między lekarzami i pacjentami, zakres dat, walidacja,
powiązanie z planem), plan działania (CRUD, kolejność, izolacja, kontekst LLM tylko po włączeniu, usuwanie z pacjentem), wywiad (szablon, migawka zatwierdzenia w kontekście LLM, nagrania i transkrypcja, izolacja, usuwanie z pacjentem), anonimizację (odmiany, płeć, wzorce, zachowanie treści klinicznej, zapis do logu), RAG (parser, filtry,
  źródła, fallback trafności), bazę wiedzy (formaty, skany, chunking, OCR – logika linii i orientacji,
  sesje, duplikaty, bezpieczeństwo ścieżek, idempotencja, ponawianie, postęp).
- Frontend: `npx ng test --watch=false --browsers=ChromeHeadlessNoSandbox && npx ng build`.

---

## Historia zmian

Nowe wpisy dopisuj na górze listy (data, co i dlaczego).

- **2026-11-10** – Zakładka „Kalendarz” lekarza: wszystkie wydarzenia pacjentów w jednym widoku (tydzień z siatką
  godzin, miesiąc), pacjenci oznaczeni kolorowymi inicjałami, wolne terminy i dodawanie wizyty kliknięciem.
- **2026-11-10** – Wskaźnik kredytów jako kółko z procentem (nawigacja i strona Kredyty), obok kwoty w zł.
- **2026-11-09** – Testy jakości asystenta (goldset): import pytań i odpowiedzi wzorcowych z tekstu, test przez
  prawdziwy RAG, ocena LLM-sędziego 0–5 + podobieństwo embeddingów, historia i porównanie przebiegów (`/admin/testy`).
- **2026-11-09** – Propozycja następnego kroku planu działania od asystenta (LLM + baza wiedzy): uzupełnienie
  diagnostyki albo etap terapii, z uzasadnieniem i źródłami; „Użyj propozycji” wypełnia formularz nowego kroku.
- **2026-11-09** – Nowy szablon wywiadu z prawdziwego formularza pierwszej konsultacji (sekcje `## `, plik
  `src/interview_template.txt`), nagłówki sekcji w tabeli i w kontekście LLM, przycisk „Wczytaj aktualny szablon”.
- **2026-11-08** – Stripe: sesje Checkout bez `payment_method_types` (nowe API go odrzuca – metody z panelu Stripe);
  sprawdzone na sandboxie: sesja PLN z BLIK/kartą/P24, webhook z poprawnym podpisem → 200.
- **2026-11-08** – Płatności online za kredyty: Stripe Checkout (BLIK, karta, Przelewy24), automatyczne doliczenie po
  webhooku i synchronizacja po powrocie; przelew tradycyjny zostaje jako opcja.
- **2026-11-08** – Kalendarz: dni spoza bieżącego miesiąca na szaroniebieskim tle.
- **2026-11-08** – Kredyty w zł: przeliczanie tokenów wg cennika modeli i kursu USD/PLN, miesięczne okno subskrypcji od
  daty startu (limit 20 zł, zerowanie z nowym oknem), wskaźnik w nawigacji i w panelu admina, doładowania 20/50/100 zł
  przelewem z potwierdzeniem admina; po wyczerpaniu czat przechodzi na lokalną Gemmę (Ollama) z komunikatem o tańszych modelach.
- **2026-11-08** – Kalendarz pacjenta (wizyty, konsultacje u specjalistów, początki i końce etapów terapii) – wspólny dla
  lekarza (karta pacjenta) i pacjenta (panel „Mój kalendarz”); pacjent może dodawać własne konsultacje.
- **2026-11-08** – Odpowiedzi asystenta formatowane z Markdownu (nagłówki, listy, pogrubienia, tabele, odnośniki do źródeł)
  zamiast surowych znaków `#` i `*`.
- **2026-11-07** – Karty kroków planu na lekko beżowym tle (białe zlewały się z sekcją); status – kolor lewej krawędzi i ikona.
- **2026-11-07** – Blok „Plan działania” w karcie pacjenta: diagram kart-kroków ze statusami (zakończony / zawieszony /
  niewykonalny, nowy = zaplanowany), okno edycji z opisem, zmianą nazwy, kolejności i usuwaniem; opcjonalnie w kontekście LLM.
- **2026-11-07** – Ikony Bootstrap Icons (inline SVG, komponent `app-icon`) zamiast emoji: odsłuch, nagrywanie, stop/pauza, usuwanie, dodawanie, zatwierdzanie.
- **2026-11-07** – Sekcja „Wywiad pacjenta” przed zaleceniami: szablon pytań (edycja w panelu admina) + własne pytania,
  nagrania odpowiedzi w gabinecie z transkrypcją Whisper i odsłuchem, ręczna edycja, „Zatwierdź”; zatwierdzony wywiad
  dołączany do kontekstu pacjenta w czacie RAG.
- **2026-11-07** – Odsłuchiwanie notatek (synteza mowy w przeglądarce, polski głos lokalny); większe logo Webaby.
- **2026-11-07** – Logo Webaby w pasku nawigacji i wspólna stopka całej aplikacji (copyright, webaby.io, contact@webaby.io).
- **2026-11-07** – Ponowne przetwarzanie dokumentów z oryginałów (cała baza lub jeden dokument): rejestr silników OCR,
  pamięć OCR per silnik (`kb_ocr_results`, bez utraty starych odczytów), opcja przebudowy indeksu od zera; pojedyncze
  pliki z panelu zapisują oryginał w katalogu. Aplikacja zmigrowana na serwer 187.126.17.17.
- **2026-11-06** – Przygotowanie migracji na nowy serwer (187.126.17.17); poprawka healthchecku frontendu (127.0.0.1).
- **2026-11-06** – Logo aplikacji (okrągła plakietka) zamiast litery „L” w nawigacji i na stronie logowania.
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
