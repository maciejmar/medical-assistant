"""Anonimizacja tekstu przed wysłaniem do zewnętrznego LLM.

Zakres jest celowo wąski – usuwane są WYŁĄCZNIE dane wskazujące wprost na osobę:
- imię i nazwisko pacjentów zalogowanego lekarza (z kart pacjentów), także w odmianie
  (Kowalski → Kowalskiego, Anna → Annie); imię zastępuje znacznik z płcią
  ([IMIĘ PACJENTA] / [IMIĘ PACJENTKI]), żeby model zachował rodzaj gramatyczny,
- PESEL,
- numer telefonu,
- adres (ul./al./os./pl. z numerem) i kod pocztowy.

Wszystko inne – wiek, płeć, rozpoznanie, ICD, cechy szczególne, daty, liczby – trafia do modelu
bez zmian, żeby nie osłabiać jakości odpowiedzi.
Ograniczenie: imiona osób spoza kart pacjentów (np. rodziców) wpisane wolnym tekstem nie są
wykrywane – wymagałoby to modelu NER.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlmodel import col, select

from .database import Patient, session_factory

FIRST_NAME_MALE = "[IMIĘ PACJENTA]"
FIRST_NAME_FEMALE = "[IMIĘ PACJENTKI]"
LAST_NAME = "[NAZWISKO]"

# Polskie imiona męskie zakończone na -a (reszta imion na -a to imiona żeńskie).
_MALE_NAMES_ENDING_A = {"kuba", "barnaba", "bonawentura", "kosma", "jarema", "boryna"}

_IDENTIFIERS: tuple[tuple[re.Pattern[str], str], ...] = (
    # PESEL przed telefonem (11 cyfr zawiera w sobie 9).
    (re.compile(r"\b\d{11}\b"), "[PESEL]"),
    (re.compile(r"(?<![\w.])(?:\+48[ -]?)?\d{3}[ -]?\d{3}[ -]?\d{3}\b"), "[TELEFON]"),
    # Prefiks bez względu na wielkość liter, nazwa ulicy: do 3 słów z wielkiej litery + numer.
    (
        re.compile(
            r"\b(?i:ul\.|ulica|ulicy|al\.|aleja|alei|os\.|osiedle|osiedlu|pl\.|plac|placu)\s+"
            r"[A-ZĄĆĘŁŃÓŚŹŻ0-9][\w.-]*(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][\w.-]*){0,2}"
            r"(?:\s+\d+[a-zA-Z]?(?:\s*/\s*\d+[a-zA-Z]?)?)?"
        ),
        "[ADRES]",
    ),
    (re.compile(r"\b\d{2}-\d{3}\b"), "[ADRES]"),  # kod pocztowy
)

_MARKER = re.compile(r"\[(?:IMIĘ|NAZWISKO|PESEL|TELEFON|ADRES)[^\]]*\]")

# Końcówki fleksyjne polskich imion i nazwisk (Kowalskiego, Nowakowi, Annie, Janem…).
# Także formy żeńskie od nazwisk (Nowakowa, Nowakowej, Nowakówna).
_ENDINGS = (
    "ównej|ówną|ówna|owej|ową|owa|owie|owi|ego|emu|iej|ich|ych|ami|ach|ów|om|em|ie|im|ym|ej"
    "|a|y|i|e|ę|ą|o|u"
)
_VOWELS = "aeiouyąęó"


def _stems(name: str) -> set[str]:
    name = name.lower()
    stems = {name}
    # Anna → Ann(ie), Kowalski → Kowalsk(iego); krótkie rdzenie pomijamy (Ala → „al” = „ale”).
    if name[-1] in _VOWELS and len(name) - 1 >= 3:
        stems.add(name[:-1])
    return stems


def _name_pattern(names: Iterable[str]) -> re.Pattern[str] | None:
    stems: set[str] = set()
    for name in names:
        for part in re.split(r"[\s-]+", name.strip()):
            if len(part) >= 3:
                stems |= _stems(part)
    if not stems:
        return None
    alternatives = "|".join(sorted((re.escape(s) for s in stems), key=len, reverse=True))
    return re.compile(rf"\b(?:{alternatives})(?:{_ENDINGS})?\b", re.IGNORECASE)


def is_female_name(first_name: str) -> bool:
    name = first_name.strip().split()[0].lower() if first_name.strip() else ""
    return name.endswith("a") and name not in _MALE_NAMES_ENDING_A


@dataclass(frozen=True)
class Anonymizer:
    female_first_names: re.Pattern[str] | None = None
    male_first_names: re.Pattern[str] | None = None
    last_names: re.Pattern[str] | None = None

    @classmethod
    def for_names(cls, people: Iterable[tuple[str, str]]) -> "Anonymizer":
        people = list(people)
        return cls(
            female_first_names=_name_pattern(f for f, _ in people if is_female_name(f)),
            male_first_names=_name_pattern(f for f, _ in people if not is_female_name(f)),
            last_names=_name_pattern(last for _, last in people),
        )

    def __call__(self, text: str) -> str:
        if not text:
            return text
        # Nazwiska przed imionami: „Jan Janowski” – rdzeń imienia nie zje początku nazwiska.
        if self.last_names is not None:
            text = self.last_names.sub(LAST_NAME, text)
        if self.female_first_names is not None:
            text = self.female_first_names.sub(FIRST_NAME_FEMALE, text)
        if self.male_first_names is not None:
            text = self.male_first_names.sub(FIRST_NAME_MALE, text)
        for pattern, label in _IDENTIFIERS:
            text = pattern.sub(label, text)
        return text

    def messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        return [{**m, "content": self(str(m.get("content", "")))} for m in messages]

    def for_search(self, text: str) -> str:
        """Wersja do embeddingu/wyszukiwania: znaczniki usunięte, żeby nie zaszumiały zapytania."""
        return " ".join(_MARKER.sub(" ", self(text)).split())


PATTERNS_ONLY = Anonymizer()


async def anonymizer_for(user_id: int | None) -> Anonymizer:
    """Anonimizator z imionami i nazwiskami wszystkich pacjentów danego lekarza."""
    if user_id is None:
        return PATTERNS_ONLY
    async with session_factory() as session:
        rows = await session.exec(
            select(col(Patient.first_name), col(Patient.last_name)).where(
                Patient.user_id == user_id
            )
        )
        return Anonymizer.for_names(rows.all())
