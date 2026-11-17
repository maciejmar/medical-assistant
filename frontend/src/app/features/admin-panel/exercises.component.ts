import { DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  Exercise,
  ExerciseCandidate,
  ExerciseInput,
  ExerciseMatch,
  ExercisesService,
  ExtractionStatus,
} from '../../core/exercises.service';

const POLL_MS = 2000;

function apiError(err: unknown, fallback: string): string {
  if (err instanceof HttpErrorResponse && typeof err.error?.detail === 'string') {
    return err.error.detail;
  }
  return fallback;
}

/** Bez diakrytyków i wielkości liter – filtr listy ćwiczeń. */
export function searchKey(text: string): string {
  return text
    .toLowerCase()
    .replace(/ł/g, 'l')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '');
}

/**
 * Katalog ćwiczeń: jednorazowe wyodrębnienie ćwiczeń z dokumentów bazy wiedzy (model czyta
 * tekst w zachodzących oknach), przegląd i poprawki administratora oraz sprawdzenie, które
 * ćwiczenia z wklejonej listy (np. bazy etapu terapii) mają opis w katalogu.
 */
@Component({
  selector: 'app-exercises',
  standalone: true,
  imports: [DecimalPipe, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="space-y-6">
      <div>
        <a routerLink="/admin/knowledge" class="mb-1 inline-block text-sm text-brand-700 hover:underline">← Baza wiedzy</a>
        <h1 class="text-2xl font-bold">Katalog ćwiczeń</h1>
        <p class="text-sm text-slate-500">
          Każde ćwiczenie z materiałów bazy wiedzy jako jeden kompletny rekord (nazwa, cel, narzędzia, opis, strona) –
          niezależnie od podziału tekstu na fragmenty. Z katalogu korzystają szablony z listą ćwiczeń, żeby opisy były dokładne.
        </p>
      </div>

      @if (error(); as e) {
        <p class="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ e }}</p>
      }

      <!-- Wyodrębnianie -->
      <section class="card space-y-3">
        <h2 class="font-semibold">Wyodrębnij z bazy wiedzy</h2>
        @if (candidates().length === 0) {
          <p class="text-sm text-slate-500">Nie znaleziono dokumentów z katalogiem ćwiczeń (szukane znaczniki: „CEL:”, „OPIS TECHNIKI”, „POTRZEBNE NARZĘDZIA”…).</p>
        } @else {
          <p class="text-xs text-slate-500">
            Dokumenty, w których widać opisy ćwiczeń (liczba znaczników ≈ liczba ćwiczeń). Ponowne wyodrębnienie zastępuje
            niesprawdzone ćwiczenia dokumentu – sprawdzone i poprawione zostają.
          </p>
          <ul class="divide-y divide-slate-100 text-sm">
            @for (c of candidates(); track c.document_id) {
              <li class="flex items-center gap-3 py-2">
                <input type="checkbox" class="h-4 w-4" [id]="'doc-' + c.document_id" [checked]="chosen().has(c.document_id)" (change)="toggleDoc(c.document_id)" [disabled]="!!running()" />
                <label class="min-w-0 flex-1 truncate font-medium" [for]="'doc-' + c.document_id">{{ c.title }}</label>
                <span class="text-xs tabular-nums text-slate-500">znaczników: {{ c.markers }}</span>
                <span class="badge" [class]="c.exercises ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'">ćwiczeń: {{ c.exercises }}</span>
              </li>
            }
          </ul>
          <div class="flex flex-wrap items-center gap-3">
            <button type="button" class="btn-primary" [disabled]="!!running() || chosen().size === 0 || busy()" (click)="extract()">
              Wyodrębnij ćwiczenia ({{ chosen().size }} {{ chosen().size === 1 ? 'dokument' : 'dokumenty' }})
            </button>
            <span class="text-xs text-slate-500">Koszt liczony w Twoich kredytach – książka ok. 130 stron to ok. 20–30 kredytów i kilka minut.</span>
          </div>
        }
        @if (job(); as j) {
          <div role="status" aria-live="polite" class="rounded-lg bg-slate-50 p-3 text-sm">
            @if (j.status === 'running') {
              <div class="mb-1 flex justify-between text-xs text-slate-600">
                <span>{{ j.current || 'Przygotowanie' }} – fragment {{ j.done_windows }} z {{ j.total_windows }}, znaleziono {{ j.found }}…</span>
                <button type="button" class="font-medium text-red-600 hover:underline" (click)="cancel()">Zatrzymaj</button>
              </div>
              <div class="h-2 overflow-hidden rounded-full bg-slate-200">
                <div class="h-full rounded-full bg-brand-500 transition-all" [style.width.%]="j.total_windows ? (100 * j.done_windows) / j.total_windows : 0"></div>
              </div>
            } @else {
              <p [class]="j.status === 'done' ? 'text-emerald-800' : 'text-red-700'">
                {{ jobLabel(j) }} Dodano ćwiczeń: {{ j.found }} · tokeny: {{ j.tokens | number }}.
                @if (j.error) { <span class="block text-xs">{{ j.error }}</span> }
              </p>
            }
          </div>
        }
      </section>

      <!-- Sprawdzenie listy -->
      <section class="card space-y-3">
        <h2 class="font-semibold">Sprawdź listę ćwiczeń</h2>
        <p class="text-xs text-slate-500">
          Wklej listę nazw (np. bazę ćwiczeń z promptu etapu terapii, z punktorami) – zobaczysz, które ćwiczenia mają opis w katalogu,
          a których brakuje. Nagłówki pisane wielkimi literami i wiersze kończące się dwukropkiem są pomijane.
        </p>
        <textarea class="field font-mono text-xs" rows="6" [value]="matchText()" (input)="matchText.set($any($event.target).value)" aria-label="Lista nazw ćwiczeń"></textarea>
        <button type="button" class="btn-secondary" [disabled]="busy() || !matchText().trim()" (click)="checkList()">Sprawdź</button>
        @if (matches().length) {
          <p class="text-sm font-medium">
            W katalogu: {{ matchedCount() }} z {{ matches().length }}
            @if (matchedCount() < matches().length) { <span class="text-amber-700">– brakuje {{ matches().length - matchedCount() }}</span> }
          </p>
          <ul class="divide-y divide-slate-100 text-sm">
            @for (m of matches(); track $index) {
              <li class="py-1.5">
                @if (m.exercise; as ex) {
                  <details>
                    <summary class="cursor-pointer">
                      <span class="font-semibold text-emerald-700">✓</span> {{ m.name }}
                      <span class="text-xs text-slate-500">→ {{ ex.name }} ({{ ex.document_title }}{{ ex.page ? ', s. ' + ex.page : '' }}){{ m.score < 1 ? ' · dopasowanie ' + (m.score * 100 | number: '1.0-0') + '%' : '' }}</span>
                    </summary>
                    <p class="mt-1 whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs text-slate-700">{{ ex.description || ex.goal }}</p>
                  </details>
                } @else {
                  <span class="font-semibold text-red-600">✗</span> {{ m.name }} <span class="text-xs text-slate-500">– brak w katalogu</span>
                }
              </li>
            }
          </ul>
        }
      </section>

      <!-- Katalog -->
      <section class="card space-y-3">
        <div class="flex flex-wrap items-center gap-3">
          <h2 class="mr-auto font-semibold">Ćwiczenia ({{ filtered().length }}{{ filtered().length !== items().length ? ' z ' + items().length : '' }})</h2>
          <input class="field !w-56" placeholder="Szukaj nazwy…" [value]="query()" (input)="query.set($any($event.target).value)" aria-label="Szukaj ćwiczenia" />
          <label class="flex items-center gap-1.5 text-xs text-slate-600">
            <input type="checkbox" class="h-4 w-4" [checked]="onlyUnverified()" (change)="onlyUnverified.set(!onlyUnverified())" /> tylko niesprawdzone
          </label>
        </div>
        @if (items().length === 0) {
          <p class="text-sm text-slate-500">Katalog jest pusty – wyodrębnij ćwiczenia z dokumentów powyżej.</p>
        }
        <ul class="divide-y divide-slate-100">
          @for (ex of filtered(); track ex.id) {
            <li class="py-2 text-sm">
              @if (editingId() === ex.id) {
                <div class="space-y-2">
                  <div class="grid gap-2 sm:grid-cols-[1fr_6rem_6rem]">
                    <input class="field" [value]="draft().name" (input)="patch('name', $any($event.target).value)" aria-label="Nazwa" />
                    <input class="field" [value]="draft().number" (input)="patch('number', $any($event.target).value)" aria-label="Numer" placeholder="nr" />
                    <input class="field" type="number" [value]="draft().page ?? ''" (input)="patchPage($any($event.target).value)" aria-label="Strona" placeholder="strona" />
                  </div>
                  <textarea class="field" rows="2" [value]="draft().goal" (input)="patch('goal', $any($event.target).value)" aria-label="Cel" placeholder="Cel"></textarea>
                  <input class="field" [value]="draft().tools" (input)="patch('tools', $any($event.target).value)" aria-label="Narzędzia" placeholder="Narzędzia" />
                  <textarea class="field" rows="5" [value]="draft().description" (input)="patch('description', $any($event.target).value)" aria-label="Opis wykonania" placeholder="Opis wykonania"></textarea>
                  <div class="flex justify-end gap-2">
                    <button type="button" class="btn-secondary" (click)="editingId.set(null)">Anuluj</button>
                    <button type="button" class="btn-primary" [disabled]="busy() || !draft().name.trim()" (click)="save(ex, draft())">Zapisz jako sprawdzone</button>
                  </div>
                </div>
              } @else {
                <div class="flex items-start gap-2">
                  <details class="min-w-0 flex-1">
                    <summary class="cursor-pointer">
                      <span class="font-medium">{{ ex.number ? ex.number + '. ' : '' }}{{ ex.name }}</span>
                      <span class="ml-1 text-xs text-slate-500">{{ ex.document_title }}{{ ex.page ? ', s. ' + ex.page : '' }}</span>
                      @if (ex.verified) { <span class="badge ml-1 bg-emerald-100 text-emerald-800">sprawdzone</span> }
                      @if (!ex.complete) { <span class="badge ml-1 bg-amber-100 text-amber-800">opis może być ucięty</span> }
                    </summary>
                    <dl class="mt-2 space-y-1 rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
                      @if (ex.goal) { <div><dt class="inline font-semibold">Cel: </dt><dd class="inline">{{ ex.goal }}</dd></div> }
                      @if (ex.tools) { <div><dt class="inline font-semibold">Narzędzia: </dt><dd class="inline">{{ ex.tools }}</dd></div> }
                      <div><dt class="font-semibold">Opis wykonania:</dt><dd class="whitespace-pre-wrap">{{ ex.description || '—' }}</dd></div>
                    </dl>
                  </details>
                  @if (!ex.verified) {
                    <button type="button" class="text-xs font-medium text-emerald-700 hover:underline" (click)="save(ex, inputOf(ex))">Sprawdzone</button>
                  }
                  <button type="button" class="text-xs font-medium text-brand-700 hover:underline" (click)="edit(ex)">Edytuj</button>
                  <button type="button" class="text-xs font-medium text-slate-400 hover:text-red-600" (click)="remove(ex)">Usuń</button>
                </div>
              }
            </li>
          }
        </ul>
      </section>
    </div>
  `,
})
export class ExercisesComponent implements OnInit {
  private readonly api = inject(ExercisesService);

  protected readonly candidates = signal<ExerciseCandidate[]>([]);
  protected readonly chosen = signal<Set<number>>(new Set());
  protected readonly job = signal<ExtractionStatus | null>(null);
  protected readonly items = signal<Exercise[]>([]);
  protected readonly matches = signal<ExerciseMatch[]>([]);
  protected readonly matchText = signal('');
  protected readonly query = signal('');
  protected readonly onlyUnverified = signal(false);
  protected readonly editingId = signal<number | null>(null);
  protected readonly draft = signal<ExerciseInput>(this.emptyDraft());
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly running = computed(() => (this.job()?.status === 'running' ? this.job() : null));
  protected readonly matchedCount = computed(() => this.matches().filter((m) => m.exercise).length);
  protected readonly filtered = computed(() => {
    const q = searchKey(this.query().trim());
    return this.items().filter((e) => (!q || searchKey(e.name).includes(q)) && (!this.onlyUnverified() || !e.verified));
  });
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.stopPolling());
  }

  ngOnInit(): void {
    this.loadCandidates(true);
    this.loadItems();
    this.api.status().subscribe({
      next: (s) => {
        this.job.set(s);
        if (s?.status === 'running') {
          this.startPolling();
        }
      },
    });
  }

  protected jobLabel(j: ExtractionStatus): string {
    return { running: 'W toku.', done: 'Zakończono.', failed: 'Przerwano z błędem.', cancelled: 'Zatrzymano.' }[j.status];
  }

  protected toggleDoc(id: number): void {
    const next = new Set(this.chosen());
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    this.chosen.set(next);
  }

  protected extract(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.extract([...this.chosen()]).subscribe({
      next: (s) => {
        this.busy.set(false);
        this.job.set(s);
        this.startPolling();
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.error.set(apiError(err, 'Nie udało się uruchomić wyodrębniania.'));
      },
    });
  }

  protected cancel(): void {
    this.api.cancel().subscribe({ next: (s) => this.job.set(s) });
  }

  protected checkList(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.match(this.matchText()).subscribe({
      next: (m) => {
        this.busy.set(false);
        this.matches.set(m);
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.matches.set([]);
        this.error.set(apiError(err, 'Nie udało się sprawdzić listy.'));
      },
    });
  }

  protected inputOf(ex: Exercise): ExerciseInput {
    return { name: ex.name, number: ex.number, goal: ex.goal, tools: ex.tools, description: ex.description, page: ex.page, verified: true };
  }

  protected edit(ex: Exercise): void {
    this.editingId.set(ex.id);
    this.draft.set(this.inputOf(ex));
  }

  protected patch(key: 'name' | 'number' | 'goal' | 'tools' | 'description', value: string): void {
    this.draft.update((d) => ({ ...d, [key]: value }));
  }

  protected patchPage(value: string): void {
    this.draft.update((d) => ({ ...d, page: value === '' ? null : Number(value) }));
  }

  protected save(ex: Exercise, body: ExerciseInput): void {
    this.busy.set(true);
    this.api.update(ex.id, { ...body, verified: true }).subscribe({
      next: (saved) => {
        this.busy.set(false);
        this.editingId.set(null);
        this.items.update((list) => list.map((e) => (e.id === saved.id ? saved : e)));
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.error.set(apiError(err, 'Nie udało się zapisać ćwiczenia.'));
      },
    });
  }

  protected remove(ex: Exercise): void {
    if (!confirm(`Usunąć ćwiczenie „${ex.name}” z katalogu?`)) {
      return;
    }
    this.api.remove(ex.id).subscribe({ next: () => this.items.update((list) => list.filter((e) => e.id !== ex.id)) });
  }

  private emptyDraft(): ExerciseInput {
    return { name: '', number: '', goal: '', tools: '', description: '', page: null, verified: true };
  }

  private loadCandidates(preselect = false): void {
    this.api.candidates().subscribe({
      next: (list) => {
        this.candidates.set(list);
        if (preselect) {
          // Domyślnie: dokumenty z wyraźnym katalogiem, z których jeszcze nic nie wyodrębniono.
          this.chosen.set(new Set(list.filter((c) => c.markers >= 5 && c.exercises === 0).map((c) => c.document_id)));
        }
      },
    });
  }

  private loadItems(): void {
    this.api.list().subscribe({ next: (items) => this.items.set(items) });
  }

  private poll(): void {
    this.api.status().subscribe({
      next: (s) => {
        this.job.set(s);
        if (s?.status !== 'running') {
          this.stopPolling();
          this.loadItems();
          this.loadCandidates();
        }
      },
    });
  }

  private startPolling(): void {
    if (this.timer === null) {
      this.timer = setInterval(() => this.poll(), POLL_MS);
    }
  }

  private stopPolling(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}
