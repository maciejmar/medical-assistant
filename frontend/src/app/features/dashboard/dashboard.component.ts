import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { PatientsService } from '../../core/patients.service';
import { Patient, RecentNote } from '../../shared/models';
import { ageFromBirthDate, emptyToNull } from '../../shared/utils';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="dashboard-page">
    <div class="page-bg-dashboard"></div>
    <div class="mb-6 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-2xl font-bold">Dzień dobry, {{ auth.user()?.full_name }}</h1>
        <p class="text-sm text-slate-500">Twoi pacjenci i ostatnie działania.</p>
      </div>
      <div class="flex gap-2">
        <a routerLink="/chat" class="btn-secondary">Zapytaj asystenta</a>
        <button type="button" class="btn-primary" (click)="showForm.set(!showForm())">
          {{ showForm() ? 'Zamknij' : 'Dodaj pacjenta' }}
        </button>
      </div>
    </div>

    @if (showForm()) {
      <form class="card mb-6 grid gap-4 sm:grid-cols-2" [formGroup]="form" (ngSubmit)="create()">
        <div>
          <label class="label" for="first">Imię</label>
          <input id="first" class="field" formControlName="first_name" />
        </div>
        <div>
          <label class="label" for="last">Nazwisko</label>
          <input id="last" class="field" formControlName="last_name" />
        </div>
        <div>
          <label class="label" for="birth">Data urodzenia</label>
          <input id="birth" class="field" type="date" formControlName="birth_date" />
        </div>
        <div>
          <label class="label" for="icd">Kod ICD</label>
          <input id="icd" class="field" placeholder="np. F80.0" formControlName="icd_code" />
        </div>
        <div class="sm:col-span-2">
          <label class="label" for="diag">Rozpoznanie</label>
          <input id="diag" class="field" formControlName="diagnosis" />
        </div>
        <div class="flex items-center justify-end gap-2 sm:col-span-2">
          @if (formError()) {
            <span class="mr-auto text-sm text-red-600">{{ formError() }}</span>
          }
          <button type="submit" class="btn-primary" [disabled]="form.invalid || saving()">
            {{ saving() ? 'Zapisywanie…' : 'Zapisz pacjenta' }}
          </button>
        </div>
      </form>
    }

    <div class="grid gap-6 lg:grid-cols-3">
      <section class="card lg:col-span-2">
        <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h2 class="font-semibold">Pacjenci ({{ patients().length }})</h2>
          <input
            class="field max-w-xs"
            type="search"
            placeholder="Szukaj po nazwisku lub rozpoznaniu…"
            [value]="query()"
            (input)="query.set($any($event.target).value)"
          />
        </div>

        @if (loading()) {
          <p class="text-sm text-slate-500">Ładowanie…</p>
        } @else if (filtered().length === 0) {
          <p class="text-sm text-slate-500">
            {{ patients().length === 0 ? 'Nie masz jeszcze żadnych pacjentów.' : 'Brak wyników wyszukiwania.' }}
          </p>
        } @else {
          <ul class="divide-y divide-slate-100">
            @for (p of filtered(); track p.id) {
              <li>
                <a [routerLink]="['/patients', p.id]" class="flex items-center justify-between gap-3 rounded-lg px-2 py-3 hover:bg-slate-50">
                  <div class="min-w-0">
                    <p class="truncate font-medium">{{ p.last_name }} {{ p.first_name }}</p>
                    <p class="truncate text-xs text-slate-500">{{ p.diagnosis || 'Brak rozpoznania' }}</p>
                  </div>
                  <div class="flex shrink-0 items-center gap-2">
                    @if (age(p) !== null) {
                      <span class="badge bg-slate-100 text-slate-600">{{ age(p) }} l.</span>
                    }
                    @if (p.icd_code) {
                      <span class="badge bg-brand-50 text-brand-700">{{ p.icd_code }}</span>
                    }
                  </div>
                </a>
              </li>
            }
          </ul>
        }
      </section>

      <section class="card">
        <h2 class="mb-4 font-semibold">Ostatnie notatki</h2>
        @if (recent().length === 0) {
          <p class="text-sm text-slate-500">Brak ostatnich działań.</p>
        } @else {
          <ul class="space-y-3">
            @for (n of recent(); track n.note_id) {
              <li>
                <a [routerLink]="['/patients', n.patient_id]" class="block rounded-lg p-2 hover:bg-slate-50">
                  <p class="text-sm font-medium">{{ n.patient_name }}</p>
                  <p class="line-clamp-2 text-xs text-slate-500">{{ n.snippet }}</p>
                  <p class="mt-1 text-[11px] text-slate-400">
                    {{ n.created_at | date: 'dd.MM.yyyy HH:mm' }}
                    @if (n.source === 'dictated') { · dyktowana }
                  </p>
                </a>
              </li>
            }
          </ul>
        }
      </section>
    </div>

    <footer class="mt-8 flex flex-col items-center gap-3 rounded-xl bg-[#02121c] px-4 py-2.5 text-xs text-slate-300 sm:flex-row sm:justify-between">
      <p>© 2026 Webaby — oprogramowanie Logoped Assist.</p>
      <div class="flex items-center gap-4">
        <a href="#" target="_blank" rel="noopener noreferrer" aria-label="WhatsApp" class="text-slate-300 transition hover:text-white">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.288.173-1.413-.074-.124-.272-.198-.57-.347z" />
            <path d="M12.04 2C6.52 2 2.04 6.48 2.04 12c0 1.86.51 3.6 1.4 5.1l-1.48 5.4 5.54-1.45c1.45.8 3.08 1.25 4.54 1.25 5.52 0 10-4.48 10-10S17.56 2 12.04 2zm0 18.2c-1.5 0-2.97-.4-4.25-1.16l-.3-.18-3.28.86.88-3.21-.2-.33A8.19 8.19 0 0 1 3.84 12c0-4.56 3.72-8.28 8.3-8.28 4.57 0 8.28 3.72 8.28 8.28 0 4.57-3.71 8.3-8.28 8.3z" />
          </svg>
        </a>
        <a href="#" target="_blank" rel="noopener noreferrer" aria-label="Facebook" class="text-slate-300 transition hover:text-white">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M22.675 0h-21.35C.593 0 0 .592 0 1.325v21.351C0 23.408.593 24 1.325 24H12.82v-9.294H9.692v-3.622h3.128V8.413c0-3.1 1.893-4.788 4.659-4.788 1.325 0 2.464.099 2.795.143v3.24l-1.918.001c-1.504 0-1.795.715-1.795 1.763v2.313h3.587l-.467 3.622h-3.12V24h6.116C23.407 24 24 23.408 24 22.676V1.325C24 .592 23.407 0 22.675 0z" />
          </svg>
        </a>
        <a href="#" target="_blank" rel="noopener noreferrer" aria-label="Instagram" class="text-slate-300 transition hover:text-white">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072c-4.358.2-6.78 2.618-6.98 6.98C.014 8.332 0 8.74 0 12s.014 3.668.072 4.948c.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24s3.668-.014 4.948-.072c4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 1 0 0 12.324 6.162 6.162 0 0 0 0-12.324zM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm6.406-11.845a1.44 1.44 0 1 0 0 2.881 1.44 1.44 0 0 0 0-2.881z" />
          </svg>
        </a>
        <a href="#" target="_blank" rel="noopener noreferrer" aria-label="X (Twitter)" class="text-slate-300 transition hover:text-white">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231 5.451-6.231zm-1.161 17.52h1.833L7.084 4.126H5.117l11.966 15.644z" />
          </svg>
        </a>
      </div>
    </footer>
    </div>
  `,
})
export class DashboardComponent {
  protected readonly auth = inject(AuthService);
  private readonly patientsApi = inject(PatientsService);
  private readonly fb = inject(FormBuilder);

  protected readonly patients = signal<Patient[]>([]);
  protected readonly recent = signal<RecentNote[]>([]);
  protected readonly loading = signal(true);
  protected readonly showForm = signal(false);
  protected readonly saving = signal(false);
  protected readonly formError = signal<string | null>(null);
  protected readonly query = signal('');

  protected readonly filtered = computed(() => {
    const q = this.query().trim().toLowerCase();
    if (!q) {
      return this.patients();
    }
    return this.patients().filter((p) =>
      `${p.first_name} ${p.last_name} ${p.diagnosis ?? ''} ${p.icd_code ?? ''}`
        .toLowerCase()
        .includes(q),
    );
  });

  protected readonly form = this.fb.nonNullable.group({
    first_name: ['', [Validators.required, Validators.maxLength(100)]],
    last_name: ['', [Validators.required, Validators.maxLength(100)]],
    birth_date: [''],
    icd_code: [''],
    diagnosis: [''],
  });

  constructor() {
    this.patientsApi.list().subscribe({
      next: (patients) => {
        this.patients.set(patients);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
    this.patientsApi.recentNotes().subscribe({ next: (notes) => this.recent.set(notes) });
  }

  protected age(patient: Patient): number | null {
    return ageFromBirthDate(patient.birth_date);
  }

  protected create(): void {
    if (this.form.invalid || this.saving()) {
      return;
    }
    const value = this.form.getRawValue();
    this.saving.set(true);
    this.formError.set(null);
    this.patientsApi
      .create({
        first_name: value.first_name.trim(),
        last_name: value.last_name.trim(),
        birth_date: emptyToNull(value.birth_date),
        icd_code: emptyToNull(value.icd_code),
        diagnosis: emptyToNull(value.diagnosis),
        description: null,
      })
      .subscribe({
        next: (patient) => {
          this.patients.update((list) =>
            [...list, patient].sort((a, b) => a.last_name.localeCompare(b.last_name, 'pl')),
          );
          this.form.reset();
          this.showForm.set(false);
          this.saving.set(false);
        },
        error: () => {
          this.formError.set('Nie udało się zapisać pacjenta.');
          this.saving.set(false);
        },
      });
  }
}
