import { TestBed } from '@angular/core/testing';
import { KbImportProgress, KbImportStatus } from '../../shared/models';
import { ImportProgressComponent, humanDuration } from './import-progress.component';

function status(progress: Partial<KbImportProgress>, extra: Partial<KbImportStatus> = {}): KbImportStatus {
  return {
    source_dir: '/kb',
    source_available: true,
    running: true,
    started_at: '2026-10-18T08:00:00Z',
    finished_at: null,
    summary: '',
    failed: [],
    error: null,
    trigger: 'panel',
    auto_scan_seconds: 300,
    progress: {
      phase: 'ocr',
      fraction: 0.42,
      elapsed_seconds: 300,
      eta_seconds: 420,
      units_total: 2,
      units_done: 0,
      unchanged: 16,
      created: 0,
      updated: 0,
      failed: 0,
      unit_title: 'Logopeda 17 10 2026',
      unit_path: 'Logopeda-17-10-2026/',
      unit_kind: 'images',
      step_done: 12,
      step_total: 20,
      recent: [],
      ...progress,
    },
    ...extra,
  };
}

function render(value: KbImportStatus | null, upload = { active: false, done: 0, total: 0, errors: 0 }): HTMLElement {
  const fixture = TestBed.createComponent(ImportProgressComponent);
  fixture.componentRef.setInput('status', value);
  fixture.componentRef.setInput('upload', upload);
  fixture.detectChanges();
  return fixture.nativeElement as HTMLElement;
}

describe('ImportProgressComponent', () => {
  beforeEach(() => TestBed.configureTestingModule({ imports: [ImportProgressComponent] }));

  it('pokazuje etap OCR, bieżący dokument, procent i szacowany czas', () => {
    const text = render(status({})).textContent ?? '';
    expect(text).toContain('42%');
    expect(text).toContain('OCR: strona 12 z 20');
    expect(text).toContain('Logopeda 17 10 2026');
    expect(text).toContain('dokument 1 z 2');
    expect(text).toContain('Pozostało ok. 7 min');
    expect(text).toContain('bez zmian: 16');
  });

  it('podczas wysyłania pokazuje postęp przesyłania plików', () => {
    const text = render(status({}, { running: false }), { active: true, done: 30, total: 87, errors: 0 }).textContent ?? '';
    expect(text).toContain('34%');
    expect(text).toContain('Wysyłanie plików na serwer: 30 z 87');
  });

  it('po zakończeniu pokazuje podsumowanie i listę dokumentów', () => {
    const done = status(
      {
        phase: 'done',
        fraction: 1,
        units_done: 2,
        created: 2,
        recent: [
          { path: 'Logopeda-18-10-2026/', title: 'Język to nie jest osobny narząd', status: 'created', pages: 62, chunks: 41, error: null },
        ],
      },
      { running: false, finished_at: '2026-10-18T08:20:00Z' },
    );
    const text = (render(done).textContent ?? '').replace(/\s+/g, ' ');
    expect(text).toContain('100%');
    expect(text).toContain('Zaindeksowano 2 z 2 dokumentów');
    expect(text).toContain('62 stron OCR · 41 fragmentów w indeksie');
  });

  it('jest ukryty, gdy nie było importu', () => {
    expect(render(null).textContent?.trim()).toBe('');
  });

  it('formatuje czas', () => {
    expect(humanDuration(30)).toBe('< 1 min');
    expect(humanDuration(420)).toBe('7 min');
    expect(humanDuration(3900)).toBe('1 h 5 min');
  });
});
