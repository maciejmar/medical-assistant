import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { GoldsetResult, GoldsetRun } from '../../core/goldset.service';
import { GoldsetComponent, scoreLevel } from './goldset.component';

const RUN: GoldsetRun = {
  id: 2,
  status: 'done',
  total: 2,
  done: 2,
  errors: 0,
  note: 'po dodaniu materiałów',
  settings: { chat_model: 'gpt-4o-mini' },
  avg_score: 3,
  avg_similarity: 0.62,
  avg_latency_ms: 8000,
  total_tokens: 4000,
  started_at: '2026-11-09T10:00:00Z',
  finished_at: '2026-11-09T10:01:00Z',
};

function result(id: number, itemId: number, title: string, score: number): GoldsetResult {
  return {
    id,
    item_id: itemId,
    title,
    question: 'Pytanie',
    answer: '**Odpowiedź**',
    sources: [],
    verdict: { comment: 'Komentarz', missing: score < 4 ? ['konsultacja ortodontyczna'] : [] },
    score,
    similarity: 0.6,
    latency_ms: 8000,
    tokens: 1000,
    judge_tokens: 300,
    status: 'ok',
    error: null,
  };
}

describe('GoldsetComponent', () => {
  it('poziom oceny zawsze ma etykietę', () => {
    expect(scoreLevel(4.5).label).toBe('dobra');
    expect(scoreLevel(3).label).toBe('częściowa');
    expect(scoreLevel(1).label).toBe('słaba');
  });

  it('pokazuje historię, wyniki od najsłabszych i różnicę względem porównywanego przebiegu', () => {
    TestBed.configureTestingModule({
      imports: [GoldsetComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const fixture = TestBed.createComponent(GoldsetComponent);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne('/api/admin/goldset').flush([
      { id: 10, position: 0, title: 'Tyłozgryz', question: 'Q', reference_answer: '1. Ortodonta', updated_at: '' },
    ]);
    http.expectOne('/api/admin/goldset/runs').flush([RUN, { ...RUN, id: 1, avg_score: 2, note: '' }]);
    http.expectOne('/api/admin/goldset/runs/2').flush({
      run: RUN,
      results: [result(1, 10, 'Tyłozgryz', 1), result(2, 11, 'Połykanie', 5)],
    });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;

    expect(el.textContent).toContain('3.0/5');
    const rows = Array.from(el.querySelectorAll('li button[aria-expanded]')).map((b) => b.textContent?.replace(/\s+/g, ' ').trim());
    expect(rows[0]).toContain('1/5 · słaba');
    expect(rows[1]).toContain('5/5 · dobra');

    const select = el.querySelector('select') as HTMLSelectElement;
    select.value = '1';
    select.dispatchEvent(new Event('change'));
    http.expectOne('/api/admin/goldset/runs/1').flush({
      run: { ...RUN, id: 1 },
      results: [result(3, 10, 'Tyłozgryz', 3), result(4, 11, 'Połykanie', 5)],
    });
    fixture.detectChanges();
    expect(el.textContent).toContain('▼ -2');

    (el.querySelector('li button[aria-expanded]') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el.textContent).toContain('brak: konsultacja ortodontyczna');
    expect(el.textContent).toContain('1. Ortodonta');
  });
});
