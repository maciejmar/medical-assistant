import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { LEAVE_MS, PatientExamsComponent } from './patient-exams.component';

const EMPTY = { status: 'draft', approved_at: null, updated_at: '', items: [] };

describe('PatientExamsComponent – przełącznik Wywiad / Diagnoza ankyloglosji', () => {
  it('domyślnie wywiad; zmiana animuje wyjście, potem pokazuje drugą kartę i zachowuje pierwszą', fakeAsync(() => {
    TestBed.configureTestingModule({
      imports: [PatientExamsComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const fixture = TestBed.createComponent(PatientExamsComponent);
    fixture.componentInstance.patientId = 7;
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne('/api/patients/7/interview?form=interview').flush(EMPTY);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const tabs = el.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    expect(Array.from(tabs).map((t) => t.textContent?.trim())).toEqual(['Wywiad', 'Diagnoza ankyloglosji']);
    expect(tabs[0].getAttribute('aria-selected')).toBe('true');
    const panel = () => el.querySelector<HTMLElement>('#exam-panel-interview')!;
    expect(panel().classList).toContain('exam-enter');
    expect(el.querySelector('#exam-panel-ankyloglossia')).toBeNull(); // karta ankyloglosji jeszcze niezałożona

    tabs[1].click();
    fixture.detectChanges();
    expect(tabs[1].getAttribute('aria-selected')).toBe('true');
    expect(panel().classList).toContain('exam-leave');
    http.expectNone('/api/patients/7/interview?form=ankyloglossia');

    tick(LEAVE_MS);
    fixture.detectChanges();
    http.expectOne('/api/patients/7/interview?form=ankyloglossia').flush(EMPTY);
    fixture.detectChanges();
    expect(panel().hidden).toBeTrue();
    const exam = el.querySelector<HTMLElement>('#exam-panel-ankyloglossia')!;
    expect(exam.hidden).toBeFalse();
    expect(exam.classList).toContain('exam-enter');
    expect(exam.textContent).toContain('Karta badania – diagnoza ankyloglosji');

    // Powrót: wywiad nie jest wczytywany ponownie (stan formularza zachowany).
    tabs[0].click();
    fixture.detectChanges();
    tick(LEAVE_MS);
    fixture.detectChanges();
    expect(panel().hidden).toBeFalse();
    expect(exam.hidden).toBeTrue();
    http.verify();
  }));
});
