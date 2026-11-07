"""Import katalogu z materiałami do bazy wiedzy RAG (idempotentny – można uruchamiać wielokrotnie).

Zasady:
- każdy plik tekstowy (.pdf z tekstem, .docx, .odt, .md, .txt) = jeden dokument,
- zdjęcia stron w podkatalogu = jeden dokument (strony w kolejności wykonania zdjęć),
- zdjęcia luzem w katalogu głównym są dzielone na dokumenty według sesji fotografowania
  (przerwa > KB_SESSION_GAP_MINUTES między kolejnymi zdjęciami),
- identyczne pliki (ta sama suma SHA-256) są przetwarzane raz,
- niezmienione materiały są pomijane; zmienione – odczytywane i indeksowane ponownie
  (tytuł i metadane ustawione w panelu zostają),
- OCR każdego zdjęcia wykonywany jest raz (pamięć podręczna kb_ocr_pages).

Uruchomienie: python -m src.kb_import [KATALOG] [--dry-run]   (domyślnie KB_SOURCE_DIR=/kb)
"""

import asyncio
import hashlib
import logging
import os
import re
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image
from sqlmodel import col, select

from .config import settings
from .database import KbDocument, OcrCacheEntry, OcrPage, User, init_db, session_factory
from .knowledge import (
    TEXT_EXTENSIONS,
    ExtractionError,
    extract_text,
    index_and_record,
    set_document_owner,
)
from .ocr import IMAGE_EXTENSIONS, LEGACY_TESSERACT_KEY, OcrEngine, get_engine
from .seed import seed_builtin
from .vector_store import vector_store

logger = logging.getLogger(__name__)

DEFAULT_CATEGORY = "technique"
DEFAULT_AUDIENCE = "all"


@dataclass
class SourceFile:
    path: Path
    relative: str
    sha256: str
    taken_at: datetime


@dataclass
class ImportUnit:
    source_path: str
    kind: str  # "file" | "images"
    files: list[SourceFile]
    title_hint: str
    owner_id: int | None = None  # materiał prywatny (katalog prywatne/<id>/), None = wspólny

    @property
    def content_hash(self) -> str:
        digest = hashlib.sha256()
        for f in self.files:
            digest.update(f.sha256.encode())
        return digest.hexdigest()


@dataclass
class ImportReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    duplicates: int = 0
    planned: list[str] = field(default_factory=list)  # ścieżki źródłowe dokumentów w katalogu

    def summary(self) -> str:
        return (
            f"nowe: {len(self.created)}, zaktualizowane: {len(self.updated)}, "
            f"bez zmian: {len(self.unchanged)}, błędy: {len(self.failed)}, "
            f"pominięte duplikaty plików: {self.duplicates}"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _taken_at(path: Path) -> datetime:
    """Moment wykonania zdjęcia z EXIF (DateTimeOriginal), w razie braku – data modyfikacji."""
    try:
        exif = Image.open(path).getexif()
        stamp = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        if stamp:
            return datetime.strptime(str(stamp), "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def split_sessions(files: list[SourceFile], gap: timedelta) -> list[list[SourceFile]]:
    ordered = sorted(files, key=lambda f: (f.taken_at, f.relative))
    sessions: list[list[SourceFile]] = []
    for f in ordered:
        if sessions and f.taken_at - sessions[-1][-1].taken_at <= gap:
            sessions[-1].append(f)
        else:
            sessions.append([f])
    return sessions


def _pretty(name: str) -> str:
    return re.sub(r"[_+]+", " ", Path(name).stem).strip() or name


_hash_cache: dict[tuple[str, int, int], str] = {}


def _cached_sha256(path: Path) -> str:
    """SHA-256 z pamięcią podręczną (ścieżka, rozmiar, mtime) – cykliczne skanowanie katalogu nie
    czyta ponownie niezmienionych plików."""
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key not in _hash_cache:
        _hash_cache[key] = _sha256(path)
    return _hash_cache[key]


def source_files(root: Path) -> list[Path]:
    """Obsługiwane pliki w katalogu; pomija ukryte pliki i katalogi (np. pliki tymczasowe
    trwającego wgrywania albo rsync)."""
    supported = TEXT_EXTENSIONS | IMAGE_EXTENSIONS
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in supported
        and not any(part.startswith(".") for part in p.relative_to(root).parts)
    )


def directory_fingerprint(root: Path) -> str:
    """Tani odcisk stanu katalogu (ścieżki, rozmiary, czasy modyfikacji) – bez czytania plików."""
    digest = hashlib.sha256()
    for path in source_files(root):
        stat = path.stat()
        digest.update(f"{path.relative_to(root)}|{stat.st_size}|{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


_SAFE_PART = re.compile(r"[\w .,+()&'\-]+")
_MAX_DEPTH = 4
PRIVATE_DIR = "prywatne"


def owner_from_path(relative: str) -> int | None:
    """Właściciel materiału prywatnego z ścieżki „prywatne/<id konta>/…”; None = wiedza wspólna."""
    parts = relative.split("/")
    if len(parts) >= 3 and parts[0] == PRIVATE_DIR and parts[1].isdigit():
        return int(parts[1])
    return None


class UnsafePathError(ValueError):
    pass


def safe_target(root: Path, relative_path: str) -> Path:
    """Ścieżka docelowa wgrywanego pliku wewnątrz katalogu bazy wiedzy (bez wyjścia poza niego)."""
    parts = [p.strip() for p in relative_path.replace("\\", "/").split("/")]
    if not parts or len(parts) > _MAX_DEPTH:
        raise UnsafePathError("Nieprawidłowa ścieżka pliku (zbyt głęboka struktura folderów)")
    for part in parts:
        if not part or part in (".", "..") or part.startswith(".") or len(part) > 150:
            raise UnsafePathError(f"Nieprawidłowy element ścieżki: {part!r}")
        if not _SAFE_PART.fullmatch(part):
            raise UnsafePathError(f"Niedozwolone znaki w nazwie: {part!r}")
    if Path(parts[-1]).suffix.lower() not in TEXT_EXTENSIONS | IMAGE_EXTENSIONS:
        raise UnsafePathError("Nieobsługiwany typ pliku")
    target = root.joinpath(*parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise UnsafePathError("Ścieżka wychodzi poza katalog bazy wiedzy")
    return target


def safe_name(name: str, fallback: str = "plik") -> str:
    """Nazwa pliku/folderu dopuszczalna w katalogu bazy wiedzy (niedozwolone znaki → „_”)."""
    cleaned = re.sub(r"[^\w .,+()&'\-]", "_", name).strip(" .") or fallback
    return cleaned.lstrip(".")[:120] or fallback


SINGLE_UPLOADS_DIR = "pojedyncze"


def store_single_upload(
    root: Path, filename: str, data: bytes, owner_id: int | None
) -> tuple[str, str, int]:
    """Zapisuje oryginał pliku wgranego w panelu jako „Pojedynczy plik” – każdy w osobnym
    folderze pojedyncze/<nazwa>-<skrót>/, żeby import traktował go jak osobny dokument.
    Zwraca (source_path, content_hash, pages) zgodne z tym, co wyliczy import katalogu."""
    sha = hashlib.sha256(data).hexdigest()
    name = safe_name(filename)
    folder = f"{safe_name(Path(name).stem, 'dokument')}-{sha[:8]}"
    stored, _ = store_file(root, f"{SINGLE_UPLOADS_DIR}/{folder}/{name}", data, owner_id)
    content_hash = hashlib.sha256(sha.encode()).hexdigest()  # jak ImportUnit.content_hash
    if Path(name).suffix.lower() in IMAGE_EXTENSIONS:
        return stored.rsplit("/", 1)[0] + "/", content_hash, 1
    return stored, content_hash, 0


def store_file(
    root: Path, relative_path: str, data: bytes, owner_id: int | None = None
) -> tuple[str, bool]:
    """Zapisuje plik w katalogu bazy wiedzy; zwraca (ścieżka względna, czy zmieniono treść).
    Materiał prywatny trafia do prywatne/<owner_id>/…. Zapis przez plik tymczasowy (ukryty –
    pomijany przez import) i atomową zmianę nazwy."""
    safe_target(root, relative_path)  # walidacja ścieżki podanej przez użytkownika
    top = relative_path.replace("\\", "/").split("/")[0].strip()
    if owner_id is None and top == PRIVATE_DIR:
        raise UnsafePathError(f"Folder „{PRIVATE_DIR}” jest zarezerwowany dla wiedzy prywatnej")
    if owner_id is not None:
        relative_path = f"{PRIVATE_DIR}/{owner_id}/{relative_path}"
    target = root.joinpath(*[part.strip() for part in relative_path.replace("\\", "/").split("/")])
    if target.is_file() and _sha256(target) == hashlib.sha256(data).hexdigest():
        return target.relative_to(root).as_posix(), False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".upload-{uuid.uuid4().hex}.part"
    try:
        temporary.write_bytes(data)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target.relative_to(root).as_posix(), True


def plan_units(root: Path, report: ImportReport) -> list[ImportUnit]:
    """Dzieli zawartość katalogu na dokumenty, przetwarzając identyczne pliki raz:
    - plik tekstowy obecny w kilku miejscach – liczy się kopia położona najpłycej (stabilnie
      przy dorzucaniu folderów zawierających kopie już zaimportowanych dokumentów),
    - zdjęcie obecne w kilku miejscach – liczy się kopia z podkatalogu (podkatalog = dokument).
    Duplikaty wykrywane są w obrębie zakresu widoczności (wspólne / prywatne danego konta)."""
    files = source_files(root)
    seen: set[tuple[int | None, str]] = set()
    units: list[ImportUnit] = []

    texts = [p for p in files if p.suffix.lower() in TEXT_EXTENSIONS]
    for path in sorted(texts, key=lambda p: (len(p.relative_to(root).parts), str(p))):
        sha = _cached_sha256(path)
        relative = path.relative_to(root).as_posix()
        owner = owner_from_path(relative)
        if (owner, sha) in seen:
            report.duplicates += 1
            continue
        seen.add((owner, sha))
        units.append(
            ImportUnit(
                relative,
                "file",
                [SourceFile(path, relative, sha, datetime.min)],
                _pretty(path.name),
                owner,
            )
        )

    images_by_dir: dict[Path, list[Path]] = {}
    for path in files:
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            images_by_dir.setdefault(path.parent, []).append(path)
    for directory in sorted(images_by_dir, key=lambda d: (-len(d.relative_to(root).parts), str(d))):
        images: list[SourceFile] = []
        rel_dir = directory.relative_to(root).as_posix()
        owner = owner_from_path(f"{rel_dir}/x")
        for path in images_by_dir[directory]:
            sha = _cached_sha256(path)
            if (owner, sha) in seen:
                report.duplicates += 1
                continue
            seen.add((owner, sha))
            relative = path.relative_to(root).as_posix()
            images.append(SourceFile(path, relative, sha, _taken_at(path)))
        if not images:
            continue
        if directory != root:
            ordered = sorted(images, key=lambda f: (f.taken_at, f.relative))
            units.append(
                ImportUnit(f"{rel_dir}/", "images", ordered, _pretty(directory.name), owner)
            )
        else:
            gap = timedelta(minutes=settings.kb_session_gap_minutes)
            for session in split_sessions(images, gap):
                first = session[0]
                units.append(
                    ImportUnit(
                        f"#{Path(first.relative).name}",
                        "images",
                        session,
                        f"Materiały ze zdjęć {first.taken_at:%Y-%m-%d %H:%M}",
                    )
                )
    return sorted(units, key=lambda u: u.source_path)


async def _ocr_cached(source: SourceFile, engine: OcrEngine, force: bool = False) -> OcrCacheEntry:
    """Wynik OCR zdjęcia dla danego silnika: z pamięci podręcznej (także z pierwotnej tabeli
    Tesseracta), a przy `force` albo braku wyniku – rozpoznanie od nowa i zapis."""
    key = engine.key()
    if not force:
        async with session_factory() as session:
            cached = await session.get(OcrCacheEntry, (source.sha256, key))
            if cached is not None:
                return cached
            legacy = (
                await session.get(OcrPage, source.sha256) if key == LEGACY_TESSERACT_KEY else None
            )
        if legacy is not None:
            return await _store_ocr(source.sha256, key, legacy.text, legacy.confidence)
    result = await asyncio.to_thread(engine.read, source.path.read_bytes())
    return await _store_ocr(source.sha256, key, result.text, result.confidence)


async def _store_ocr(sha256: str, engine_key: str, text: str, confidence: float) -> OcrCacheEntry:
    async with session_factory() as session:
        row = await session.merge(
            OcrCacheEntry(sha256=sha256, engine=engine_key, text=text, confidence=confidence)
        )
        await session.commit()
        await session.refresh(row)
        return row


def title_from_text(text: str, fallback: str) -> str:
    """Pierwsza sensowna linia rozpoznanego tekstu (np. tytuł z okładki) jako tytuł dokumentu."""
    for line in text.splitlines():
        line = line.strip(" #\t")
        letters = sum(ch.isalpha() for ch in line)
        if 8 <= len(line) <= 120 and letters >= len(line) * 0.6:
            return line[:1] + line[1:].lower() if line.isupper() else line
    return fallback


@dataclass
class ImportProgress:
    """Postęp importu dla panelu administratora (OCR → embedding, ważony liczbą stron)."""

    phase: str = "idle"  # scan | ocr | extract | embed | done
    started: float = field(default_factory=time.monotonic)
    units_total: int = 0  # dokumenty nowe/zmienione do przetworzenia
    units_done: int = 0
    unchanged: int = 0
    created: int = 0
    updated: int = 0
    failed: int = 0
    work_total: float = 0.0
    work_done: float = 0.0
    unit_title: str = ""
    unit_path: str = ""
    unit_kind: str = ""
    unit_weight: float = 0.0
    unit_fraction: float = 0.0
    step_done: int = 0  # strony OCR albo fragmenty embeddingu bieżącego dokumentu
    step_total: int = 0
    recent: list[dict] = field(default_factory=list)

    # Udział etapów w pracy nad dokumentem: zdjęcia – głównie OCR, pliki – głównie embedding.
    _OCR_SHARE = 0.85
    _EXTRACT_SHARE = 0.2

    @staticmethod
    def weight(unit: ImportUnit) -> float:
        return float(len(unit.files)) if unit.kind == "images" else 2.0

    def begin(self, unit: ImportUnit) -> None:
        self.unit_path, self.unit_kind = unit.source_path, unit.kind
        self.unit_title = unit.title_hint
        self.unit_weight, self.unit_fraction = self.weight(unit), 0.0
        self.phase = "ocr" if unit.kind == "images" else "extract"
        self.step_done, self.step_total = 0, len(unit.files) if unit.kind == "images" else 1

    def on_page(self, done: int, total: int) -> None:
        self.step_done, self.step_total = done, total
        self.unit_fraction = self._OCR_SHARE * done / max(total, 1)

    def on_chunks(self, done: int, total: int) -> None:
        self.phase = "embed"
        self.step_done, self.step_total = done, total
        base = self._OCR_SHARE if self.unit_kind == "images" else self._EXTRACT_SHARE
        self.unit_fraction = base + (1 - base) * done / max(total, 1)

    def finish(self, status: str, title: str, chunks: int = 0, error: str | None = None) -> None:
        self.units_done += 1
        self.work_done += self.unit_weight
        self.unit_fraction = 0.0
        setattr(self, status, getattr(self, status) + 1)
        self.recent.insert(
            0,
            {
                "path": self.unit_path,
                "title": title,
                "status": status,
                "pages": int(self.unit_weight) if self.unit_kind == "images" else 0,
                "chunks": chunks,
                "error": error,
            },
        )
        del self.recent[10:]

    @property
    def fraction(self) -> float:
        if self.phase == "done":
            return 1.0
        if not self.work_total:
            return 0.0
        current = self.unit_weight * self.unit_fraction
        return min(1.0, (self.work_done + current) / self.work_total)

    @property
    def elapsed_seconds(self) -> int:
        return int(time.monotonic() - self.started)

    @property
    def eta_seconds(self) -> int | None:
        """Szacunek na podstawie dotychczasowego tempa (po przerobieniu min. 3% pracy)."""
        if self.phase in ("done", "scan") or self.fraction < 0.03:
            return None
        return int(self.elapsed_seconds * (1 - self.fraction) / self.fraction)


async def _user_ids() -> set[int]:
    async with session_factory() as session:
        return set((await session.exec(select(User.id))).all())  # type: ignore[arg-type]


async def unit_text(
    unit: ImportUnit,
    on_page: Callable[[int, int], None] | None = None,
    engine: OcrEngine | None = None,
    force_ocr: bool = False,
) -> tuple[str, str]:
    """Zwraca (tekst, proponowany tytuł) dla pliku lub grupy zdjęć."""
    engine = engine or get_engine()
    if unit.kind == "file":
        source = unit.files[0]
        text = await asyncio.to_thread(
            extract_text, source.path.read_bytes(), source.path.suffix.lower()
        )
        return text, unit.title_hint
    pages = []
    total = len(unit.files)
    for number, source in enumerate(unit.files, start=1):
        page = await _ocr_cached(source, engine, force_ocr)
        if len(page.text) >= 20:
            pages.append(f"# Strona {number}\n\n{page.text}")
        if on_page:
            on_page(number, total)
    if not pages:
        raise ExtractionError("Na zdjęciach nie rozpoznano drukowanego tekstu.")
    text = "\n\n".join(pages)
    first_page = re.sub(r"^# Strona \d+\s*", "", pages[0])
    return text, title_from_text(first_page, unit.title_hint)


async def import_directory(
    root: Path,
    *,
    dry_run: bool = False,
    progress: ImportProgress | None = None,
    log: Callable[[str], None] | None = None,
    force: bool = False,
    force_ocr: bool = False,
    engine: OcrEngine | None = None,
    only: set[str] | None = None,
) -> ImportReport:
    """Import katalogu. `force` – przetwarza także niezmienione dokumenty (ponowne przygotowanie),
    `force_ocr` – OCR od nowa zamiast pamięci podręcznej, `engine` – silnik OCR (domyślny
    z ustawień), `only` – tylko dokumenty o podanych ścieżkach źródłowych."""
    if not root.is_dir():
        raise FileNotFoundError(f"Katalog {root} nie istnieje (ustaw KB_SOURCE_DIR / wolumen /kb)")
    progress = progress or ImportProgress()
    progress.phase = "scan"
    report = ImportReport()
    units = await asyncio.to_thread(plan_units, root, report)
    if only is not None:
        units = [u for u in units if u.source_path in only]
    report.planned = [u.source_path for u in units]
    engine = engine or get_engine()

    async with session_factory() as session:
        known = {
            d.source_path: d
            for d in (
                await session.exec(
                    select(KbDocument).where(col(KbDocument.source_path).is_not(None))
                )
            ).all()
        }
    known_users = await _user_ids()
    pending = []
    for unit in units:
        if unit.owner_id is not None and unit.owner_id not in known_users:
            report.failed.append(f"{unit.source_path}: konto #{unit.owner_id} nie istnieje")
            continue
        existing = known.get(unit.source_path)
        # Pomijamy tylko dokumenty zaindeksowane w całości – przerwany import (np. restart przy
        # wdrożeniu) albo błąd indeksowania są ponawiane; OCR stron i tak jest w pamięci podręcznej.
        if (
            not force
            and existing is not None
            and existing.content_hash == unit.content_hash
            and existing.status == "indexed"
        ):
            report.unchanged.append(unit.source_path)
        else:
            pending.append(unit)
    progress.unchanged = len(report.unchanged)
    progress.units_total = len(pending)
    progress.work_total = sum(ImportProgress.weight(u) for u in pending)

    for position, unit in enumerate(pending, start=1):
        existing = known.get(unit.source_path)
        if log:
            log(f"[{position}/{len(pending)}] {unit.source_path}")
        if dry_run:
            (report.updated if existing else report.created).append(unit.source_path)
            continue
        progress.begin(unit)
        try:
            text, title = await unit_text(unit, progress.on_page, engine, force_ocr)
        except Exception as exc:
            logger.warning("Import %s nie powiódł się: %s", unit.source_path, exc)
            report.failed.append(f"{unit.source_path}: {exc}")
            progress.finish("failed", unit.title_hint, error=str(exc))
            continue
        progress.unit_title = existing.title if existing else title

        doc = existing or KbDocument(
            title=title[:300],
            filename=Path(unit.files[0].relative).name if unit.kind == "file" else unit.source_path,
            category=DEFAULT_CATEGORY,
            audience=DEFAULT_AUDIENCE,
            source_path=unit.source_path,
            text=text,
            uploaded_by=unit.owner_id,
        )
        doc.text = text
        doc.content_hash = unit.content_hash
        doc.pages = len(unit.files) if unit.kind == "images" else 0
        async with session_factory() as session:  # ID potrzebne do kluczy fragmentów w Qdrant
            doc = await session.merge(doc)
            await session.commit()
            await session.refresh(doc)
        if existing is None:
            # Widoczność ustalana przy utworzeniu (z katalogu prywatne/<id>/); później można ją
            # zmienić w panelu – kolejne importy jej nie nadpisują.
            await set_document_owner(doc.id, unit.owner_id)  # type: ignore[arg-type]
        doc = await index_and_record(doc, progress.on_chunks)
        if doc.status != "indexed":
            report.failed.append(f"{unit.source_path}: {doc.error}")
            progress.finish("failed", doc.title, error=doc.error)
        else:
            (report.updated if existing else report.created).append(unit.source_path)
            progress.finish("updated" if existing else "created", doc.title, chunks=doc.chunks)
    progress.phase = "done"
    return report


async def reprocess(
    root: Path,
    *,
    progress: ImportProgress | None = None,
    engine_name: str | None = None,
    force_ocr: bool = True,
    rebuild_index: bool = False,
    only: set[str] | None = None,
) -> ImportReport:
    """Ponowne przygotowanie dokumentów z oryginałów: OCR wybranym silnikiem (od nowa albo
    z pamięci podręcznej tego silnika), podział na fragmenty i embedding. `rebuild_index` usuwa
    cały indeks Qdrant i buduje go od zera (np. po zmianie modelu embeddingów) – wtedy także
    hasła wbudowane i dokumenty bez oryginału w katalogu (z zapisanego tekstu)."""
    engine = get_engine(engine_name)
    progress = progress or ImportProgress()
    if rebuild_index:
        progress.phase = "scan"
        await vector_store.drop_collection()
        await seed_builtin()
    report = await import_directory(
        root, progress=progress, force=True, force_ocr=force_ocr, engine=engine, only=only
    )
    if rebuild_index:
        planned = set(report.planned)
        async with session_factory() as session:
            leftovers = [
                d
                for d in (await session.exec(select(KbDocument))).all()
                if d.source_path not in planned
            ]
        for doc in leftovers:
            doc = await index_and_record(doc)
            if doc.status != "indexed":
                report.failed.append(f"{doc.title}: {doc.error}")
    return report


@dataclass
class ImportJob:
    """Stan importu uruchomionego z panelu administratora (jeden naraz, w tle)."""

    running: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: ImportProgress = field(default_factory=ImportProgress)
    summary: str = ""
    failed: list[str] = field(default_factory=list)
    error: str | None = None
    trigger: str = ""  # "panel" | "auto"
    label: str = ""  # co robi zadanie – pokazywane w panelu
    # Odcisk katalogu z początku ostatniego importu – automat uruchamia import tylko po zmianach.
    imported_fingerprint: str | None = None
    task: asyncio.Task | None = None


job = ImportJob()


def _start_job(
    root: Path,
    work: Callable[[ImportProgress], Awaitable[ImportReport]],
    *,
    trigger: str,
    label: str,
) -> bool:
    """Uruchamia zadanie bazy wiedzy w tle (jedno naraz) z postępem dla panelu."""
    if job.running:
        return False

    async def run() -> None:
        try:
            job.imported_fingerprint = await asyncio.to_thread(directory_fingerprint, root)
            report = await work(job.progress)
            job.summary, job.failed = report.summary(), report.failed
        except Exception as exc:
            logger.exception("Zadanie bazy wiedzy nie powiodło się: %s", label)
            job.error = str(exc)
        finally:
            job.running, job.finished_at = False, datetime.now()

    job.running, job.started_at, job.finished_at = True, datetime.now(), None
    job.trigger, job.label = trigger, label
    job.progress = ImportProgress()
    job.summary, job.failed, job.error = "", [], None
    job.task = asyncio.create_task(run())
    return True


def start_background_import(root: Path, trigger: str = "panel") -> bool:
    return _start_job(
        root,
        lambda progress: import_directory(root, progress=progress),
        trigger=trigger,
        label="Synchronizacja katalogu",
    )


def start_background_reprocess(
    root: Path,
    *,
    engine_name: str | None = None,
    force_ocr: bool = True,
    rebuild_index: bool = False,
    only: set[str] | None = None,
    label: str,
) -> bool:
    get_engine(engine_name)  # nieznany silnik → ValueError przed startem zadania
    return _start_job(
        root,
        lambda progress: reprocess(
            root,
            progress=progress,
            engine_name=engine_name,
            force_ocr=force_ocr,
            rebuild_index=rebuild_index,
            only=only,
        ),
        trigger="panel",
        label=label,
    )


def should_auto_import(current: str, previous_check: str | None, imported: str | None) -> bool:
    """Import automatyczny, gdy katalog różni się od stanu z ostatniego importu i nie zmienił się
    od poprzedniego sprawdzenia (pliki nie są właśnie kopiowane)."""
    return current != imported and current == previous_check


async def watch_directory(root: Path, interval_seconds: int) -> None:
    """Pętla w tle: co interval_seconds sprawdza katalog i importuje nowe/zmienione materiały."""
    previous_check: str | None = None
    while True:
        await asyncio.sleep(interval_seconds)
        if job.running or not root.is_dir():
            continue
        try:
            current = await asyncio.to_thread(directory_fingerprint, root)
        except OSError:
            logger.exception("Nie udało się sprawdzić katalogu bazy wiedzy %s", root)
            continue
        if should_auto_import(current, previous_check, job.imported_fingerprint):
            logger.info("Wykryto zmiany w katalogu bazy wiedzy – uruchamiam import")
            start_background_import(root, trigger="auto")
        previous_check = current


async def _main(argv: list[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = [a for a in argv if not a.startswith("--")]
    root = Path(args[0] if args else settings.kb_source_dir)
    await init_db()
    report = await import_directory(root, dry_run="--dry-run" in argv, log=logger.info)
    for label, items in (("Nowe", report.created), ("Zaktualizowane", report.updated)):
        for item in items:
            logger.info("%s: %s", label, item)
    for item in report.failed:
        logger.error("Błąd: %s", item)
    logger.info("Podsumowanie: %s", report.summary())


if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1:]))
