import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { PromptTemplate } from '../../core/templates.service';
import { ChatComponent, templateQuestion } from './chat.component';

const STAGE: PromptTemplate = {
  id: 2,
  name: 'Etap 2 · Wydolność',
  description: 'Rozgrzewka języka',
  body: 'ETAP 2\n• „glonojad”\n• huśtawka',
  requires_patient: true,
  long_answer: true,
  position: 1,
  shared: true,
  editable: false,
  updated_at: '',
};

describe('ChatComponent – szablony (pastylki)', () => {
  function setup() {
    TestBed.configureTestingModule({
      imports: [ChatComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    const fixture = TestBed.createComponent(ChatComponent);
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/api/chat/conversations').flush([]);
    http.expectOne('/api/patients').flush([{ id: 5, first_name: 'Jan', last_name: 'Kowalski' }]);
    http.expectOne('/api/templates').flush([STAGE]);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  it('pastylka wymaga pacjenta, podgląd pokazuje treść szablonu', () => {
    const { fixture, el } = setup();
    const send = () => Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Wyślij') as HTMLButtonElement;
    expect(send().disabled).toBeTrue();

    const pill = el.querySelector('button[aria-pressed]') as HTMLButtonElement;
    expect(pill.textContent).toContain('Etap 2 · Wydolność');
    pill.click();
    fixture.detectChanges();
    expect(pill.getAttribute('aria-pressed')).toBe('true');
    expect(el.textContent).toContain('Wybierz pacjenta');
    expect(send().disabled).toBeTrue();
    expect(el.querySelector('#patient')!.getAttribute('aria-invalid')).toBe('true');

    (el.querySelector('button[aria-label="Podgląd szablonu Etap 2 · Wydolność"]') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el.querySelector('pre')!.textContent).toContain('• „glonojad”');

    (fixture.componentInstance as unknown as { patientId: { set(v: number): void } }).patientId.set(5);
    fixture.detectChanges();
    expect(el.textContent).toContain('dłuższa odpowiedź');
    expect(send().disabled).toBeFalse();
  });

  it('treść pytania z pastylki', () => {
    expect(templateQuestion(STAGE, '')).toBe('Przygotuj plan: Etap 2 · Wydolność');
    expect(templateQuestion(STAGE, ' bez pracy wewnątrz jamy ustnej ')).toBe(
      'Przygotuj plan: Etap 2 · Wydolność\nUwagi lekarza: bez pracy wewnątrz jamy ustnej',
    );
  });
});
