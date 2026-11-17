# ruff: noqa: E501 – treść szablonów etapów: wiersz = punkt listy widoczny w podglądzie i dla modelu.
"""Szablony promptów (pastylki w czacie): wspólne i prywatne, startowe etapy terapii, opisy
ćwiczeń z katalogu dla trybu szablonu.

Szablon zawiera tylko część specyficzną (cel, baza ćwiczeń, organizacja spotkań, pola opisu).
Zasady wspólne – dobór wyłącznie z bazy, uzasadnienie danymi pacjenta, „nie zgaduj”, opis
wykonania tylko ze źródeł – są w TEMPLATE_RULES i dołączane do każdego szablonu, także do
prywatnych szablonów lekarzy.

Ćwiczenia szablonu = wiersze zaczynające się od punktora („•”, „-”, „*”, „–”). Ich pełne opisy
pochodzą z katalogu ćwiczeń (src/exercises.py) i trafiają do kontekstu modelu jako źródła.
"""

import logging
import re
from typing import Any

from sqlmodel import col, or_, select

from .database import KbDocument, PromptTemplate, session_factory
from .exercises import match_names

logger = logging.getLogger(__name__)

TEMPLATE_RULES = (
    "Lekarz wybrał szablon odpowiedzi (poniżej). Przygotuj indywidualny plan terapii dla "
    "wybranego pacjenta na podstawie jego danych: wieku, opisu, rozpoznania, zatwierdzonego "
    "wywiadu i planu działania. Uwzględnij główny problem, napięcie mięśniowe, kompensacje "
    "i zaburzone funkcje. Zasady doboru:\n"
    "1. Wybieraj WYŁĄCZNIE ćwiczenia/techniki z bazy podanej w szablonie i używaj ich nazw "
    "dokładnie w tym brzmieniu. Nie dodawaj niczego spoza bazy.\n"
    "2. Każdy wybór uzasadnij konkretną informacją o pacjencie, np. „(wywiad: oddycha przez "
    "usta)”. Nie wybieraj automatycznie ze wszystkich kategorii – tylko to, czego ten pacjent "
    "najbardziej potrzebuje.\n"
    "3. Liczby ćwiczeń w szablonie to wartości maksymalne. Nie zgaduj brakujących informacji: "
    "jeśli dane pacjenta nie uzasadniają pełnej liczby, wybierz mniej, napisz dlaczego i dodaj "
    "sekcję „Do uzupełnienia w badaniu”.\n"
    "4. Dostosuj dobór, liczbę powtórzeń i formę (u dzieci zabawowa) do wieku i możliwości "
    "pacjenta. Pomiń ćwiczenia nieodpowiednie dla wieku lub stanu pacjenta i krótko zaznacz, "
    "które pominąłeś i dlaczego.\n"
    "5. Sposób wykonania opisuj WYŁĄCZNIE na podstawie opisów ćwiczeń z bazy wiedzy (źródła "
    "zaczynające się od „Ćwiczenie:”) i cytuj je [n]. Jeśli ćwiczenie nie ma opisu w źródłach, "
    "napisz „sposób wykonania – wg materiałów szkoleniowych (brak opisu w bazie wiedzy)” zamiast "
    "go wymyślać. Parametry (czas, powtórzenia, serie, częstotliwość) podaj ze źródła albo "
    "oznacz jako propozycję do decyzji terapeuty.\n"
    "6. Nie powtarzaj ćwiczeń między spotkaniami, chyba że dane pacjenta to uzasadniają – wtedy "
    "podaj uzasadnienie.\n"
    "Format z szablonu ma pierwszeństwo przed ogólnymi zasadami formatu odpowiedzi. "
    "Format: krótkie podsumowanie pacjenta (2–3 zdania), potem „Spotkanie 1” i „Spotkanie 2” "
    "z numerowanymi ćwiczeniami w kolejności wykonania – każde z polami wymienionymi "
    "w szablonie, zwięźle w punktach – następnie „Do uzupełnienia w badaniu” i „Uwagi "
    "i przeciwwskazania” (jeśli dotyczy)."
)

NO_PATIENT_MESSAGE = "Ten szablon wymaga wybrania pacjenta – plan opiera się na jego danych."

_BULLET = re.compile(r"^\s*[•\-*–]\s+(.+?)\s*[,;.]?\s*$")


def template_exercise_names(body: str) -> list[str]:
    """Nazwy ćwiczeń szablonu: wiersze z punktorem (bez przecinka/średnika na końcu)."""
    names = []
    for line in body.splitlines():
        match = _BULLET.match(line)
        if match:
            names.append(match.group(1))
    return names


async def visible_templates(session, user_id: int) -> list[PromptTemplate]:
    """Aktywne szablony wspólne i prywatne danego użytkownika (wspólne pierwsze)."""
    rows = await session.exec(
        select(PromptTemplate)
        .where(
            col(PromptTemplate.active).is_(True),
            or_(col(PromptTemplate.owner_id).is_(None), PromptTemplate.owner_id == user_id),
        )
        .order_by(
            col(PromptTemplate.owner_id).is_not(None),
            col(PromptTemplate.position),
            col(PromptTemplate.id),
        )
    )
    return list(rows.all())


async def template_for_user(session, template_id: int, user_id: int) -> PromptTemplate | None:
    template = await session.get(PromptTemplate, template_id)
    if template is None or not template.active:
        return None
    if template.owner_id is not None and template.owner_id != user_id:
        return None
    return template


def _exercise_text(exercise: Any) -> str:
    parts = []
    if exercise.goal:
        parts.append(f"Cel: {exercise.goal}")
    if exercise.tools:
        parts.append(f"Narzędzia: {exercise.tools}")
    if exercise.description:
        parts.append(f"Opis wykonania: {exercise.description}")
    return "\n".join(parts)


async def catalog_documents(
    session, template: PromptTemplate, user_id: int
) -> tuple[list[dict[str, Any]], list[str]]:
    """Opisy ćwiczeń szablonu z katalogu jako dokumenty źródłowe (te same pola co fragmenty RAG)
    oraz nazwy ćwiczeń bez opisu w katalogu."""
    names = template_exercise_names(template.body)
    if not names:
        return [], []
    results = await match_names(session, names, user_id)
    doc_ids = {r["exercise"].document_id for r in results if r["exercise"]}
    titles: dict[int, str] = {}
    if doc_ids:
        rows = await session.exec(
            select(KbDocument.id, KbDocument.title).where(col(KbDocument.id).in_(doc_ids))
        )
        titles = {doc_id: title for doc_id, title in rows.all()}
    documents: list[dict[str, Any]] = []
    seen: set[int] = set()
    missing: list[str] = []
    for result in results:
        exercise = result["exercise"]
        if exercise is None:
            missing.append(result["name"])
            continue
        if exercise.id in seen:  # warianty jednego ćwiczenia („pierogi – warga górna/dolna”)
            continue
        seen.add(exercise.id)
        source = titles.get(exercise.document_id, "")
        page = f", s. {exercise.page}" if exercise.page else ""
        documents.append(
            {
                "id": f"exercise-{exercise.id}",
                "title": f"Ćwiczenie: {exercise.name} ({source}{page})",
                "text": _exercise_text(exercise),
                "category": "technique",
                "audience": "all",
                "icd10": "",
                "icd11": "",
                "score": 1.0,
            }
        )
    return documents, missing


# --- szablony startowe (etapy terapii miofunkcjonalnej) ---

_FIELDS_TECHNIQUE = (
    "nazwa; cel; sposób wykonania; czas lub liczba powtórzeń; częstotliwość; na co zwrócić "
    "uwagę; kryterium przejścia do kolejnej techniki"
)
_FIELDS_EXERCISE = (
    "nazwa; cel; sposób wykonania; liczba powtórzeń/czas; liczba serii; częstotliwość; na co "
    "zwrócić uwagę; najczęstsze kompensacje lub błędy; kryterium prawidłowego wykonania"
)

STAGE_1 = f"""ETAP 1 – DYSTRYBUCJA NAPIĘCIA MIĘŚNIOWEGO
Cel: przywrócenie prawidłowej dystrybucji napięcia mięśniowego struktur okolicznych – przygotowanie głowy, szyi, żuchwy i dna jamy ustnej do dalszej terapii.

Terapia manualna – bierna:
• rozluźnienie podstawy czaszki
• rozluźnienie podstawy czaszki z delikatnym rozciągnięciem odcinka szyjnego
• rozluźnienie mięśni podpotylicznych
• rozluźnienie czepca ścięgnistego
• praca z powięzią przyuszniczą
• rozluźnienie mięśni skroniowych
• rozluźnienie mięśni żwaczy T1, T2, T3, T4
• rozluźnienie mięśni mostkowo-obojczykowo-sutkowych (MOS)
• rozluźnienie mięśni czworobocznych

Rozluźnienie dna jamy ustnej – mięśnie nadgnykowe:
• stymulacja punktowa zewnętrzna
• ślizganie zewnętrzne
• stymulacja punktowa wewnętrzna
• „spotkanie na dnie” – stymulacja punktowa
• „spotkanie na dnie” – stymulacja ślizgowa
• mobilizacja kości gnykowej

Terapia ruchem – czynna:
• kołyska
• karuzela
• spacer w miejscu
• krążenia ramion
• przejście dla pieszych
• krążenia głową
• krążenia głową z koszyczkiem
• głowa do ramienia
• głowa do klatki piersiowej

Rozluźnienie mięśni żucia:
• stymulacja punktowa zewnętrzna mięśni żwaczy
• powolne ruchy okrężne z delikatnym dociskiem mięśni żwaczy

Organizacja: Spotkanie 1 – do 7 technik. Spotkanie 2 – do 7 kolejnych technik, logiczna kontynuacja i przygotowanie do etapu 2.
Kolejność: od rozluźnienia struktur ogólnych (głowa, szyja, obręcz barkowa) do pracy specyficznej (żuchwa, dno jamy ustnej).
Pola każdej techniki: {_FIELDS_TECHNIQUE}."""

STAGE_2 = f"""ETAP 2 – WYDOLNOŚĆ I SPRAWNOŚĆ JĘZYKA
Cel: zwiększenie wydolności, sprawności i koordynacji języka, warg i mięśni żucia oraz przygotowanie do pracy funkcjonalnej.

Rozgrzewka języka:
• „liczenie” zębów
• „masowanie” policzków
• „malowanie” sufitu pędzlem
• „kląskanie” (przysysanie i stopniowe odklejanie tylnej części języka)
• „koci grzbiet” + wymiatanie
• pionizacja – „winda”
• huśtawka
• huśtawka 2
• „masaż podniebienia”
• „glonojad” (zassanie języka jak najdłużej przy odwiedzionej żuchwie)
• „kaka” (przy odwiedzionej żuchwie i szerokim języku na podniebieniu)
• „niania” (żuchwa w odwiedzeniu, język szeroki, sylaba „ńia”)
• „laka – naka”
• „laka – niaka”

Rozgrzewka mięśni otoczenia szpary ust:
• „zimny paluch”
• „pierogi” – warga górna
• „pierogi” – warga dolna
• „pierogi” – obie wargi
• „koparka” – ruch wymiatająco-rozcierający w kierunku dolnym
• „koparka” – ruch wymiatająco-rozciągający w kierunku górnym

Rozgrzewka mięśni żucia:
• „podciąganie” mięśnia żwacza
• „podciąganie z kotwicą”
• „zbieranie do siebie”
• „rozcieranie z dociskiem” mięśnia żwacza
• „nagryzanie” (krótkie odcinki cewników Foleya, przy prawidłowej stabilizacji żuchwy)

Ćwiczenia wydolnościowe warg:
• „rybka”
• „stary dziadek”
• „dzióbek”
• „uśmiech”
• „okienko”
• „dzióbek – uśmiech – okienko”
• „dzióbek na boki”
• „dzióbek w kółko”

Organizacja: Spotkanie 1 – do 7 ćwiczeń. Spotkanie 2 – do 6 kolejnych ćwiczeń o wyższym poziomie trudności.
Kolejność: rozgrzewka → aktywizacja i wzmacnianie → ćwiczenia wymagające większej kontroli i wydolności.
Pola każdego ćwiczenia: {_FIELDS_EXERCISE}."""

STAGE_3 = f"""ETAP 3 – SIŁA
Cel: zwiększenie siły i wydolności mięśni języka, nadgnykowych, otoczenia szpary ust i żucia, przy prawidłowej stabilizacji i kontroli ruchu.

Siła i wydolność mięśni języka:
• ćwiczenia oporowe – dół
• ćwiczenia oporowe – góra
• ćwiczenia oporowe – boki
• ćwiczenia oporowe – mediodorsum
• ćwiczenia oporowe – „koci grzbiet”
• ćwiczenia oporowe – czubek języka
• ćwiczenia oporowe – podniebienie
• ćwiczenia oporowe – policzki
• „grot”
• „grot w szczelinie”
• „język w opałach”
• „miseczka”
• „grot – miseczka”
• „grot” na boki

Siła i wydolność mięśni nadgnykowych:
• ćwiczenie Shakera – wersja 1
• ćwiczenie Shakera – wersja 2
• ćwiczenie Shakera – wersja 3
• manewr Mendelsohna
• wysiłkowe połykanie
• chin tuck z oporem
• „patrzeć w niebo”
• „patrzeć w niebo ze zdziwieniem”
• „patrzeć w niebo” z „glonojadem”

Siła mięśni otoczenia szpary ust:
• „dzióbek” z oporem horyzontalnym
• „dzióbek” z oporem wertykalnym
• „nie oddam” – patyczek między wargami, opór po skosie
• „nie oddam” – centrum
• „guzik” – opór w centrum
• „guzik” – opór w kąciku ust
• „dzióbek w opałach” – rozciąganie warg przy utrzymywaniu dzióbka
• „dzióbek w opałach” – próba ściągania warg do środka przy oporze

Siła mięśni żucia:
• „nie oddam” z cewnikami Foleya
• „nie oddam” ze szpatułką

Organizacja: Spotkanie 1 – do 7 ćwiczeń. Spotkanie 2 – do 6 kolejnych ćwiczeń, progresja treningu siłowego.
Kolejność: od łatwiejszych do trudniejszych, od mniejszego do większego obciążenia; zaplanuj regenerację i nie przeciążaj struktur. Ćwiczenia z oporem oraz ćwiczenia Shakera i Mendelsohna dobieraj ostrożnie do wieku i możliwości pacjenta.
Pola każdego ćwiczenia: {_FIELDS_EXERCISE}."""

STAGE_4 = """ETAP 4 – FUNKCJA
Cel: przeniesienie efektów wcześniejszych etapów na prawidłową funkcję języka, warg, żucia i połykania oraz utrwalenie prawidłowych wzorców.

Funkcja – język:
• pionizacja – „młoteczek”
• „młoteczek przyklejony”
• „zamiatanie” za zębami
• „zamiatanie” podniebienia
• „odklej andruta”
• „grot” – miseczka na podniebieniu
• kląskanie
• „glonojad”
• „glonojad w windzie”
• „cukierek”
• „miseczka”
• „malowanie sufitu” wałkiem
• „rozgnieść andruta”
• „glonojad na masażu”

Funkcja – mięśnie otoczenia szpary ust:
• przytrzymanie szpatułki między wargami i dociskanie warg

Funkcja – żucie:
• jedzenie twardych pokarmów podczas posiłków, z zachowaniem obustronnego żucia

Budowanie podciśnienia między językiem a podniebieniem:
• połykanie ze słomką i językiem między zębami
• pozycja języka od głoski „ń” (bez fonacji)
• „ń” + rozciąganie
• „ń” + mlaskanie
• pozycja języka od samogłoski „a” (bez fonacji)
• „a” + „n”
• „grot – deska”
• „deska na dźwigu”
• rozluźnianie masy języka
• rozluźnianie masy języka z ruchem do góry
• „od glonojada do meduzy”
• pozycja języka od głoski /n/
• pozycja języka od głoski /ń/

Budowanie funkcji – połykanie:
• „pompka”
• połykanie z językiem między zębami
• połykanie z cienką słomką
• szczelność – „łódeczka” + kropla wody + połknięcie
• połykanie z cienką słomką bez słomki
• przyssanie mediodorsum – rozluźnienie i ponowne przyssanie
• różnicowanie pozycji przyssania języka
• nauka motoryki połykania z pipetką i „łopatką”
• nauka motoryki połykania z pipetą i kroplą wody na „łódeczce”

Utrwalanie motoryki połykania (wprowadzaj w tej kolejności): 1) pipeta – otwarta jama ustna; 2) pipeta – zwarcie łuków zębowych; 3) pipeta – zwarte łuki zębowe i wargi; 4) picie z otwartego kubka; 5) połykanie śliny, napojów i pokarmów; 6) utrwalanie podczas posiłków – 10–15 świadomych przełknięć.

Organizacja: Spotkanie 1 – do 7 ćwiczeń/technik. Spotkanie 2 – do 6 kolejnych, progresja terapii.
Kolejność: nauka kontroli ruchu → budowanie prawidłowego wzorca → ćwiczenia funkcjonalne i utrwalanie. Połykanie: najpierw pozycja i podciśnienie, potem ćwiczenia z pomocami, dopiero potem samodzielne połykanie płynów, śliny i pokarmów oraz utrwalanie podczas posiłków.
Pola każdego ćwiczenia: nazwa; cel funkcjonalny; sposób wykonania; liczba powtórzeń/czas; częstotliwość; na co zwrócić uwagę; najczęstsze kompensacje lub błędy; kryterium prawidłowego wykonania."""

SEED_TEMPLATES = [
    {
        "seed_key": "mft-stage-1",
        "name": "Etap 1 · Napięcie",
        "description": "Dystrybucja napięcia: terapia manualna, dno jamy ustnej, ruch, mięśnie żucia",
        "body": STAGE_1,
    },
    {
        "seed_key": "mft-stage-2",
        "name": "Etap 2 · Wydolność",
        "description": "Rozgrzewka języka, warg i mięśni żucia, wydolność warg",
        "body": STAGE_2,
    },
    {
        "seed_key": "mft-stage-3",
        "name": "Etap 3 · Siła",
        "description": "Ćwiczenia oporowe języka, nadgnykowych, warg i mięśni żucia",
        "body": STAGE_3,
    },
    {
        "seed_key": "mft-stage-4",
        "name": "Etap 4 · Funkcja",
        "description": "Funkcja języka, podciśnienie, połykanie i jego utrwalanie",
        "body": STAGE_4,
    },
]


async def seed_templates() -> int:
    """Wpisuje brakujące szablony startowe (wspólne); istniejących nie nadpisuje."""
    added = 0
    async with session_factory() as session:
        existing = set(
            (
                await session.exec(
                    select(PromptTemplate.seed_key).where(col(PromptTemplate.seed_key).is_not(None))
                )
            ).all()
        )
        for position, seed in enumerate(SEED_TEMPLATES):
            if seed["seed_key"] in existing:
                continue
            session.add(PromptTemplate(position=position, **seed))
            added += 1
        await session.commit()
    if added:
        logger.info("Dodano %s szablonów startowych", added)
    return added
