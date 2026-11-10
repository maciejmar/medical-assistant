import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { DoctorCalendarEvent } from '../../core/calendar.service';
import { DoctorCalendarComponent } from './doctor-calendar.component';

function at(dayOffset: number, hour: number): string {
  const monday = new Date();
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7) + dayOffset);
  return new Date(monday.getFullYear(), monday.getMonth(), monday.getDate(), hour, 0).toISOString();
}

function event(id: number, patientId: number, name: string, day: number, hour: number): DoctorCalendarEvent {
  return {
    id,
    type: 'visit',
    title: `Wizyta ${id}`,
    starts_at: at(day, hour),
    ends_at: at(day, hour + 1),
    all_day: false,
    location: '',
    description: '',
    plan_step_id: null,
    plan_step_title: null,
    created_by_role: 'doctor',
    editable: true,
    updated_at: '',
    patient_id: patientId,
    patient_name: name,
  };
}

describe('DoctorCalendarComponent', () => {
  function setup() {
    TestBed.configureTestingModule({
      imports: [DoctorCalendarComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    const fixture = TestBed.createComponent(DoctorCalendarComponent);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne('/api/patients').flush([
      { id: 1, first_name: 'Ala', last_name: 'Nowak' },
      { id: 2, first_name: 'Olek', last_name: 'Zając' },
    ]);
    const calls = http.match((r) => r.url === '/api/calendar/events');
    expect(calls.length).toBe(2); // widoczny tydzień + 14 dni do wolnych terminów
    const events = [event(1, 1, 'Ala Nowak', 0, 9), event(2, 2, 'Olek Zając', 0, 9), event(3, 1, 'Ala Nowak', 2, 14)];
    calls[0].flush(events);
    calls[1].flush([]);
    fixture.detectChanges();
    return { fixture, http, el: fixture.nativeElement as HTMLElement };
  }

  afterEach(() => document.querySelectorAll('dialog[open]').forEach((d) => (d as HTMLDialogElement).close()));

  it('pokazuje wydarzenia wielu pacjentów z inicjałami, obok siebie przy nakładaniu', () => {
    const { el } = setup();
    const blocks = Array.from(el.querySelectorAll<HTMLButtonElement>('button[aria-label^="Wizyta u logopedy"]'));
    expect(blocks.length).toBe(3);
    expect(blocks.map((b) => b.textContent?.replace(/\s+/g, ' ').trim().slice(0, 2))).toEqual(['AN', 'OZ', 'AN']);
    const overlapping = blocks.filter((b) => b.getAttribute('aria-label')!.includes('09:00'));
    expect(overlapping.map((b) => b.style.width)).toEqual(['calc(50% - 4px)', 'calc(50% - 4px)']);
    expect(el.textContent).toContain('Ala Nowak');
    expect(el.textContent).toContain('Olek Zając');
  });

  it('filtr pacjenta ukrywa jego wydarzenia', () => {
    const { fixture, el } = setup();
    const checkbox = Array.from(el.querySelectorAll<HTMLLabelElement>('aside label')).find((l) => l.textContent?.includes('Ala Nowak'))!.querySelector('input')!;
    checkbox.click();
    fixture.detectChanges();
    expect(el.querySelectorAll('button[aria-label^="Wizyta u logopedy"]').length).toBe(1);
  });

  it('nowe wydarzenie wymaga wyboru pacjenta i trafia do jego kalendarza', () => {
    const { fixture, http, el } = setup();
    Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Nowe wydarzenie'))!.click();
    fixture.detectChanges();
    const dialog = el.querySelector('dialog')!;
    const save = Array.from(dialog.querySelectorAll('button')).find((b) => b.textContent?.includes('Zapisz')) as HTMLButtonElement;
    expect(save.disabled).toBeTrue();
    const select = dialog.querySelector('#dc-patient') as HTMLSelectElement;
    select.value = '2';
    select.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(save.disabled).toBeFalse();
    save.click();
    const req = http.expectOne((r) => r.method === 'POST' && r.url === '/api/patients/2/events');
    expect(req.request.body.type).toBe('visit');
  });
});
