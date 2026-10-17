"""Anonimizacja tekstu przed wysłaniem do zewnętrznego LLM.

Usuwane są:
- imiona i nazwiska pacjentów zalogowanego lekarza (z kart pacjentów), także w odmianie
  (Kowalski → Kowalskiego, Anna → Annie),
- identyfikatory rozpoznawane wzorcem: e-mail, PESEL, numer konta, telefon, numer dowodu,
  kod pocztowy, adres (ul./al./os./pl.), pełne daty.

Ograniczenie: imiona osób spoza kart pacjentów (np. rodziców) wpisane wolnym tekstem nie są
wykrywane – wymagałoby to modelu NER. Kody ICD (np. F80.0) i wiek pozostają bez zmian.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlmodel import col, select

from .database import Patient, session_factory

FIRST_NAME = "[IMIĘ]"
LAST_NAME = "[NAZWISKO]"

# Kolejność ma znaczenie: dłuższe ciągi cyfr przed krótszymi (PESEL przed telefonem).
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), label)
    for pattern, label in (
        (r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "[EMAIL]"),
        (r"\b(?:PL)?\d{2}(?:[ ]?\d{4}){6}\b", "[NR KONTA]"),
        (r"\b\d{11}\b", "[PESEL]"),
        (r"(?<![\w.])(?:\+48[ -]?)?\d{3}[ -]?\d{3}[ -]?\d{3}\b", "[TELEFON]"),
        (r"\b[A-Z]{3}[ ]?\d{6}\b", "[NR DOKUMENTU]"),
        (r"\b\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2}\b", "[DATA]"),
        (r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b", "[DATA]"),
        (r"\b\d{2}-\d{3}\b", "[KOD POCZTOWY]"),
        # Prefiks bez względu na wielkość liter, nazwa ulicy: do 3 słów z wielkiej litery + numer.
        (
            r"\b(?i:ul\.|ulica|ulicy|al\.|aleja|alei|os\.|osiedle|osiedlu|pl\.|plac|placu)\s+"
            r"[A-ZĄĆĘŁŃÓŚŹŻ0-9][\w.-]*(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][\w.-]*){0,2}"
            r"(?:\s+\d+[a-zA-Z]?(?:\s*/\s*\d+[a-zA-Z]?)?)?",
            "[ADRES]",
        ),
    )
)

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


@dataclass(frozen=True)
class Anonymizer:
    first_names: re.Pattern[str] | None = None
    last_names: re.Pattern[str] | None = None

    @classmethod
    def for_names(cls, people: Iterable[tuple[str, str]]) -> "Anonymizer":
        people = list(people)
        return cls(
            first_names=_name_pattern(first for first, _ in people),
            last_names=_name_pattern(last for _, last in people),
        )

    def __call__(self, text: str) -> str:
        if not text:
            return text
        # Nazwiska przed imionami: „Jan Janowski” – rdzeń imienia nie zje początku nazwiska.
        if self.last_names is not None:
            text = self.last_names.sub(LAST_NAME, text)
        if self.first_names is not None:
            text = self.first_names.sub(FIRST_NAME, text)
        for pattern, label in _PATTERNS:
            text = pattern.sub(label, text)
        return text

    def messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        return [{**m, "content": self(str(m.get("content", "")))} for m in messages]


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
