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
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image
from sqlmodel import select

from .config import settings
from .database import KbDocument, OcrPage, init_db, session_factory
from .knowledge import TEXT_EXTENSIONS, ExtractionError, extract_text, index_and_record
from .ocr import IMAGE_EXTENSIONS, ocr_image

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


def store_file(root: Path, relative_path: str, data: bytes) -> tuple[str, bool]:
    """Zapisuje plik w katalogu bazy wiedzy; zwraca (ścieżka względna, czy zmieniono treść).
    Zapis przez plik tymczasowy (ukryty – pomijany przez import) i atomową zmianę nazwy."""
    target = safe_target(root, relative_path)
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
    - zdjęcie obecne w kilku miejscach – liczy się kopia z podkatalogu (podkatalog = dokument)."""
    files = source_files(root)
    seen: set[str] = set()
    units: list[ImportUnit] = []

    texts = [p for p in files if p.suffix.lower() in TEXT_EXTENSIONS]
    for path in sorted(texts, key=lambda p: (len(p.relative_to(root).parts), str(p))):
        sha = _cached_sha256(path)
        if sha in seen:
            report.duplicates += 1
            continue
        seen.add(sha)
        relative = path.relative_to(root).as_posix()
        units.append(
            ImportUnit(
                relative,
                "file",
                [SourceFile(path, relative, sha, datetime.min)],
                _pretty(path.name),
            )
        )

    images_by_dir: dict[Path, list[Path]] = {}
    for path in files:
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            images_by_dir.setdefault(path.parent, []).append(path)
    for directory in sorted(images_by_dir, key=lambda d: (-len(d.relative_to(root).parts), str(d))):
        images: list[SourceFile] = []
        for path in images_by_dir[directory]:
            sha = _cached_sha256(path)
            if sha in seen:
                report.duplicates += 1
                continue
            seen.add(sha)
            relative = path.relative_to(root).as_posix()
            images.append(SourceFile(path, relative, sha, _taken_at(path)))
        if not images:
            continue
        rel_dir = directory.relative_to(root).as_posix()
        if directory != root:
            ordered = sorted(images, key=lambda f: (f.taken_at, f.relative))
            units.append(ImportUnit(f"{rel_dir}/", "images", ordered, _pretty(directory.name)))
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


async def _ocr_cached(source: SourceFile) -> OcrPage:
    async with session_factory() as session:
        cached = await session.get(OcrPage, source.sha256)
        if cached is not None:
            return cached
    result = await asyncio.to_thread(ocr_image, source.path.read_bytes())
    page = OcrPage(sha256=source.sha256, text=result.text, confidence=result.confidence)
    async with session_factory() as session:
        page = await session.merge(page)
        await session.commit()
    return page


def title_from_text(text: str, fallback: str) -> str:
    """Pierwsza sensowna linia rozpoznanego tekstu (np. tytuł z okładki) jako tytuł dokumentu."""
    for line in text.splitlines():
        line = line.strip(" #\t")
        letters = sum(ch.isalpha() for ch in line)
        if 8 <= len(line) <= 120 and letters >= len(line) * 0.6:
            return line[:1] + line[1:].lower() if line.isupper() else line
    return fallback


async def unit_text(
    unit: ImportUnit, progress: Callable[[str], None] | None = None
) -> tuple[str, str]:
    """Zwraca (tekst, proponowany tytuł) dla pliku lub grupy zdjęć."""
    if unit.kind == "file":
        source = unit.files[0]
        text = await asyncio.to_thread(
            extract_text, source.path.read_bytes(), source.path.suffix.lower()
        )
        return text, unit.title_hint
    pages = []
    for number, source in enumerate(unit.files, start=1):
        if progress:
            progress(f"OCR {source.relative} ({number}/{len(unit.files)})")
        page = await _ocr_cached(source)
        if len(page.text) >= 20:
            pages.append(f"# Strona {number}\n\n{page.text}")
    if not pages:
        raise ExtractionError("Na zdjęciach nie rozpoznano drukowanego tekstu.")
    text = "\n\n".join(pages)
    first_page = re.sub(r"^# Strona \d+\s*", "", pages[0])
    return text, title_from_text(first_page, unit.title_hint)


async def import_directory(
    root: Path,
    *,
    dry_run: bool = False,
    progress: Callable[[str], None] | None = None,
) -> ImportReport:
    if not root.is_dir():
        raise FileNotFoundError(f"Katalog {root} nie istnieje (ustaw KB_SOURCE_DIR / wolumen /kb)")
    report = ImportReport()
    units = await asyncio.to_thread(plan_units, root, report)
    for position, unit in enumerate(units, start=1):
        if progress:
            progress(f"[{position}/{len(units)}] {unit.source_path}")
        async with session_factory() as session:
            existing = (
                await session.exec(
                    select(KbDocument).where(KbDocument.source_path == unit.source_path)
                )
            ).first()
        if existing is not None and existing.content_hash == unit.content_hash:
            report.unchanged.append(unit.source_path)
            continue
        if dry_run:
            (report.updated if existing else report.created).append(unit.source_path)
            continue
        try:
            text, title = await unit_text(unit, progress)
        except Exception as exc:
            logger.warning("Import %s nie powiódł się: %s", unit.source_path, exc)
            report.failed.append(f"{unit.source_path}: {exc}")
            continue

        doc = existing or KbDocument(
            title=title[:300],
            filename=Path(unit.files[0].relative).name if unit.kind == "file" else unit.source_path,
            category=DEFAULT_CATEGORY,
            audience=DEFAULT_AUDIENCE,
            source_path=unit.source_path,
            text=text,
        )
        doc.text = text
        doc.content_hash = unit.content_hash
        doc.pages = len(unit.files) if unit.kind == "images" else 0
        async with session_factory() as session:  # ID potrzebne do kluczy fragmentów w Qdrant
            doc = await session.merge(doc)
            await session.commit()
            await session.refresh(doc)
        doc = await index_and_record(doc)
        if doc.status != "indexed":
            report.failed.append(f"{unit.source_path}: {doc.error}")
        else:
            (report.updated if existing else report.created).append(unit.source_path)
    return report


@dataclass
class ImportJob:
    """Stan importu uruchomionego z panelu administratora (jeden naraz, w tle)."""

    running: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    current: str = ""
    summary: str = ""
    failed: list[str] = field(default_factory=list)
    error: str | None = None
    trigger: str = ""  # "panel" | "auto"
    # Odcisk katalogu z początku ostatniego importu – automat uruchamia import tylko po zmianach.
    imported_fingerprint: str | None = None
    task: asyncio.Task | None = None


job = ImportJob()


def start_background_import(root: Path, trigger: str = "panel") -> bool:
    if job.running:
        return False

    async def run() -> None:
        try:
            job.imported_fingerprint = await asyncio.to_thread(directory_fingerprint, root)
            report = await import_directory(
                root, progress=lambda message: setattr(job, "current", message)
            )
            job.summary, job.failed = report.summary(), report.failed
        except Exception as exc:
            logger.exception("Import katalogu bazy wiedzy nie powiódł się")
            job.error = str(exc)
        finally:
            job.running, job.finished_at, job.current = False, datetime.now(), ""

    job.running, job.started_at, job.finished_at, job.trigger = True, datetime.now(), None, trigger
    job.summary, job.failed, job.error = "", [], None
    job.task = asyncio.create_task(run())
    return True


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
    report = await import_directory(root, dry_run="--dry-run" in argv, progress=logger.info)
    for label, items in (("Nowe", report.created), ("Zaktualizowane", report.updated)):
        for item in items:
            logger.info("%s: %s", label, item)
    for item in report.failed:
        logger.error("Błąd: %s", item)
    logger.info("Podsumowanie: %s", report.summary())


if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1:]))
