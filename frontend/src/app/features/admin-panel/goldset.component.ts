import { DatePipe, DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import {
  GoldsetItem,
  GoldsetItemInput,
  GoldsetResult,
  GoldsetRun,
  GoldsetRunDetail,
  GoldsetService,
} from '../../core/goldset.service';
import { IconComponent } from '../../shared/icon.component';
import { MarkdownPipe } from '../../shared/markdown.pipe';

const POLL_MS = 3000;

function apiError(err: unknown, fallback: string): string {
  if (err instanceof HttpErrorResponse && typeof err.error?.detail === 'string') {
    return err.error.detail;
  }
  return fallback;
}

/** Ocena 0–5 → poziom (zawsze z liczbą i etykietą, kolor tylko pomocniczo). */
export function scoreLevel(score: number): { label: string; css: string } {
  if (score >= 4) {
    return { label: 'dobra', css: 'bg-emerald-100 text-emerald-800' };
  }
  if (score >= 2.5) {
    return { label: 'częściowa', css: 'bg-amber-100 text-amber-800' };
  }
  return { label: 'słaba', css: 'bg-red-100 text-red-800' };
}

/**
 * Testy jakości asystenta: goldset (pytania + odpowiedzi wzorcowe, import z tekstu), uruchamianie
 * testu przez prawdziwy RAG, ocena LLM-sędziego, historia przebiegów i porównanie dwóch przebiegów.
 */
@Component({
  selector: 'app-goldset',
  standalone: true,
  imports: [DatePipe, DecimalPipe, IconComponent, MarkdownPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="space-y-6">
      <div>
        <h1 class="text-2xl font-bold">Testy jakości asystenta</h1>
        <p class="text-sm text-slate-500">
          Goldset to pytania z odpowiedziami wzorcowymi. Test zadaje je asystentowi tak jak lekarz (ta sama baza wiedzy i ustawienia),
          a model-sędzia ocenia zgodność z wzorcem w skali 0–5. Goldset nie trafia do bazy wiedzy.
        </p>
      </div>

      @if (error(); as e) {
        <p class="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ e }}</p>
      }

      <!-- Uruchomienie -->
      <section class="card space-y-3">
        <div class="flex flex-wrap items-end gap-3">
          <div class="min-w-[14rem] flex-1">
            <label class="label" for="run-note">Notatka do przebiegu (np. co zmieniono)</label>
            <input id="run-note" class="field" maxlength="300" [value]="note()" (input)="note.set($any($event.target).value)" placeholder="np. po dodaniu materiałów o miofunkcjach" />
          </div>
          <button type="button" class="btn-primary" [disabled]="!!running() || items().length === 0 || busy()" (click)="start()">
            Uruchom test ({{ items().length }} pytań)
          </button>
        </div>
        @if (running(); as r) {
          <div role="status" aria-live="polite">
            <div class="mb-1 flex justify-between text-xs text-slate-600">
              <span>Przebieg #{{ r.id }} – pytanie {{ r.done }} z {{ r.total }}…</span>
              <button type="button" class="font-medium text-red-600 hover:underline" (click)="cancel(r)">Zatrzymaj</button>
            </div>
            <div class="h-2 overflow-hidden rounded-full bg-slate-200">
              <div class="h-full rounded-full bg-brand-500 transition-all" [style.width.%]="r.total ? (100 * r.done) / r.total : 0"></div>
            </div>
          </div>
        }
        <p class="text-xs text-slate-500">Jedno pytanie to ok. 10–30 s (odpowiedź asystenta + ocena). Koszt liczony jest w Twoich kredytach.</p>
      </section>

      <!-- Historia -->
      @if (runs().length > 0) {
        <section class="card">
          <h2 class="mb-3 font-semibold">Historia przebiegów</h2>
          <div class="overflow-x-auto">
            <table class="w-full min-w-[44rem] text-sm">
              <thead>
                <tr class="text-left text-xs uppercase text-slate-500">
                  <th class="pb-2">#</th><th class="pb-2">Data</th><th class="pb-2">Notatka</th><th class="pb-2">Wynik</th>
                  <th class="pb-2">Podobieństwo</th><th class="pb-2">Czas śr.</th><th class="pb-2">Tokeny</th><th class="pb-2">Model</th><th></th>
                </tr>
              </thead>
              <tbody>
                @for (r of runs(); track r.id) {
                  <tr class="cursor-pointer border-t border-slate-100 hover:bg-slate-50" [class.bg-brand-50]="selected()?.run?.id === r.id" (click)="open(r.id)">
                    <td class="py-2 font-medium">{{ r.id }}</td>
                    <td class="py-2 text-xs">{{ r.started_at | date: 'dd.MM.yyyy HH:mm' }}</td>
                    <td class="max-w-[14rem] truncate py-2 text-xs" [title]="r.note">{{ r.note || '—' }}</td>
                    <td class="py-2">
                      @if (r.avg_score !== null) {
                        <span class="inline-flex items-center gap-2">
                          <span class="font-semibold tabular-nums">{{ r.avg_score | number: '1.1-1' }}/5</span>
                          <span class="h-1.5 w-16 overflow-hidden rounded-full bg-slate-200"><span class="block h-full rounded-full bg-brand-500" [style.width.%]="r.avg_score * 20"></span></span>
                        </span>
                      } @else {
                        <span class="text-xs text-slate-500">{{ statusLabel(r) }}</span>
                      }
                    </td>
                    <td class="py-2 tabular-nums">{{ r.avg_similarity !== null ? (r.avg_similarity * 100 | number: '1.0-0') + '%' : '—' }}</td>
                    <td class="py-2 tabular-nums">{{ r.avg_latency_ms !== null ? (r.avg_latency_ms / 1000 | number: '1.0-1') + ' s' : '—' }}</td>
                    <td class="py-2 tabular-nums">{{ r.total_tokens | number }}</td>
                    <td class="py-2 text-xs text-slate-500">{{ r.settings['chat_model'] }}</td>
                    <td class="py-2 text-right">
                      @if (r.status !== 'running') {
                        <button type="button" class="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600" (click)="$event.stopPropagation(); removeRun(r)" [attr.aria-label]="'Usuń przebieg ' + r.id"><app-icon name="trash" [size]="13" /></button>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      }

      <!-- Wyniki -->
      @if (selected(); as d) {
        <section class="card space-y-3">
          <div class="flex flex-wrap items-center gap-3">
            <h2 class="mr-auto font-semibold">Wyniki przebiegu #{{ d.run.id }} <span class="text-sm font-normal text-slate-500">(najsłabsze na górze)</span></h2>
            <label class="flex items-center gap-2 text-xs text-slate-600">
              Porównaj z
              <select class="field !w-auto !py-1 !text-xs" (change)="compareWith($any($event.target).value)">
                <option value="">—</option>
                @for (r of runs(); track r.id) {
                  @if (r.id !== d.run.id && r.status !== 'running') {
                    <option [value]="r.id">#{{ r.id }} ({{ r.avg_score !== null ? (r.avg_score | number: '1.1-1') : '—' }})</option>
                  }
                }
              </select>
            </label>
          </div>
          <ul class="divide-y divide-slate-100">
            @for (res of d.results; track res.id) {
              <li class="py-2">
                <button type="button" class="flex w-full flex-wrap items-center gap-3 text-left" (click)="toggle(res.id)" [attr.aria-expanded]="expanded() === res.id">
                  @if (res.status === 'ok') {
                    <span class="badge tabular-nums" [class]="level(res.score).css">{{ res.score | number: '1.0-1' }}/5 · {{ level(res.score).label }}</span>
                  } @else {
                    <span class="badge bg-slate-200 text-slate-700">błąd</span>
                  }
                  @if (delta(res); as dl) {
                    <span class="text-xs font-semibold" [class]="dl > 0 ? 'text-emerald-700' : dl < 0 ? 'text-red-700' : 'text-slate-500'">{{ dl > 0 ? '▲ +' : dl < 0 ? '▼ ' : '= ' }}{{ dl | number: '1.0-1' }}</span>
                  }
                  <span class="min-w-0 flex-1 truncate font-medium text-slate-800">{{ res.title }}</span>
                  <span class="text-xs tabular-nums text-slate-500">podob. {{ res.similarity * 100 | number: '1.0-0' }}% · {{ res.latency_ms / 1000 | number: '1.0-1' }} s</span>
                </button>
                @if (expanded() === res.id) {
                  <div class="mt-3 space-y-3 rounded-lg bg-slate-50 p-3 text-sm">
                    <p class="whitespace-pre-wrap text-slate-700"><span class="font-semibold">Pytanie:</span> {{ res.question }}</p>
                    @if (res.error) { <p class="text-red-700">{{ res.error }}</p> }
                    @if (res.verdict.comment) {
                      <p><span class="font-semibold">Ocena sędziego:</span> {{ res.verdict.comment }}
                        @if (res.verdict.order_ok === false) { <span class="badge ml-1 bg-amber-100 text-amber-800">zła kolejność kroków</span> }
                      </p>
                    }
                    <div class="flex flex-wrap gap-1">
                      @for (m of res.verdict.missing ?? []; track m) { <span class="badge bg-red-50 text-red-700">brak: {{ m }}</span> }
                      @for (e of res.verdict.errors ?? []; track e) { <span class="badge bg-red-100 text-red-800">błąd: {{ e }}</span> }
                      @for (c of res.verdict.covered ?? []; track c) { <span class="badge bg-emerald-50 text-emerald-700">✓ {{ c }}</span> }
                    </div>
                    <div class="grid gap-3 lg:grid-cols-2">
                      <div class="rounded-lg border border-slate-200 bg-white p-3">
                        <h3 class="mb-1 text-xs font-semibold uppercase text-slate-500">Odpowiedź asystenta</h3>
                        <div class="md" [innerHTML]="res.answer | markdown"></div>
                        @if (res.sources.length) {
                          <p class="mt-2 text-xs text-slate-500">Źródła: @for (s of res.sources; track s.index) {[{{ s.index }}] {{ s.title }}; }</p>
                        }
                      </div>
                      <div class="rounded-lg border border-emerald-200 bg-emerald-50/40 p-3">
                        <h3 class="mb-1 text-xs font-semibold uppercase text-emerald-800">Odpowiedź wzorcowa</h3>
                        <p class="whitespace-pre-wrap">{{ reference(res) }}</p>
                      </div>
                    </div>
                  </div>
                }
              </li>
            }
          </ul>
        </section>
      }

      <!-- Goldset -->
      <section class="card space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="font-semibold">Goldset ({{ items().length }} pytań)</h2>
          <button type="button" class="btn-secondary" (click)="showImport.set(!showImport())">{{ showImport() ? 'Zamknij import' : 'Importuj z tekstu' }}</button>
        </div>

        @if (showImport()) {
          <div class="space-y-2 rounded-lg border border-dashed border-slate-300 p-3">
            <p class="text-xs text-slate-500">
              Wklej tekst: najpierw pytania („1. Tytuł” + treść), potem odpowiedzi wzorcowe („1. Tytuł” + kroki). Po przetworzeniu
              sprawdź podgląd – zapis zastępuje obecny goldset (historia wyników zostaje).
            </p>
            <textarea class="field font-mono text-xs" rows="10" [value]="importText()" (input)="importText.set($any($event.target).value)" aria-label="Tekst goldsetu"></textarea>
            <div class="flex flex-wrap gap-2">
              <button type="button" class="btn-secondary" [disabled]="busy() || !importText().trim()" (click)="parse()">Przetwórz</button>
              @if (preview().length) {
                <button type="button" class="btn-primary" [disabled]="busy()" (click)="saveImport()">Zapisz goldset ({{ preview().length }} pytań)</button>
              }
            </div>
            @for (p of preview(); track i; let i = $index) {
              <details class="rounded-lg bg-slate-50 p-2 text-sm">
                <summary class="cursor-pointer font-medium">{{ i + 1 }}. {{ p.title }}</summary>
                <p class="mt-2 whitespace-pre-wrap text-slate-700">{{ p.question }}</p>
                <p class="mt-2 whitespace-pre-wrap rounded bg-emerald-50 p-2 text-emerald-900">{{ p.reference_answer }}</p>
              </details>
            }
          </div>
        }

        <ul class="divide-y divide-slate-100">
          @for (item of items(); track item.id; let i = $index) {
            <li class="py-2">
              @if (editingId() === item.id) {
                <div class="space-y-2">
                  <input class="field" [value]="draft().title" (input)="patchDraft('title', $any($event.target).value)" aria-label="Tytuł" />
                  <textarea class="field" rows="4" [value]="draft().question" (input)="patchDraft('question', $any($event.target).value)" aria-label="Pytanie"></textarea>
                  <textarea class="field" rows="6" [value]="draft().reference_answer" (input)="patchDraft('reference_answer', $any($event.target).value)" aria-label="Odpowiedź wzorcowa"></textarea>
                  <div class="flex justify-end gap-2">
                    <button type="button" class="btn-secondary" (click)="editingId.set(null)">Anuluj</button>
                    <button type="button" class="btn-primary" [disabled]="busy()" (click)="saveItem(item)">Zapisz</button>
                  </div>
                </div>
              } @else {
                <div class="flex items-start gap-2">
                  <details class="min-w-0 flex-1 text-sm">
                    <summary class="cursor-pointer font-medium">{{ i + 1 }}. {{ item.title }}</summary>
                    <p class="mt-2 whitespace-pre-wrap text-slate-700">{{ item.question }}</p>
                    <p class="mt-2 whitespace-pre-wrap rounded bg-emerald-50 p-2 text-emerald-900">{{ item.reference_answer }}</p>
                  </details>
                  <button type="button" class="text-xs font-medium text-brand-700 hover:underline" (click)="edit(item)">Edytuj</button>
                  <button type="button" class="text-xs font-medium text-slate-400 hover:text-red-600" (click)="removeItem(item)">Usuń</button>
                </div>
              }
            </li>
          }
        </ul>
      </section>
    </div>
  `,
})
export class GoldsetComponent implements OnInit {
  private readonly api = inject(GoldsetService);

  protected readonly items = signal<GoldsetItem[]>([]);
  protected readonly runs = signal<GoldsetRun[]>([]);
  protected readonly selected = signal<GoldsetRunDetail | null>(null);
  protected readonly compared = signal<GoldsetRunDetail | null>(null);
  protected readonly expanded = signal<number | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly note = signal('');
  protected readonly showImport = signal(false);
  protected readonly importText = signal('');
  protected readonly preview = signal<GoldsetItemInput[]>([]);
  protected readonly editingId = signal<number | null>(null);
  protected readonly draft = signal<GoldsetItemInput>({ title: '', question: '', reference_answer: '' });
  protected readonly running = computed(() => this.runs().find((r) => r.status === 'running') ?? null);
  private readonly referenceById = computed(() => new Map(this.items().map((i) => [i.id, i.reference_answer])));
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.stopPolling());
  }

  ngOnInit(): void {
    this.api.items().subscribe({ next: (i) => this.items.set(i) });
    this.loadRuns(true);
  }

  protected level(score: number) {
    return scoreLevel(score);
  }

  protected statusLabel(r: GoldsetRun): string {
    return { running: 'w toku', done: 'brak wyników', failed: 'przerwany', cancelled: 'zatrzymany' }[r.status];
  }

  protected reference(res: GoldsetResult): string {
    return (res.item_id !== null && this.referenceById().get(res.item_id)) || '(pytanie usunięte z goldsetu)';
  }

  protected delta(res: GoldsetResult): number | null {
    const other = this.compared()?.results.find((r) => (res.item_id !== null && r.item_id === res.item_id) || r.title === res.title);
    return other && other.status === 'ok' && res.status === 'ok' ? res.score - other.score : null;
  }

  protected toggle(id: number): void {
    this.expanded.set(this.expanded() === id ? null : id);
  }

  protected start(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.startRun(this.note().trim()).subscribe({
      next: (run) => {
        this.busy.set(false);
        this.note.set('');
        this.runs.update((list) => [run, ...list]);
        this.startPolling();
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.error.set(apiError(err, 'Nie udało się uruchomić testu.'));
      },
    });
  }

  protected cancel(run: GoldsetRun): void {
    this.api.cancelRun(run.id).subscribe({ next: () => this.loadRuns() });
  }

  protected open(id: number): void {
    this.compared.set(null);
    this.expanded.set(null);
    this.api.run(id).subscribe({ next: (d) => this.selected.set(d) });
  }

  protected compareWith(value: string): void {
    if (!value) {
      this.compared.set(null);
      return;
    }
    this.api.run(Number(value)).subscribe({ next: (d) => this.compared.set(d) });
  }

  protected removeRun(run: GoldsetRun): void {
    if (!confirm(`Usunąć przebieg #${run.id} wraz z wynikami?`)) {
      return;
    }
    this.api.deleteRun(run.id).subscribe({
      next: () => {
        if (this.selected()?.run.id === run.id) {
          this.selected.set(null);
        }
        this.loadRuns();
      },
    });
  }

  protected parse(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.parse(this.importText()).subscribe({
      next: (items) => {
        this.busy.set(false);
        this.preview.set(items);
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.preview.set([]);
        this.error.set(apiError(err, 'Nie udało się przetworzyć tekstu.'));
      },
    });
  }

  protected saveImport(): void {
    if (this.items().length && !confirm(`Zastąpić obecny goldset (${this.items().length} pytań) nowym (${this.preview().length})?`)) {
      return;
    }
    this.busy.set(true);
    this.api.replace(this.preview()).subscribe({
      next: (items) => {
        this.busy.set(false);
        this.items.set(items);
        this.preview.set([]);
        this.importText.set('');
        this.showImport.set(false);
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.error.set(apiError(err, 'Nie udało się zapisać goldsetu.'));
      },
    });
  }

  protected edit(item: GoldsetItem): void {
    this.editingId.set(item.id);
    this.draft.set({ title: item.title, question: item.question, reference_answer: item.reference_answer });
  }

  protected patchDraft(key: keyof GoldsetItemInput, value: string): void {
    this.draft.update((d) => ({ ...d, [key]: value }));
  }

  protected saveItem(item: GoldsetItem): void {
    this.busy.set(true);
    this.api.update(item.id, this.draft()).subscribe({
      next: (saved) => {
        this.busy.set(false);
        this.editingId.set(null);
        this.items.update((list) => list.map((i) => (i.id === saved.id ? saved : i)));
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.error.set(apiError(err, 'Nie udało się zapisać pytania.'));
      },
    });
  }

  protected removeItem(item: GoldsetItem): void {
    if (!confirm(`Usunąć pytanie „${item.title}” z goldsetu?`)) {
      return;
    }
    this.api.remove(item.id).subscribe({ next: () => this.items.update((list) => list.filter((i) => i.id !== item.id)) });
  }

  private loadRuns(openLatest = false): void {
    this.api.runs().subscribe({
      next: (runs) => {
        const wasRunning = this.running();
        this.runs.set(runs);
        const running = this.running();
        if (running) {
          this.startPolling();
        } else {
          this.stopPolling();
        }
        const finished = wasRunning && !running ? runs.find((r) => r.id === wasRunning.id) : null;
        if (finished || (openLatest && runs[0] && !running)) {
          this.open((finished ?? runs[0]).id);
        }
      },
    });
  }

  private startPolling(): void {
    if (this.timer === null) {
      this.timer = setInterval(() => this.loadRuns(), POLL_MS);
    }
  }

  private stopPolling(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}
