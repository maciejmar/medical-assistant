import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { PromptTemplate } from '../../core/templates.service';
import { TemplatesComponent } from './templates.component';

const SHARED: PromptTemplate = {
  id: 1, name: 'Etap 1 · Napięcie', description: 'terapia manualna', body: '• kołyska\n• karuzela',
  requires_patient: true, long_answer: true, position: 0, shared: true, editable: false, updated_at: '',
};

describe('TemplatesComponent', () => {
  it('kopiuje szablon wspólny do własnych i sprawdza ćwiczenia w bazie wiedzy', () => {
    TestBed.configureTestingModule({
      imports: [TemplatesComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    const fixture = TestBed.createComponent(TemplatesComponent);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne('/api/templates').flush([SHARED]);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Nie masz jeszcze własnych szablonów');
    expect(el.textContent).not.toContain('Ukryj'); // wspólnego nie edytuje lekarz

    Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Kopiuj do moich'))!.click();
    const copy = { ...SHARED, id: 9, name: 'Etap 1 · Napięcie (moja)', shared: false, editable: true };
    http.expectOne('/api/templates/1/copy').flush(copy);
    http.expectOne('/api/templates').flush([SHARED, copy]);
    fixture.detectChanges();
    expect((el.querySelector('#t-name') as HTMLInputElement).value).toBe('Etap 1 · Napięcie (moja)');

    Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Sprawdź ćwiczenia'))!.click();
    http.expectOne('/api/templates/coverage').flush([
      { name: 'kołyska', found: true, exercise_name: 'Kołyska', source: 'Rehabilitacja dysfunkcji języka, s. 91' },
      { name: 'karuzela', found: false, exercise_name: '', source: '' },
    ]);
    fixture.detectChanges();
    expect(el.textContent).toContain('Opis w bazie wiedzy: 1 z 2');
    expect(el.textContent).toContain('karuzela – brak opisu');

    Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Zapisz')!.click();
    const save = http.expectOne('/api/templates/9');
    expect(save.request.method).toBe('PUT');
    expect(save.request.body.name).toBe('Etap 1 · Napięcie (moja)');
  });
});
