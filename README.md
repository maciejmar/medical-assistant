# Logoped Assist

Asystent RAG dla lekarzy logopedów: czat ze źródłami (LangGraph + Qdrant + reranker), dyktowanie notatek (Whisper),
karty pacjentów izolowane per lekarz, panel pacjenta z zaleceniami i powiadomieniami e-mail oraz panel
administratora (statystyki zużycia, zarządzanie kontami, log zapytań LLM).

Pełny opis projektu w formie promptu do odtworzenia go od zera (z historią zmian): [REBUILD_PROMPT.md](REBUILD_PROMPT.md).

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

## Baza wiedzy RAG – dodawanie materiałów ----

Źródła wiedzy asystenta (wszystkie trafiają do Qdrant i są cytowane w odpowiedziach):

- **hasła wbudowane** – `backend/src/seed_data.py` (zmiana wymaga wdrożenia),
- **katalog z materiałami** – na serwerze `/opt/logoped-kb` (lokalnie domyślnie `../laryngolog`), montowany
  w kontenerze backendu jako `/kb` (tylko do odczytu); ścieżkę hosta zmienia `KB_SOURCE_HOST_DIR`,
- **pojedyncze pliki** wgrane w panelu *Baza wiedzy* (`/admin/knowledge`).

### Wiedza wspólna i prywatna

Przy dodawaniu pliku lub folderu (i później w „Edytuj”) wybierasz widoczność: **wspólna** – dla wszystkich
użytkowników aplikacji, **prywatna** – tylko dla konta, które ją dodało (inni administratorzy jej nie widzą, a asystent
korzysta z niej wyłącznie w rozmowach tego konta). Pliki prywatne leżą na serwerze w `/opt/logoped-kb/prywatne/<id konta>/`
– tak samo można je dorzucać przez rsync.

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

**Przetwarzanie od nowa:** panel → *Baza wiedzy* → „Przetwórz dokumenty od nowa” (wybór silnika OCR, OCR od nowa
lub z pamięci, opcjonalnie przebudowa całego indeksu – np. po zmianie modelu embeddingów) albo „Przetwórz ponownie”
przy jednym dokumencie. Źródłem są oryginały w katalogu materiałów; tytuły i metadane zostają.

**OCR zdjęć:** Tesseract (lokalnie w kontenerze, obrazy nie opuszczają serwera), wyłącznie druk – słowa z niską
pewnością rozpoznania (pismo odręczne) są odrzucane. Obrócone zdjęcia są wykrywane automatycznie. Wynik OCR każdego
zdjęcia jest zapamiętywany (`kb_ocr_pages`), więc ponowna synchronizacja nie powtarza OCR. Pierwszy import kilkuset
zdjęć trwa długo (kilka sekund na stronę).

**Usuwanie:** dokument usunięty w panelu wróci przy kolejnej synchronizacji, jeśli jego plik nadal jest w katalogu –
usuń też plik. Skany PDF bez warstwy tekstowej są odrzucane (zamiast nich użyj zdjęć stron albo transkrypcji `.md`).

Tekst materiałów jest przechowywany w PostgreSQL (`kb_documents`), więc indeks można odtworzyć:
`python -m src.seed --force` (lub automatycznie przy starcie na pustym Qdrant) indeksuje ponownie hasła wbudowane
i wszystkie materiały. Nie umieszczaj w bazie wiedzy materiałów zawierających dane pacjentów.

### Podłączenie nowego silnika OCR (np. modelu wizyjnego)

Silniki OCR są zarejestrowane w `backend/src/ocr.py` (słownik `ENGINES`). Panel, pamięć podręczna OCR i ponowne
przetwarzanie obsługują każdy zarejestrowany silnik automatycznie – nowy silnik to jedna klasa. Przykład dla modelu
wizyjnego z API zgodnym z OpenAI (OpenAI, własny vLLM z Qwen2.5-VL itp.), który czyta **druk i pismo odręczne**:

1. **Ustawienia** – w klasie `Settings` (`backend/src/config.py`):

   ```python
   ocr_vision_base_url: str = "https://api.openai.com/v1"
   ocr_vision_api_key: str = ""
   ocr_vision_model: str = "gpt-4.1-mini"
   ```

2. **Silnik** – w `backend/src/ocr.py` (importy `io`, `Image`, `ImageOps`, `settings` już tam są):

   ```python
   import base64

   from openai import OpenAI

   VISION_PROMPT = (
       "Wykonaj wierną transkrypcję strony (polskie materiały logopedyczne). Odczytaj druk i pismo "
       "odręczne, zachowaj nagłówki, listy i kolejność. Nie streszczaj i nie poprawiaj autora. "
       "Nieczytelne fragmenty oznacz [nieczytelne], niepewne – [prawdopodobnie: …]. "
       "Zwróć wyłącznie tekst strony (Markdown)."
   )


   class VisionEngine:
       name = "vision"
       label = "Model wizyjny – druk i pismo odręczne"
       PROMPT_VERSION = "v1"  # zmiana promptu → nowy klucz → nowe odczyty (stare zostają)

       def key(self) -> str:
           # Klucz obejmuje model i wersję promptu – każda zmiana daje osobne wpisy w pamięci OCR.
           return f"vision:{settings.ocr_vision_model}:{self.PROMPT_VERSION}"

       def read(self, data: bytes) -> OcrResult:
           # Wywoływane w osobnym wątku (asyncio.to_thread) – dlatego synchroniczny klient.
           image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
           image.thumbnail((2000, 2000))  # mniejszy obraz = niższy koszt, tekst nadal czytelny
           buffer = io.BytesIO()
           image.save(buffer, "JPEG", quality=85)
           url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
           client = OpenAI(
               base_url=settings.ocr_vision_base_url,
               api_key=settings.ocr_vision_api_key,
               timeout=120,
           )
           response = client.chat.completions.create(
               model=settings.ocr_vision_model,
               temperature=0,
               messages=[
                   {
                       "role": "user",
                       "content": [
                           {"type": "text", "text": VISION_PROMPT},
                           {"type": "image_url", "image_url": {"url": url, "detail": "high"}},
                       ],
                   }
               ],
           )
           text = (response.choices[0].message.content or "").strip()
           return OcrResult(text=text, confidence=100.0, words=len(text.split()))
   ```

   i rejestracja:

   ```python
   ENGINES: dict[str, OcrEngine] = {
       engine.name: engine for engine in (TesseractEngine(), VisionEngine())
   }
   ```

3. **Test** – w `backend/tests/` podstaw klienta (`monkeypatch` na `OpenAI`) i sprawdź, że `get_engine("vision")`
   zwraca tekst; reszta mechanizmu jest już pokryta testami (`test_kb_reprocess.py`).
4. **Konfiguracja serwera** – w `/opt/logoped-assist.env`: `OCR_VISION_API_KEY=…` (oraz `OCR_VISION_MODEL`,
   `OCR_VISION_BASE_URL` dla innego dostawcy). Opcjonalnie `OCR_ENGINE=vision`, żeby nowe materiały
   (import i pojedyncze zdjęcia) były od razu czytane tym silnikiem. Wdrożenie: commit + push (GitHub Actions);
   sama zmiana pliku `.env` wymaga `docker compose --env-file /opt/logoped-assist.env up -d backend`.
5. **Przełączenie bazy** – panel → *Baza wiedzy* → „Przetwórz dokumenty od nowa”: wybierz silnik, najpierw
   „Przetwórz ponownie” przy jednym dokumencie i porównaj „Podgląd odczytanego tekstu”; jeśli jest lepiej –
   „Przetwórz wszystkie dokumenty od nowa” z zaznaczonym „OCR zdjęć od nowa”. Odczyty Tesseracta zostają
   w pamięci podręcznej, więc powrót do niego (bez „OCR od nowa”) trwa kilka minut.

Uwagi: zdjęcia materiałów trafiają do dostawcy modelu (nie wgrywaj materiałów z danymi pacjentów). Wywołania
silnika nie przechodzą przez `src/llm.py`, więc nie trafiają do statystyk tokenów ani logu LLM – w razie potrzeby
dopisz tam zapis (`track_usage`). Koszt orientacyjny pełnego OCR ok. 1000 stron sprawdź w cenniku dostawcy przed
uruchomieniem.

## Kredyty i model zastępczy

Każdy lekarz i administrator ma miesięczny limit kredytów w zł (domyślnie 20 zł, okno liczone od daty startu
subskrypcji; zmiana w panelu administratora). Koszt = tokeny × cena modelu (USD / 1 mln) × `BILLING_USD_PLN_RATE`.
Wskaźnik wykorzystania jest w pasku nawigacji, szczegóły i doładowanie (20/50/100 zł przelewem) na stronie `/kredyty`;
administrator potwierdza wpłaty w panelu. Po wyczerpaniu kredytów czat korzysta z modelu lokalnego
(`LOCAL_LLM_BASE_URL`, np. Ollama z Gemmą) – użytkownik widzi komunikat o przejściu na tańsze modele.

Płatności online (BLIK, karta, Przelewy24) obsługuje Stripe Checkout – kredyty dochodzą automatycznie po webhooku:

1. Konto na https://dashboard.stripe.com; w *Settings → Payment methods* włącz BLIK i Przelewy24, wyłącz zbędne
   (np. Klarna) – Checkout pokazuje wszystkie włączone metody obsługujące PLN (API nie przyjmuje już listy metod).
2. *Developers → API keys* → klucz tajny `sk_…` → `STRIPE_SECRET_KEY`.
3. *Developers → Webhooks → Add endpoint*: `https://logopeda-assist.webaby.io/api/payments/stripe/webhook`,
   zdarzenia `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
   `checkout.session.async_payment_failed`, `checkout.session.expired` → sekret `whsec_…` → `STRIPE_WEBHOOK_SECRET`.
4. Restart backendu. Najpierw klucze testowe (`sk_test_…`), potem produkcyjne.

Podłączenie Ollamy działającej na serwerze w osobnym kontenerze (`gemma4`):

```bash
docker network connect logoped-assist_logoped_net gemma4
# w /opt/logoped-assist.env:
LOCAL_LLM_BASE_URL=http://gemma4:11434/v1
LOCAL_LLM_MODEL=gemma4:12b
TOPUP_BANK_ACCOUNT=<numer konta do przelewów>
docker compose --env-file /opt/logoped-assist.env up -d backend
```

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
| `ROLE_DOCTOR` (w UI „Użytkownik”) | Własni pacjenci, notatki, wywiad, plan działania, kalendarz pacjenta, zalecenia, powiadomienia, asystent |
| `ROLE_PATIENT` | Panel pacjenta (`/patient`): rozpoznanie, zalecenia, kalendarz (dodaje własne konsultacje), powiadomienia – bez notatek lekarza |

## Prywatność i bezpieczeństwo

- Każde zapytanie o pacjentów, notatki i rozmowy filtruje po `user_id` zalogowanego lekarza; cudzy zasób zwraca 404.
- Administrator nie widzi kart pacjentów ani notatek innych lekarzy. Widzi natomiast log zapytań LLM (`llm_calls`):
  pełną treść promptów (w tym pytania lekarzy i zanonimizowany kontekst pacjenta) oraz odpowiedzi modelu. Logi starsze
  niż `LLM_LOG_RETENTION_DAYS` są usuwane przy starcie; `LLM_LOG_ENABLED=false` wyłącza zapisywanie.
- Do zewnętrznego LLM trafia kontekst pacjenta bez imienia i nazwiska (wiek, płeć, kod ICD, rozpoznanie, opis
  oraz **zatwierdzony** wywiad – pytania z odpowiedziami; szkic wywiadu nie jest wysyłany) oraz plan działania – tylko gdy lekarz włączy to dla danego pacjenta.
- Każdy tekst wysyłany do LLM (pytanie, historia rozmowy, kontekst pacjenta, zapytanie do embeddingu) przechodzi
  przez `backend/src/anonymizer.py`: imiona i nazwiska pacjentów lekarza (z odmianą) zastępowane są przez
  `[IMIĘ PACJENTA]`/`[IMIĘ PACJENTKI]` i `[NAZWISKO]`, a PESEL, telefon i adres (z kodem pocztowym) – znacznikami.
  Nic poza tym nie jest usuwane: wiek (u dzieci z miesiącami), płeć, ICD, rozpoznanie, pełny opis z cechami
  szczególnymi, daty i liczby trafiają do modelu bez zmian. Model jest poinstruowany, jak traktować znaczniki,
  a do wyszukiwania w bazie wiedzy trafia tekst bez znaczników. Log LLM w panelu administratora zawiera już
  wersję zanonimizowaną.
- Ograniczenie: imiona osób spoza kart pacjentów (np. rodziców) wpisane wolnym tekstem nie są wykrywane.
- Nagrania odpowiedzi z wywiadu są przechowywane w bazie (`patient_interview_audio`) i usuwane razem z pacjentem.
- Nagrania do dyktowania notatek i odpowiedzi z wywiadu trafiają do zewnętrznego API Whisper w oryginale (głosu nie da się
  zanonimizować) – do pełnej ochrony danych Whisper powinien działać na własnej infrastrukturze.
- Token JWT jest przechowywany w `localStorage`. Przy publicznym wystawieniu aplikacji zalecane są HTTPS, polityka CSP
  i limit prób logowania na reverse proxy.

## Testy * 

```bash
cd backend  && uv sync && uv run ruff check src tests && uv run pytest
cd frontend && npm install && npx ng test --watch=false && npx ng build
```
