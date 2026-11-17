import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Exercise } from '../../core/exercises.service';
import { ExercisesComponent, searchKey } from './exercises.component';

const DESKA: Exercise = {
  id: 1,
  document_id: 7,
  document_title: 'Rehabilitacja dysfunkcji języka',
  number: '22',
  name: 'Deska na dźwigu',
  goal: 'precyzja ruchów celowych',
  tools: '',
  description: 'Szeroki język unoszony do podniebienia.',
  page: 126,
  complete: true,
  verified: false,
  updated_at: '',
  aliases: [],
};

describe('ExercisesComponent', () => {
  it('preselekcja dokumentów z katalogiem, uruchomienie wyodrębniania i sprawdzenie listy', () => {
    TestBed.configureTestingModule({
      imports: [ExercisesComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    const fixture = TestBed.createComponent(ExercisesComponent);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne('/api/admin/exercises/candidates').flush([
      { document_id: 7, title: 'Rehabilitacja dysfunkcji języka', markers: 120, exercises: 0 },
      { document_id: 8, title: 'Ortotropia', markers: 2, exercises: 0 },
    ]);
    http.expectOne('/api/admin/exercises').flush([DESKA]);
    http.expectOne('/api/admin/exercises/extract').flush(null);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;

    const boxes = Array.from(el.querySelectorAll('li input[type="checkbox"]')) as HTMLInputElement[];
    expect(boxes.map((b) => b.checked)).toEqual([true, false]);
    expect(el.textContent).toContain('Deska na dźwigu');

    const textarea = el.querySelector('textarea') as HTMLTextAreaElement;
    textarea.value = '• deska na dźwigu,\n• kołyska';
    textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Sprawdź')!.click();
    http.expectOne('/api/admin/exercises/match').flush([
      { name: 'deska na dźwigu', score: 1, alias: false, exercise: DESKA },
      { name: 'kołyska', score: 0, alias: false, exercise: null },
    ]);
    fixture.detectChanges();
    expect(el.textContent).toContain('W katalogu: 1 z 2');
    expect(el.textContent).toContain('kołyska – brak w katalogu');

    // „Przypisz” przy braku: wyszukiwarka z katalogu, wybór zapisuje nazwę jako alias.
    Array.from(el.querySelectorAll('button')).filter((b) => b.textContent?.trim() === 'Przypisz')[0].click();
    fixture.detectChanges();
    const search = el.querySelector('input[aria-label="Szukaj ćwiczenia do przypisania"]') as HTMLInputElement;
    expect(search.value).toBe('kolyska');
    search.value = 'dzwig';
    search.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Deska na dźwigu –'))!.click();
    const alias = http.expectOne('/api/admin/exercises/1/aliases');
    expect(alias.request.body).toEqual({ name: 'kołyska' });
    alias.flush({ ...DESKA, verified: true, aliases: [{ id: 5, alias: 'kołyska' }] });
    http.expectOne('/api/admin/exercises/match').flush([]);
    fixture.detectChanges();

    const extract = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Wyodrębnij ćwiczenia'))!;
    extract.click();
    const req = http.expectOne((r) => r.method === 'POST' && r.url === '/api/admin/exercises/extract');
    expect(req.request.body).toEqual({ document_ids: [7] });
    req.flush({
      status: 'running', document_ids: [7], total_windows: 40, done_windows: 0, found: 0, tokens: 0,
      current: '', error: null, started_at: '', finished_at: null,
    });
    fixture.detectChanges();
    expect(el.textContent).toContain('fragment 0 z 40');
    fixture.destroy(); // zatrzymuje odpytywanie postępu
  });

  it('wyszukiwanie bez diakrytyków', () => {
    expect(searchKey('Deska na Dźwigu')).toBe('deska na dzwigu');
    expect(searchKey('Łódeczka')).toBe('lodeczka');
  });
});
