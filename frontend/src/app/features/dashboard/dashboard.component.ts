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
