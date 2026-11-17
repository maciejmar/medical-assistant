import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { PromptTemplate, TemplateCoverage, TemplateInput, TemplatesService } from '../../core/templates.service';

function apiError(err: unknown, fallback: string): string {
  if (err instanceof HttpErrorResponse && typeof err.error?.detail === 'string') {
    return err.error.detail;
  }
  return fallback;
}

const EMPTY: TemplateInput = {
  name: '',
  description: '',
  body: '',
  requires_patient: true,
  long_answer: true,
  position: 0,
  shared: false,
};

/**
 * Szablony promptów (pastylki w czacie): wspólne (od administratora) i własne lekarza.
 * Wspólny szablon można skopiować do własnych i przerobić; ćwiczenia szablonu to wiersze
 * z punktorem – „Sprawdź ćwiczenia” pokazuje, które mają opis w bazie wiedzy.
 */
@Component({
  selector: 'app-templates',
  standalone: true,
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="mx-auto max-w-4xl space-y-6">
      <div>
        <a routerLink="/chat" class="mb-1 inline-block text-sm text-brand-700 hover:underline">← Asystent</a>
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h1 class="text-2xl font-bold">Szablony odpowiedzi</h1>
          @if (!draftOpen()) {
            <button type="button" class="btn-primary" (click)="startNew()">Nowy szablon</button>
          }
        </div>
        <p class="text-sm text-slate-500">
          Szablon to gotowe polecenie dla asystenta, wybierane w czacie jako pastylka. Asystent dobiera ćwiczenia tylko z listy
          w szablonie, uzasadnia wybór danymi pacjenta, a sposób wykonania bierze z bazy wiedzy.
        </p>
      </div>

      @if (error(); as e) {
        <p class="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ e }}</p>
      }

      @if (draftOpen()) {
        <section class="card space-y-3">
          <h2 class="font-semibold">{{ editingId() ? 'Edycja szablonu' : 'Nowy szablon' }}</h2>
          <div class="grid gap-3 sm:grid-cols-2">
            <div>
              <label class="label" for="t-name">Nazwa pastylki</label>
              <input id="t-name" class="field" maxlength="80" [value]="draft().name" (input)="patch('name', $any($event.target).value)" placeholder="np. Etap 2 · Wydolność" />
            </div>
            <div>
              <label class="label" for="t-desc">Krótki opis (podpowiedź)</label>
              <input id="t-desc" class="field" maxlength="300" [value]="draft().description" (input)="patch('description', $any($event.target).value)" />
            </div>
          </div>
          <div>
            <label class="label" for="t-body">Treść szablonu</label>
            <textarea id="t-body" class="field font-mono text-xs" rows="18" [value]="draft().body" (input)="patch('body', $any($event.target).value)"></textarea>
            <p class="mt-1 text-xs text-slate-500">
              Ćwiczenia wpisuj jako osobne wiersze zaczynające się od „•” (lub „-”) – asystent wybierze tylko z nich i dołączy ich opisy
              z bazy wiedzy. Dopisz cel etapu, liczbę ćwiczeń na spotkanie, kolejność i pola opisu każdego ćwiczenia.
            </p>
          </div>
          <div class="flex flex-wrap gap-4 text-sm">
            <label class="flex items-center gap-2"><input type="checkbox" class="h-4 w-4" [checked]="draft().requires_patient" (change)="toggle('requires_patient')" /> wymaga wybrania pacjenta</label>
            <label class="flex items-center gap-2"><input type="checkbox" class="h-4 w-4" [checked]="draft().long_answer" (change)="toggle('long_answer')" /> długa odpowiedź (mocniejszy model)</label>
            @if (auth.isAdmin() && !editingId()) {
              <label class="flex items-center gap-2"><input type="checkbox" class="h-4 w-4" [checked]="draft().shared" (change)="toggle('shared')" /> wspólny dla wszystkich lekarzy</label>
            }
          </div>
          <div class="flex flex-wrap gap-2">
            <button type="button" class="btn-secondary" [disabled]="busy() || !draft().body.trim()" (click)="checkCoverage()">Sprawdź ćwiczenia w bazie wiedzy</button>
            <span class="flex-1"></span>
            <button type="button" class="btn-secondary" (click)="closeDraft()">Anuluj</button>
            <button type="button" class="btn-primary" [disabled]="busy() || !draft().name.trim() || !draft().body.trim()" (click)="save()">Zapisz</button>
          </div>
          @if (coverage(); as cov) {
            @if (cov.length === 0) {
              <p class="text-sm text-amber-700">W treści nie ma ćwiczeń – dodaj wiersze zaczynające się od „•”.</p>
            } @else {
              <div class="rounded-lg bg-slate-50 p-3 text-sm">
                <p class="mb-1 font-medium">
                  Opis w bazie wiedzy: {{ coveredCount() }} z {{ cov.length }}
                  @if (coveredCount() < cov.length) {
                    <span class="text-amber-700">– dla pozostałych asystent napisze „wg materiałów szkoleniowych”</span>
                  }
                </p>
                <ul class="space-y-0.5 text-xs">
                  @for (c of cov; track $index) {
                    <li>
                      @if (c.found) {
                        <span class="font-semibold text-emerald-700">✓</span> {{ c.name }} <span class="text-slate-500">→ {{ c.exercise_name }} ({{ c.source }})</span>
                      } @else {
                        <span class="font-semibold text-red-600">✗</span> {{ c.name }} <span class="text-slate-500">– brak opisu</span>
                      }
                    </li>
                  }
                </ul>
              </div>
            }
          }
        </section>
      }

      <section class="card space-y-2">
        <h2 class="font-semibold">Moje szablony</h2>
        @if (own().length === 0) {
          <p class="text-sm text-slate-500">Nie masz jeszcze własnych szablonów. Utwórz nowy albo skopiuj wspólny i dostosuj go do siebie.</p>
        }
        <ul class="divide-y divide-slate-100">
          @for (t of own(); track t.id) {
            <li class="flex flex-wrap items-center gap-2 py-2 text-sm">
              <span class="min-w-0 flex-1"><span class="font-medium">{{ t.name }}</span> <span class="text-xs text-slate-500">{{ t.description }}</span></span>
              <button type="button" class="text-xs font-medium text-brand-700 hover:underline" (click)="edit(t)">Edytuj</button>
              <button type="button" class="text-xs font-medium text-slate-400 hover:text-red-600" (click)="remove(t)">Usuń</button>
            </li>
          }
        </ul>
      </section>

      <section class="card space-y-2">
        <h2 class="font-semibold">Szablony wspólne</h2>
        <ul class="divide-y divide-slate-100">
          @for (t of shared(); track t.id) {
            <li class="py-2 text-sm">
              <div class="flex flex-wrap items-center gap-2">
                <details class="min-w-0 flex-1">
                  <summary class="cursor-pointer"><span class="font-medium">{{ t.name }}</span> <span class="text-xs text-slate-500">{{ t.description }}</span></summary>
                  <pre class="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 font-sans text-xs text-slate-700">{{ t.body }}</pre>
                </details>
                <button type="button" class="text-xs font-medium text-brand-700 hover:underline" (click)="copy(t)">Kopiuj do moich</button>
                @if (t.editable) {
                  <button type="button" class="text-xs font-medium text-brand-700 hover:underline" (click)="edit(t)">Edytuj</button>
                  <button type="button" class="text-xs font-medium text-slate-400 hover:text-red-600" (click)="remove(t)">Ukryj</button>
                }
              </div>
            </li>
          }
        </ul>
      </section>
    </div>
  `,
})
export class TemplatesComponent implements OnInit {
  private readonly api = inject(TemplatesService);
  protected readonly auth = inject(AuthService);

  protected readonly items = signal<PromptTemplate[]>([]);
  protected readonly own = computed(() => this.items().filter((t) => !t.shared));
  protected readonly shared = computed(() => this.items().filter((t) => t.shared));
  protected readonly draftOpen = signal(false);
  protected readonly editingId = signal<number | null>(null);
  protected readonly draft = signal<TemplateInput>({ ...EMPTY });
  protected readonly coverage = signal<TemplateCoverage[] | null>(null);
  protected readonly coveredCount = computed(() => (this.coverage() ?? []).filter((c) => c.found).length);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  ngOnInit(): void {
    this.load();
  }

  protected startNew(): void {
    this.editingId.set(null);
    this.draft.set({ ...EMPTY });
    this.coverage.set(null);
    this.draftOpen.set(true);
  }

  protected edit(t: PromptTemplate): void {
    this.editingId.set(t.id);
    this.draft.set({
      name: t.name,
      description: t.description,
      body: t.body,
      requires_patient: t.requires_patient,
      long_answer: t.long_answer,
      position: t.position,
      shared: t.shared,
    });
    this.coverage.set(null);
    this.draftOpen.set(true);
  }

  protected closeDraft(): void {
    this.draftOpen.set(false);
    this.coverage.set(null);
  }

  protected patch(key: 'name' | 'description' | 'body', value: string): void {
    this.draft.update((d) => ({ ...d, [key]: value }));
  }

  protected toggle(key: 'requires_patient' | 'long_answer' | 'shared'): void {
    this.draft.update((d) => ({ ...d, [key]: !d[key] }));
  }

  protected checkCoverage(): void {
    this.busy.set(true);
    this.api.coverage(this.draft().body).subscribe({
      next: (c) => {
        this.busy.set(false);
        this.coverage.set(c);
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.error.set(apiError(err, 'Nie udało się sprawdzić ćwiczeń.'));
      },
    });
  }

  protected save(): void {
    this.busy.set(true);
    this.error.set(null);
    const id = this.editingId();
    const request = id ? this.api.update(id, this.draft()) : this.api.create(this.draft());
    request.subscribe({
      next: () => {
        this.busy.set(false);
        this.closeDraft();
        this.load();
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.error.set(apiError(err, 'Nie udało się zapisać szablonu.'));
      },
    });
  }

  protected copy(t: PromptTemplate): void {
    this.api.copy(t.id).subscribe({
      next: (created) => {
        this.load();
        this.edit(created);
      },
      error: (err: unknown) => this.error.set(apiError(err, 'Nie udało się skopiować szablonu.')),
    });
  }

  protected remove(t: PromptTemplate): void {
    const verb = t.shared ? 'Ukryć szablon wspólny' : 'Usunąć szablon';
    if (!confirm(`${verb} „${t.name}”?`)) {
      return;
    }
    this.api.remove(t.id).subscribe({
      next: () => this.load(),
      error: (err: unknown) => this.error.set(apiError(err, 'Nie udało się usunąć szablonu.')),
    });
  }

  private load(): void {
    this.api.list().subscribe({ next: (list) => this.items.set(list) });
  }
}
