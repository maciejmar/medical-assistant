import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Plan, PlanStep } from '../../core/plan.service';
import { PatientPlanComponent } from './patient-plan.component';

const STEP: PlanStep = {
  id: 5,
  position: 0,
  title: 'Diagnoza',
  description: 'Badanie artykulacji',
  status: 'completed',
  created_at: '',
  updated_at: '',
};
const PLAN: Plan = {
  include_in_context: false,
  steps: [STEP, { ...STEP, id: 6, position: 1, title: 'Pionizacja języka', status: 'suspended' }],
};

describe('PatientPlanComponent', () => {
  function setup() {
    TestBed.configureTestingModule({
      imports: [PatientPlanComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const fixture = TestBed.createComponent(PatientPlanComponent);
    fixture.componentInstance.patientId = 3;
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne('/api/patients/3/plan').flush(PLAN);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const button = (text: string) =>
      Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.trim().includes(text))!;
    return { fixture, http, el, button };
  }

  afterEach(() => {
    document.querySelectorAll('dialog[open]').forEach((d) => (d as HTMLDialogElement).close());
  });

  it('rysuje karty kroków ze statusem i pustą kartę nowego kroku na końcu', () => {
    const { el } = setup();
    const cards = Array.from(el.querySelectorAll('ol > li')).map((li) => li.textContent?.replace(/\s+/g, ' ').trim());
    expect(cards).toEqual(['Krok 1Diagnoza Zakończony', 'Krok 2Pionizacja języka Zawieszony', 'Nowy krok']);
  });

  it('kliknięcie karty otwiera okno, w którym można zmienić nazwę, status i opis', () => {
    const { fixture, http, el, button } = setup();
    button('Diagnoza').click();
    fixture.detectChanges();
    const dialog = el.querySelector('dialog')!;
    expect(dialog.open).toBeTrue();
    const title = dialog.querySelector<HTMLInputElement>('#plan-title')!;
    expect(title.value).toBe('Diagnoza');
    expect(dialog.querySelector<HTMLTextAreaElement>('#plan-description')!.value).toBe('Badanie artykulacji');

    title.value = 'Diagnoza wstępna';
    title.dispatchEvent(new Event('input'));
    button('Niewykonalny').click();
    fixture.detectChanges();
    button('Zapisz').click();

    const request = http.expectOne('/api/patients/3/plan/steps/5');
    expect(request.request.method).toBe('PUT');
    expect(request.request.body).toEqual({
      title: 'Diagnoza wstępna',
      description: 'Badanie artykulacji',
      status: 'infeasible',
    });
    request.flush({ ...STEP, title: 'Diagnoza wstępna', status: 'infeasible' });
    fixture.detectChanges();
    expect(dialog.open).toBeFalse();
    expect(el.querySelector('ol')!.textContent).toContain('Niewykonalny');
  });

  it('pusta karta „Nowy krok” tworzy krok na końcu planu', () => {
    const { fixture, http, el, button } = setup();
    button('Nowy krok').click();
    fixture.detectChanges();
    const title = el.querySelector<HTMLInputElement>('#plan-title')!;
    expect(title.value).toBe('');
    title.value = 'Utrwalanie';
    title.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    button('Dodaj krok').click();

    const request = http.expectOne('/api/patients/3/plan/steps');
    expect(request.request.method).toBe('POST');
    expect(request.request.body.status).toBe('planned');
    request.flush({ ...STEP, id: 9, position: 2, title: 'Utrwalanie', status: 'planned' });
    fixture.detectChanges();
    expect(el.querySelectorAll('ol > li').length).toBe(4);
  });
});
