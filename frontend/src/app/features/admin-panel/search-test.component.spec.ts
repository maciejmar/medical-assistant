import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { SearchTestComponent, SearchTestResult } from './search-test.component';

const RESULT: SearchTestResult = {
  question: 'przygotowanie do zabiegu',
  rewritten_query: 'przygotowanie do frenuloplastyki ćwiczenia czynne',
  filters: { category: 'technique' },
  top_k: 12,
  top_n: 6,
  min_score: 0.02,
  rows: [
    { id: 'b1', title: 'Książka (cz. 108/127)', document_id: 1, snippet: 'opieka okołozabiegowa', score: 0.94, dense_rank: 1, sparse_rank: 2, fusion_rank: 1, candidate: true, selected: true },
    { id: 'w1', title: 'Wędzidełko (cz. 3/10)', document_id: 2, snippet: 'ankyloglosja', score: 0.81, dense_rank: 31, sparse_rank: null, fusion_rank: null, candidate: false, selected: false },
    { id: 'x9', title: 'Inne (cz. 1/1)', document_id: 3, snippet: 'szum', score: 0.001, dense_rank: 40, sparse_rank: null, fusion_rank: 44, candidate: false, selected: false },
  ],
  focus: { document_id: 2, title: 'Wędzidełko', chunks: 10, best_score: 0.81, verdict: 'Żaden fragment nie wszedł do 12 kandydatów wyszukiwania.' },
};

describe('SearchTestComponent', () => {
  it('wysyła pytanie ze wskazanym dokumentem i pokazuje werdykt oraz etapy', () => {
    TestBed.configureTestingModule({
      imports: [SearchTestComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const fixture = TestBed.createComponent(SearchTestComponent);
    fixture.componentRef.setInput('documents', [{ id: 2, title: 'Wędzidełko' }]);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;

    const input = el.querySelector('#st-question') as HTMLInputElement;
    input.value = 'przygotowanie do zabiegu';
    input.dispatchEvent(new Event('input'));
    const select = el.querySelector('#st-doc') as HTMLSelectElement;
    select.value = '2';
    select.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    (Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Sprawdź') as HTMLButtonElement).click();

    const req = http.expectOne('/api/admin/knowledge/search-test');
    expect(req.request.body).toEqual({ question: 'przygotowanie do zabiegu', document_id: 2 });
    req.flush(RESULT);
    fixture.detectChanges();

    expect(el.textContent).toContain('przygotowanie do frenuloplastyki ćwiczenia czynne');
    expect(el.textContent).toContain('Żaden fragment nie wszedł do 12 kandydatów');
    expect(el.textContent).toContain('źródło');
    expect(el.textContent).toContain('poza kandydatami');
    expect(el.textContent).not.toContain('Inne (cz. 1/1)'); // szum ukryty do „Pokaż wszystkie”

    (Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Pokaż wszystkie')) as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el.textContent).toContain('Inne (cz. 1/1)');
    http.verify();
  });
});
