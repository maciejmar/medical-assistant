import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Interview, formatPositions, parsePositions, parseQuestion } from '../../core/interview.service';
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
    http.expectOne('/api/patients/7/interview?form=interview').flush(INTERVIEW);
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
    const request = http.expectOne('/api/patients/7/interview/approve?form=interview');
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

describe('PatientInterviewComponent – sekcje', () => {
  it('nagłówek „## …” jest wierszem sekcji bez pola odpowiedzi, a numeracja pomija sekcje', () => {
    TestBed.configureTestingModule({
      imports: [PatientInterviewComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const fixture = TestBed.createComponent(PatientInterviewComponent);
    fixture.componentInstance.patientId = 7;
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne('/api/patients/7/interview?form=interview').flush({
      ...INTERVIEW,
      items: [
        { id: 10, position: 0, question: '## 1. Powód zgłoszenia', answer: '', has_audio: false, updated_at: '' },
        { id: 11, position: 1, question: 'Osoba zgłaszająca', answer: '', has_audio: false, updated_at: '' },
        { id: 12, position: 2, question: '## 2. Ciąża i poród', answer: '', has_audio: false, updated_at: '' },
        { id: 13, position: 3, question: 'Rodzaj porodu', answer: '', has_audio: false, updated_at: '' },
      ],
    });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const headers = Array.from(el.querySelectorAll('tbody th')).map((th) => th.textContent?.replace(/\s+/g, ' ').trim());
    expect(headers).toEqual(['1. Powód zgłoszeniaUsuń', '2. Ciąża i poródUsuń']);
    expect(el.querySelectorAll('tbody textarea').length).toBe(2);
    expect(el.textContent).toContain('2. Rodzaj porodu');
  });
});

describe('pytania szablonu z podpowiedziami', () => {
  it('rozbiera tytuł, podpowiedzi i flagę trzech pól', () => {
    expect(parseQuestion('Wargi | Co oceniamy: Budowa, symetria.')).toEqual({
      title: 'Wargi',
      hints: [{ label: 'Co oceniamy', text: 'Budowa, symetria.' }],
      positions: false,
    });
    const art = parseQuestion('Artykulacja – r | Głoski: r | @pozycje');
    expect(art.title).toBe('Artykulacja – r');
    expect(art.positions).toBeTrue();
    expect(parseQuestion('Zwykłe pytanie?')).toEqual({ title: 'Zwykłe pytanie?', hints: [], positions: false });
  });

  it('nagłos / śródgłos / wygłos ↔ tekst odpowiedzi', () => {
    expect(formatPositions(['r → l', '', 'r → j'])).toBe('Nagłos: r → l\nWygłos: r → j');
    expect(parsePositions('Nagłos: r → l\nWygłos: r → j')).toEqual(['r → l', '', 'r → j']);
    // Transkrypcja doklejona bez etykiety trafia do nagłosu – nic nie ginie.
    expect(parsePositions('Nagłos: ok\nwszędzie rotacyzm')).toEqual(['ok wszędzie rotacyzm', '', '']);
  });

  it('karta ankyloglosji: podpowiedzi pod próbą, trzy pola przy artykulacji, zapis z ?form=', () => {
    TestBed.configureTestingModule({
      imports: [PatientInterviewComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const fixture = TestBed.createComponent(PatientInterviewComponent);
    fixture.componentInstance.patientId = 7;
    fixture.componentInstance.form = 'ankyloglossia';
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne('/api/patients/7/interview?form=ankyloglossia').flush({
      ...INTERVIEW,
      items: [
        { id: 21, position: 0, question: 'Wysuwanie języka | Jak wykonać: Maksymalnie wysunąć. | Na co zwracamy uwagę: Efekt struny.', answer: '', has_audio: false, updated_at: '' },
        { id: 22, position: 1, question: 'Artykulacja – r | Głoski: r | @pozycje', answer: 'Wygłos: r → j', has_audio: false, updated_at: '' },
      ],
    });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Karta badania – diagnoza ankyloglosji');
    expect(el.textContent).toContain('1. Wysuwanie języka');
    expect(el.textContent).toContain('Na co zwracamy uwagę:');
    expect(el.textContent).not.toContain('@pozycje');

    const inputs = el.querySelectorAll<HTMLInputElement>('tbody input');
    expect(inputs.length).toBe(3);
    expect(inputs[2].value).toBe('r → j');
    inputs[0].value = 'r → l';
    inputs[0].dispatchEvent(new Event('input'));
    fixture.detectChanges();

    (Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Zapisz szkic') as HTMLButtonElement).click();
    const save = http.expectOne('/api/patients/7/interview?form=ankyloglossia');
    expect(save.request.method).toBe('PUT');
    expect(save.request.body.items[1].answer).toBe('Nagłos: r → l\nWygłos: r → j');
  });
});
