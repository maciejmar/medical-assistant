import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { CalendarEvent } from '../core/calendar.service';
import { dayKey } from './calendar-utils';
import { PatientCalendarComponent } from './patient-calendar.component';

function at(day: number, hour: number): string {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), day, hour, 0).toISOString();
}

const EVENTS: CalendarEvent[] = [
  { id: 1, type: 'visit', title: 'Wizyta kontrolna', starts_at: at(10, 9), ends_at: at(10, 10), all_day: false, location: 'Gabinet', description: '', plan_step_id: null, plan_step_title: null, created_by_role: 'doctor', editable: false, updated_at: '' },
  { id: 2, type: 'consultation', title: 'Laryngolog', starts_at: at(10, 12), ends_at: null, all_day: false, location: '', description: '', plan_step_id: null, plan_step_title: null, created_by_role: 'patient', editable: true, updated_at: '' },
];

describe('PatientCalendarComponent', () => {
  function setup(patientId: number | null) {
    TestBed.configureTestingModule({
      imports: [PatientCalendarComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const fixture = TestBed.createComponent(PatientCalendarComponent);
    fixture.componentInstance.patientId = patientId;
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    const base = patientId === null ? '/api/portal/events' : `/api/patients/${patientId}/events`;
    const lists = http.match((r) => r.url === base);
    expect(lists.length).toBe(2); // miesiąc + najbliższe
    lists[0].flush(EVENTS);
    lists[1].flush([]);
    if (patientId !== null) {
      http.expectOne(`/api/patients/${patientId}/plan`).flush({ include_in_context: false, steps: [] });
    }
    fixture.detectChanges();
    return { fixture, http, el: fixture.nativeElement as HTMLElement, base };
  }

  afterEach(() => document.querySelectorAll('dialog[open]').forEach((d) => (d as HTMLDialogElement).close()));

  it('pokazuje wydarzenia z ikonami w dniu miesiąca', () => {
    const { el } = setup(5);
    const now = new Date();
    const cell = Array.from(el.querySelectorAll<HTMLElement>('[role="button"]')).find((c) =>
      c.getAttribute('aria-label')?.includes('wydarzenia: 2'),
    );
    expect(cell).toBeDefined();
    expect(cell!.querySelectorAll('button svg').length).toBe(2);
    expect(cell!.textContent).toContain('Wizyta kontrolna');
    expect(dayKey(new Date(EVENTS[0].starts_at)).startsWith(String(now.getFullYear()))).toBeTrue();
  });

  it('pacjent widzi wizytę logopedy tylko do odczytu, a może dodać konsultację', () => {
    const { fixture, http, el, base } = setup(null);
    const visit = Array.from(el.querySelectorAll<HTMLButtonElement>('button')).find((b) =>
      b.getAttribute('aria-label')?.startsWith('Wizyta u logopedy: Wizyta kontrolna'),
    )!;
    visit.click();
    fixture.detectChanges();
    const dialog = el.querySelector('dialog')!;
    expect(dialog.open).toBeTrue();
    expect(dialog.textContent).toContain('dodane przez logopedę');
    expect(dialog.querySelector('#ev-title')).toBeNull();
    dialog.close();

    const add = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Dodaj wydarzenie'))!;
    add.click();
    fixture.detectChanges();
    const types = Array.from(dialog.querySelectorAll('fieldset button')).map((b) => b.textContent?.trim());
    expect(types).toEqual(['Konsultacja', 'Inne']);
    const title = dialog.querySelector<HTMLInputElement>('#ev-title')!;
    title.value = 'Neurolog';
    title.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    (Array.from(dialog.querySelectorAll('button')).find((b) => b.textContent?.includes('Zapisz')) as HTMLButtonElement).click();
    const request = http.expectOne((r) => r.method === 'POST' && r.url === base);
    expect(request.request.body.type).toBe('consultation');
    expect(request.request.body.title).toBe('Neurolog');
  });
});
