import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Interview } from '../../core/interview.service';
import { PatientInterviewComponent, mergeTranscript } from './patient-interview.component';

const INTERVIEW: Interview = {
  status: 'draft',
  approved_at: null,
  updated_at: '2026-11-07T10:00:00Z',
  items: [
    { id: 1, position: 0, question: 'Powód zgłoszenia?', answer: '', has_audio: false, updated_at: '' },
    { id: 2, position: 1, question: 'Rozwój mowy?', answer: 'Pierwsze słowa ok. 1 r.ż.', has_audio: true, updated_at: '' },
  ],
};

describe('mergeTranscript', () => {
  it('wstawia transkrypcję do pustej odpowiedzi, a do istniejącej dokleja', () => {
    expect(mergeTranscript('', ' Seplenienie ')).toBe('Seplenienie');
    expect(mergeTranscript('Rotacyzm.', 'Od 4 r.ż.')).toBe('Rotacyzm. Od 4 r.ż.');
    expect(mergeTranscript('Bez zmian', '  ')).toBe('Bez zmian');
  });
});

describe('PatientInterviewComponent', () => {
  function setup() {
    TestBed.configureTestingModule({
      imports: [PatientInterviewComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const fixture = TestBed.createComponent(PatientInterviewComponent);
    fixture.componentInstance.patientId = 7;
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne('/api/patients/7/interview').flush(INTERVIEW);
    fixture.detectChanges();
    return { fixture, http, el: fixture.nativeElement as HTMLElement };
  }

  it('pokazuje tabelę pytań z odpowiedziami i odsłuchem tylko przy nagraniu', () => {
    const { el } = setup();
    const rows = el.querySelectorAll('tbody tr');
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('1. Powód zgłoszenia?');
    const answers = Array.from(el.querySelectorAll<HTMLTextAreaElement>('tbody textarea')).map((t) => t.value);
    expect(answers).toEqual(['', 'Pierwsze słowa ok. 1 r.ż.']);
    expect(rows[0].querySelector('[aria-label^="Odsłuchaj"]')).toBeNull();
    expect(rows[1].querySelector('[aria-label^="Odsłuchaj"]')).not.toBeNull();
  });

  it('Zatwierdź wysyła poprawione odpowiedzi i pokazuje status zatwierdzenia', () => {
    const { fixture, http, el } = setup();
    const textarea = el.querySelector<HTMLTextAreaElement>('tbody textarea')!;
    textarea.value = 'Nie wymawia r';
    textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(el.textContent).toContain('Niezapisane zmiany');

    const approve = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Zatwierdź')!;
    approve.click();
    const request = http.expectOne('/api/patients/7/interview/approve');
    expect(request.request.method).toBe('POST');
    expect(request.request.body.items).toEqual([
      { id: 1, question: 'Powód zgłoszenia?', answer: 'Nie wymawia r' },
      { id: 2, question: 'Rozwój mowy?', answer: 'Pierwsze słowa ok. 1 r.ż.' },
    ]);
    request.flush({
      ...INTERVIEW,
      status: 'approved',
      approved_at: '2026-11-07T11:00:00Z',
      items: [{ ...INTERVIEW.items[0], answer: 'Nie wymawia r' }, INTERVIEW.items[1]],
    });
    fixture.detectChanges();
    expect(el.textContent).toContain('Zatwierdzony');
    expect(el.textContent).not.toContain('Niezapisane zmiany');
  });
});
