import { DecimalPipe } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';

export interface SearchRow {
  id: string;
  title: string;
  document_id: number | null;
  snippet: string;
  score: number;
  dense_rank: number | null;
  sparse_rank: number | null;
  fusion_rank: number | null;
  candidate: boolean;
  selected: boolean;
}

export interface SearchTestResult {
  question: string;
  rewritten_query: string;
  filters: Record<string, string>;
  top_k: number;
  top_n: number;
  min_score: number;
  rows: SearchRow[];
  focus: { document_id: number; title: string; chunks: number; best_score: number | null; verdict: string } | null;
}

/**
 * „Sprawdź wyszukiwanie”: odtwarza etapy czatu dla pytania (przepisanie → kandydaci → rerank)
 * i pokazuje, na którym etapie fragment odpada. Wskazany dokument jest oceniany w całości,
 * także fragmenty spoza puli kandydatów.
 */
@Component({
  selector: 'app-search-test',
  standalone: true,
  imports: [DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="card space-y-3">
      <div>
        <h2 class="font-semibold">Sprawdź wyszukiwanie</h2>
        <p class="text-xs text-slate-500">
          Wpisz pytanie jak w czacie i opcjonalnie wskaż dokument, którego brakuje w źródłach. Zobaczysz, jak asystent
          przepisał pytanie, które fragmenty weszły do kandydatów i jak ocenił je reranker.
        </p>
      </div>
      <div class="grid gap-2 sm:grid-cols-[1fr_16rem_auto]">
        <input id="st-question" class="field" placeholder="np. jak wygląda przygotowanie do zabiegu korekty wędzidełka?"
               [value]="question()" (input)="question.set($any($event.target).value)" (keydown.enter)="run()" />
        <select id="st-doc" class="field" aria-label="Sprawdzany dokument" (change)="documentId.set(+$any($event.target).value || null)">
          <option value="">— bez wskazania dokumentu —</option>
          @for (d of documents(); track d.id) {
            <option [value]="d.id">{{ d.title }}</option>
          }
        </select>
        <button type="button" class="btn-primary" [disabled]="busy() || question().trim().length < 3" (click)="run()">
          {{ busy() ? 'Sprawdzam…' : 'Sprawdź' }}
        </button>
      </div>

      @if (error(); as e) {
        <p class="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ e }}</p>
      }

      @if (result(); as r) {
        <div class="space-y-1 rounded-lg bg-slate-50 p-3 text-sm">
          <p><span class="text-slate-500">Zapytanie po przepisaniu:</span> <span class="font-medium">{{ r.rewritten_query }}</span></p>
          @if (filterText(); as f) {
            <p class="text-xs text-slate-500">Filtry (wzmacniają, nie wykluczają): {{ f }}</p>
          }
          <p class="text-xs text-slate-500">
            Kandydaci: {{ r.top_k }} najlepszych z wyszukiwania · do źródeł trafia do {{ r.top_n }} z oceną ≥ {{ r.min_score }}
          </p>
        </div>

        @if (r.focus; as f) {
          <div class="rounded-lg border p-3 text-sm" [class]="focusSelected() ? 'border-emerald-300 bg-emerald-50' : 'border-amber-300 bg-amber-50'">
            <p class="font-semibold">{{ f.title }} · {{ f.chunks }} fragm.</p>
            <p>{{ f.verdict }}</p>
          </div>
        }

        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="text-slate-500">
              <tr>
                <th class="py-1 pr-2">Fragment</th>
                <th class="px-2" title="Ocena rerankera 0–1">Ocena</th>
                <th class="px-2" title="Miejsce w wyszukiwaniu znaczeniowym (wektory)">Znacz.</th>
                <th class="px-2" title="Miejsce w wyszukiwaniu po słowach">Słowa</th>
                <th class="px-2" title="Miejsce po połączeniu obu (RRF)">Razem</th>
                <th class="pl-2">Etap</th>
              </tr>
            </thead>
            <tbody>
              @for (row of shown(); track row.id) {
                <tr class="border-t border-slate-100 align-top" [class.bg-amber-50]="row.document_id !== null && row.document_id === r.focus?.document_id">
                  <td class="py-1 pr-2">
                    <span class="font-medium">{{ row.title }}</span>
                    <span class="block text-slate-500">{{ row.snippet }}…</span>
                  </td>
                  <td class="px-2 tabular-nums">{{ row.score | number: '1.3-3' }}</td>
                  <td class="px-2 tabular-nums">{{ row.dense_rank ?? '—' }}</td>
                  <td class="px-2 tabular-nums">{{ row.sparse_rank ?? '—' }}</td>
                  <td class="px-2 tabular-nums">{{ row.fusion_rank ?? '—' }}</td>
                  <td class="whitespace-nowrap pl-2">
                    @if (row.selected) {
                      <span class="badge bg-emerald-100 text-emerald-800">źródło</span>
                    } @else if (row.candidate) {
                      <span class="badge bg-slate-100 text-slate-600">kandydat, odrzucony</span>
                    } @else {
                      <span class="badge bg-red-50 text-red-700">poza kandydatami</span>
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
        @if (r.rows.length > shown().length) {
          <button type="button" class="text-xs font-medium text-brand-700 hover:underline" (click)="showAll.set(true)">
            Pokaż wszystkie ({{ r.rows.length }})
          </button>
        }
      }
    </section>
  `,
})
export class SearchTestComponent {
  private readonly http = inject(HttpClient);

  readonly documents = input<{ id: number; title: string }[]>([]);

  protected readonly question = signal('');
  protected readonly documentId = signal<number | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly result = signal<SearchTestResult | null>(null);
  protected readonly showAll = signal(false);

  /** Domyślnie: kandydaci + fragmenty wskazanego dokumentu; „Pokaż wszystkie” – cała pula. */
  protected readonly shown = computed(() => {
    const r = this.result();
    if (!r) return [];
    if (this.showAll()) return r.rows;
    const focus = r.focus?.document_id;
    return r.rows.filter((row) => row.candidate || (focus != null && row.document_id === focus));
  });
  protected readonly focusSelected = computed(() => {
    const r = this.result();
    return !!r?.focus && r.rows.some((row) => row.selected && row.document_id === r.focus!.document_id);
  });
  protected readonly filterText = computed(() =>
    Object.entries(this.result()?.filters ?? {})
      .map(([k, v]) => `${k}: ${v}`)
      .join(', '),
  );

  protected run(): void {
    const question = this.question().trim();
    if (question.length < 3 || this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    this.showAll.set(false);
    this.http
      .post<SearchTestResult>('/api/admin/knowledge/search-test', { question, document_id: this.documentId() })
      .subscribe({
        next: (r) => {
          this.busy.set(false);
          this.result.set(r);
        },
        error: (err: unknown) => {
          this.busy.set(false);
          const detail = err instanceof HttpErrorResponse ? err.error?.detail : null;
          this.error.set(typeof detail === 'string' ? detail : 'Nie udało się sprawdzić wyszukiwania.');
        },
      });
  }
}
