import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Input,
  OnInit,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { PlanService, PlanStatus, PlanStep, PlanStepInput, PlanSuggestion } from '../../core/plan.service';
import { MarkdownPipe } from '../../shared/markdown.pipe';
import { IconComponent, IconName } from '../../shared/icon.component';

interface StatusStyle {
  label: string;
  icon: IconName;
  /** Kolor ikony i etykiety statusu. */
  tone: string;
  /** Akcent (lewa krawędź) karty kroku – tło kart jest wspólne, lekko beżowe. */
  accent: string;
}

/** Statusy kroków: kolor zawsze z ikoną i etykietą (nigdy sam kolor). */
export const PLAN_STATUSES: Record<PlanStatus, StatusStyle> = {
  planned: { label: 'Zaplanowany', icon: 'circle', tone: 'text-sky-700', accent: 'border-l-sky-400' },
  completed: { label: 'Zakończony', icon: 'check-circle', tone: 'text-emerald-700', accent: 'border-l-emerald-500' },
  suspended: { label: 'Zawieszony', icon: 'pause-circle', tone: 'text-amber-700', accent: 'border-l-amber-500' },
  infeasible: { label: 'Niewykonalny', icon: 'x-circle', tone: 'text-red-700', accent: 'border-l-red-500' },
};

const STATUS_ORDER: PlanStatus[] = ['planned', 'completed', 'suspended', 'infeasible'];

function apiError(err: unknown, fallback: string): string {
  if (err instanceof HttpErrorResponse && typeof err.error?.detail === 'string') {
    return err.error.detail;
  }
  return fallback;
}

/**
 * Plan działania: poziomy diagram kart-kroków (nazwa + status), na końcu pusta karta „+” dodająca
 * nowy krok. Kliknięcie karty otwiera okno (`<dialog>`) z nazwą, statusem i opisem kroku – edycja,
 * zmiana kolejności i usunięcie. Opcjonalnie plan trafia do kontekstu asystenta.
 */
@Component({
  selector: 'app-patient-plan',
  standalone: true,
  imports: [IconComponent, MarkdownPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="card mt-6" aria-labelledby="plan-heading">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 id="plan-heading" class="font-semibold">Plan działania</h2>
        <label class="flex cursor-pointer items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            class="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
            [checked]="includeInContext()"
            [disabled]="busy()"
            (change)="toggleContext($any($event.target).checked)"
          />
          Uwzględniaj plan w odpowiedziach asystenta
        </label>
      </div>

      @if (error(); as e) {
        <p class="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ e }}</p>
      }

      @if (loading()) {
        <p class="text-sm text-slate-500">Wczytywanie planu…</p>
      } @else {
        <ol class="flex items-stretch overflow-x-auto pb-2" aria-label="Kroki planu działania">
          @for (step of steps(); track step.id; let i = $index) {
            <li class="flex shrink-0 items-center">
              <button
                type="button"
                class="flex h-full min-h-[7.5rem] w-48 flex-col rounded-xl border border-l-4 border-[#dccbad] bg-[#f3e8d4] p-3 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md hover:brightness-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
                [class]="status(step.status).accent"
                (click)="openStep(step)"
                [attr.aria-label]="'Krok ' + (i + 1) + ': ' + step.title + ', status: ' + status(step.status).label + '. Otwórz szczegóły'"
              >
                <span class="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Krok {{ i + 1 }}</span>
                <span class="mt-1 line-clamp-3 flex-1 text-sm font-semibold text-slate-800">{{ step.title }}</span>
                <span class="mt-2 inline-flex items-center gap-1.5 text-xs font-medium" [class]="status(step.status).tone">
                  <app-icon [name]="status(step.status).icon" [size]="14" />
                  {{ status(step.status).label }}
                </span>
              </button>
              <span class="flex w-8 shrink-0 items-center justify-center text-slate-300" aria-hidden="true">
                <app-icon name="chevron-right" />
              </span>
            </li>
          }
          <li class="flex shrink-0 items-center">
            <button
              type="button"
              class="flex h-full min-h-[7.5rem] w-48 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 text-slate-500 transition hover:border-brand-400 hover:bg-brand-50 hover:text-brand-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
              (click)="openNew()"
              aria-label="Dodaj nowy krok planu"
            >
              <span class="grid h-10 w-10 place-items-center rounded-full bg-slate-100"><app-icon name="plus" [size]="20" /></span>
              <span class="text-sm font-medium">Nowy krok</span>
            </button>
          </li>
        </ol>
        @if (steps().length === 0) {
          <p class="mt-2 text-xs text-slate-500">Plan jest pusty – kliknij „Nowy krok”, aby dodać pierwszy etap terapii.</p>
        }
      }
    </section>

    <dialog
      #dialog
      class="w-[min(36rem,calc(100vw-2rem))] rounded-2xl p-0 shadow-2xl backdrop:bg-slate-900/50"
      aria-labelledby="plan-dialog-title"
      (close)="onDialogClosed()"
    >
      <form class="space-y-4 p-5" (submit)="$event.preventDefault(); saveStep()">
        <div class="flex items-start justify-between gap-3">
          <h3 id="plan-dialog-title" class="text-lg font-semibold">
            {{ editing() ? 'Krok ' + (editingIndex() + 1) : 'Nowy krok' }}
          </h3>
          <button type="button" class="grid h-8 w-8 place-items-center rounded-full text-slate-500 hover:bg-slate-100" (click)="close()" aria-label="Zamknij okno">
            <app-icon name="close" />
          </button>
        </div>

        @if (!editing()) {
          <section class="rounded-xl border border-violet-200 bg-violet-50/60 p-3" aria-live="polite" aria-labelledby="suggestion-heading">
            <div class="mb-2 flex items-center gap-2">
              <span class="grid h-7 w-7 place-items-center rounded-full bg-violet-100 text-violet-700"><app-icon name="lightbulb" [size]="14" /></span>
              <h4 id="suggestion-heading" class="mr-auto text-sm font-semibold text-violet-900">Propozycja asystenta</h4>
              @if (!suggesting()) {
                <button type="button" class="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-violet-700 hover:bg-violet-100" (click)="loadSuggestion()">
                  <app-icon name="refresh" [size]="12" /> {{ suggestion() ? 'Inna propozycja' : 'Zaproponuj' }}
                </button>
              }
            </div>
            @if (suggesting()) {
              <p class="flex items-center gap-2 text-sm text-violet-800">
                <span class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-violet-600 border-t-transparent" aria-hidden="true"></span>
                Analizuję kontekst pacjenta, dotychczasowy plan i bazę wiedzy…
              </p>
            } @else {
              @if (suggestError(); as e) {
                <p class="text-sm text-red-700" role="alert">{{ e }}</p>
              }
              @if (suggestion(); as s) {
              <span class="badge mb-1.5 gap-1" [class]="s.kind === 'diagnostics' ? 'bg-sky-100 text-sky-800' : 'bg-emerald-100 text-emerald-800'">
                <app-icon [name]="s.kind === 'diagnostics' ? 'hospital' : 'flag'" [size]="11" />
                {{ s.kind === 'diagnostics' ? 'Uzupełnienie diagnostyki' : 'Etap terapii' }}
              </span>
              <p class="font-semibold text-slate-900">{{ s.title }}</p>
              <div class="md mt-1 text-sm" [innerHTML]="s.description | markdown"></div>
              @if (s.rationale) {
                <p class="mt-2 text-xs text-slate-600"><span class="font-semibold">Dlaczego teraz:</span> {{ s.rationale }}</p>
              }
              @if (s.sources.length > 0) {
                <ul class="mt-2 space-y-0.5 text-xs text-slate-500">
                  @for (src of s.sources; track src.index) {
                    <li><span class="font-semibold text-violet-700">[{{ src.index }}]</span> {{ src.title }}</li>
                  }
                </ul>
              } @else if (!s.grounded) {
                <p class="mt-2 text-xs text-amber-700">Brak pasujących materiałów w bazie wiedzy – propozycja bez źródeł.</p>
              }
              <div class="mt-3 flex flex-wrap items-center gap-2">
                <button type="button" class="btn-primary !px-3 !py-1.5 !text-xs" (click)="useSuggestion(s)"><app-icon name="check" [size]="12" /> Użyj propozycji</button>
                <span class="text-[11px] text-slate-500">Propozycja wspiera decyzję – ostateczny wybór należy do Ciebie.</span>
              </div>
              }
            }
          </section>
        }

        <div>
          <label class="label" for="plan-title">Nazwa kroku</label>
          <input id="plan-title" class="field" autofocus maxlength="200" required [value]="title()" (input)="title.set($any($event.target).value)" />
        </div>

        <fieldset>
          <legend class="label">Status</legend>
          <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
            @for (key of statusOrder; track key) {
              <button
                type="button"
                class="flex items-center justify-center gap-1.5 rounded-lg border px-2 py-2 text-xs font-medium transition"
                [class]="stepStatus() === key ? 'border-brand-600 bg-brand-50 ring-1 ring-brand-600 ' + status(key).tone : 'border-slate-300 text-slate-600 hover:bg-slate-50'"
                [attr.aria-pressed]="stepStatus() === key"
                (click)="stepStatus.set(key)"
              >
                <app-icon [name]="status(key).icon" [size]="14" />
                {{ status(key).label }}
              </button>
            }
          </div>
        </fieldset>

        <div>
          <label class="label" for="plan-description">Opis kroku</label>
          <textarea id="plan-description" class="field" rows="6" maxlength="20000" placeholder="Cel, ćwiczenia, częstotliwość, kryteria zakończenia…" [value]="description()" (input)="description.set($any($event.target).value)"></textarea>
        </div>

        @if (dialogError(); as e) {
          <p class="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ e }}</p>
        }

        <div class="flex flex-wrap items-center gap-2 border-t border-slate-200 pt-4">
          @if (editing(); as step) {
            <button type="button" class="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold text-red-600 hover:bg-red-50" [disabled]="busy()" (click)="deleteStep(step)">
              <app-icon name="trash" [size]="14" /> Usuń krok
            </button>
            <button type="button" class="grid h-9 w-9 place-items-center rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-100 disabled:opacity-40" [disabled]="busy() || editingIndex() === 0" (click)="move(step, -1)" aria-label="Przesuń krok wcześniej" title="Przesuń wcześniej">
              <app-icon name="arrow-left" />
            </button>
            <button type="button" class="grid h-9 w-9 place-items-center rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-100 disabled:opacity-40" [disabled]="busy() || editingIndex() === steps().length - 1" (click)="move(step, 1)" aria-label="Przesuń krok później" title="Przesuń później">
              <app-icon name="arrow-right" />
            </button>
          }
          <span class="flex-1"></span>
          <button type="button" class="btn-secondary" (click)="close()">Anuluj</button>
          <button type="submit" class="btn-primary" [disabled]="busy() || !title().trim()">
            <app-icon name="check" /> {{ editing() ? 'Zapisz' : 'Dodaj krok' }}
          </button>
        </div>
      </form>
    </dialog>
  `,
})
export class PatientPlanComponent implements OnInit {
  @Input({ required: true }) patientId!: number;
  @ViewChild('dialog') private dialog!: ElementRef<HTMLDialogElement>;

  private readonly api = inject(PlanService);

  protected readonly statusOrder = STATUS_ORDER;
  protected readonly steps = signal<PlanStep[]>([]);
  protected readonly includeInContext = signal(false);
  protected readonly loading = signal(true);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly editing = signal<PlanStep | null>(null);
  protected readonly editingIndex = computed(() => {
    const step = this.editing();
    return step ? this.steps().findIndex((s) => s.id === step.id) : -1;
  });
  protected readonly title = signal('');
  protected readonly description = signal('');
  protected readonly stepStatus = signal<PlanStatus>('planned');
  protected readonly dialogError = signal<string | null>(null);
  protected readonly suggestion = signal<PlanSuggestion | null>(null);
  protected readonly suggesting = signal(false);
  protected readonly suggestError = signal<string | null>(null);
  private suggestRequest = 0;

  ngOnInit(): void {
    this.api.get(this.patientId).subscribe({
      next: (plan) => {
        this.steps.set(plan.steps);
        this.includeInContext.set(plan.include_in_context);
        this.loading.set(false);
      },
      error: (err: unknown) => {
        this.loading.set(false);
        this.error.set(apiError(err, 'Nie udało się wczytać planu działania.'));
      },
    });
  }

  protected status(key: PlanStatus): StatusStyle {
    return PLAN_STATUSES[key] ?? PLAN_STATUSES.planned;
  }

  protected openNew(): void {
    this.open(null, { title: '', description: '', status: 'planned' });
    this.loadSuggestion();
  }

  /** Prosi asystenta o propozycję kolejnego kroku (wynik spóźniony po zamknięciu okna jest pomijany). */
  protected loadSuggestion(): void {
    const request = ++this.suggestRequest;
    this.suggestion.set(null);
    this.suggestError.set(null);
    this.suggesting.set(true);
    this.api.suggest(this.patientId).subscribe({
      next: (s) => {
        if (request === this.suggestRequest) {
          this.suggestion.set(s);
          this.suggesting.set(false);
        }
      },
      error: (err: unknown) => {
        if (request === this.suggestRequest) {
          this.suggesting.set(false);
          this.suggestError.set(apiError(err, 'Nie udało się przygotować propozycji.'));
        }
      },
    });
  }

  /** Przenosi propozycję do formularza (nazwa, opis z uzasadnieniem i źródłami) – lekarz może ją poprawić. */
  protected useSuggestion(s: PlanSuggestion): void {
    const parts = [s.description];
    if (s.rationale) {
      parts.push(`Uzasadnienie: ${s.rationale}`);
    }
    if (s.sources.length > 0) {
      parts.push('Źródła: ' + s.sources.map((src) => `[${src.index}] ${src.title}`).join('; '));
    }
    this.title.set(s.title.slice(0, 200));
    this.description.set(parts.filter(Boolean).join('\n\n').slice(0, 20000));
    this.stepStatus.set('planned');
  }

  protected openStep(step: PlanStep): void {
    this.open(step, step);
  }

  protected close(): void {
    this.dialog.nativeElement.close();
  }

  protected onDialogClosed(): void {
    this.suggestRequest++;
    this.suggesting.set(false);
    this.editing.set(null);
    this.dialogError.set(null);
  }

  protected toggleContext(include: boolean): void {
    this.busy.set(true);
    this.api.setIncludeInContext(this.patientId, include).subscribe({
      next: (r) => {
        this.includeInContext.set(r.include_in_context);
        this.busy.set(false);
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.includeInContext.set(!include);
        this.error.set(apiError(err, 'Nie udało się zmienić ustawienia.'));
      },
    });
  }

  protected saveStep(): void {
    const input: PlanStepInput = {
      title: this.title().trim(),
      description: this.description().trim(),
      status: this.stepStatus(),
    };
    if (!input.title) {
      return;
    }
    const editing = this.editing();
    const request = editing
      ? this.api.update(this.patientId, editing.id, input)
      : this.api.create(this.patientId, input);
    this.busy.set(true);
    this.dialogError.set(null);
    request.subscribe({
      next: (saved) => {
        this.busy.set(false);
        this.steps.update((steps) =>
          editing ? steps.map((s) => (s.id === saved.id ? saved : s)) : [...steps, saved],
        );
        this.close();
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.dialogError.set(apiError(err, 'Nie udało się zapisać kroku.'));
      },
    });
  }

  protected deleteStep(step: PlanStep): void {
    if (!confirm(`Usunąć krok „${step.title}” wraz z opisem?`)) {
      return;
    }
    this.busy.set(true);
    this.api.remove(this.patientId, step.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.steps.update((steps) => steps.filter((s) => s.id !== step.id));
        this.close();
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.dialogError.set(apiError(err, 'Nie udało się usunąć kroku.'));
      },
    });
  }

  protected move(step: PlanStep, offset: -1 | 1): void {
    const ids = this.steps().map((s) => s.id);
    const from = ids.indexOf(step.id);
    const to = from + offset;
    if (from < 0 || to < 0 || to >= ids.length) {
      return;
    }
    [ids[from], ids[to]] = [ids[to], ids[from]];
    this.busy.set(true);
    this.api.reorder(this.patientId, ids).subscribe({
      next: (steps) => {
        this.busy.set(false);
        this.steps.set(steps);
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.dialogError.set(apiError(err, 'Nie udało się zmienić kolejności.'));
      },
    });
  }

  private open(step: PlanStep | null, values: PlanStepInput): void {
    this.editing.set(step);
    this.title.set(values.title);
    this.description.set(values.description);
    this.stepStatus.set(values.status);
    this.dialogError.set(null);
    const dialog = this.dialog.nativeElement;
    if (!dialog.open) {
      dialog.showModal();
    }
  }
}
