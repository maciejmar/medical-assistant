import { DatePipe, DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AdminService } from '../../core/admin.service';
import { LlmCallDetail, LlmCallSummary, LlmMessage } from '../../shared/models';

const PAGE_SIZE = 50;

const OPERATIONS = [
  { value: '', label: 'Wszystkie operacje' },
  { value: 'chat_rag', label: 'Odpowiedź asystenta (chat_rag)' },
  { value: 'query_rewriting', label: 'Przepisanie zapytania' },
  { value: 'embedding_query', label: 'Embedding zapytania' },
  { value: 'seed_embedding', label: 'Embedding bazy wiedzy' },
];

@Component({
  selector: 'app-llm-logs',
  standalone: true,
  imports: [DatePipe, DecimalPipe, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="mb-6 flex flex-wrap items-center justify-between gap-3">
      <div>
        <a routerLink="/admin" class="mb-1 inline-block text-sm text-brand-700 hover:underline">← Panel administratora</a>
        <h1 class="text-2xl font-bold">Log zapytań LLM</h1>
        <p class="text-sm text-slate-500">Pełna treść wysłana do modelu i otrzymana odpowiedź ({{ total() | number }} wpisów).</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <select class="field !w-auto" aria-label="Operacja" [value]="operation()" (change)="setOperation($any($event.target).value)">
          @for (o of operations; track o.value) {
            <option [value]="o.value">{{ o.label }}</option>
          }
        </select>
        <select class="field !w-auto" aria-label="Status" [value]="status()" (change)="setStatus($any($event.target).value)">
          <option value="">Każdy status</option>
          <option value="ok">OK</option>
          <option value="error">Błąd</option>
        </select>
        <button type="button" class="btn-secondary" (click)="load()">Odśwież</button>
      </div>
    </div>

    @if (error()) {
      <div class="card mb-4 text-sm text-red-700">{{ error() }}</div>
    }

    <div class="grid gap-6 lg:grid-cols-5">
      <section class="card lg:col-span-2">
        @if (items().length === 0) {
          <p class="text-sm text-slate-500">{{ loading() ? 'Ładowanie…' : 'Brak wpisów.' }}</p>
        }
        <ul class="divide-y divide-slate-100">
          @for (c of items(); track c.id) {
            <li>
              <button
                type="button"
                class="w-full rounded-lg px-2 py-2 text-left hover:bg-slate-50"
                [class.bg-brand-50]="selected()?.id === c.id"
                (click)="open(c)"
              >
                <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span>{{ c.timestamp | date: 'dd.MM.yyyy HH:mm:ss' }}</span>
                  <span class="badge bg-slate-100 text-slate-700">{{ c.operation }}</span>
                  @if (c.status === 'error') {
                    <span class="badge bg-red-100 text-red-700">błąd</span>
                  }
                  <span class="ml-auto">{{ c.total_tokens | number }} tok. · {{ c.duration_ms | number }} ms</span>
                </div>
                <p class="mt-1 line-clamp-2 text-sm">{{ c.preview || '—' }}</p>
                <p class="text-xs text-slate-400">{{ c.user_email ?? 'system' }}</p>
              </button>
            </li>
          }
        </ul>
        <div class="mt-3 flex items-center justify-between text-sm">
          <button type="button" class="btn-secondary !px-2 !py-1" [disabled]="offset() === 0" (click)="page(-1)">← Nowsze</button>
          <span class="text-slate-500">{{ offset() + 1 }}–{{ offset() + items().length }} z {{ total() }}</span>
          <button type="button" class="btn-secondary !px-2 !py-1" [disabled]="offset() + items().length >= total()" (click)="page(1)">Starsze →</button>
        </div>
      </section>

      <section class="card lg:col-span-3">
        @if (selected(); as d) {
          <div class="mb-4 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span class="font-mono">#{{ d.id }}</span>
            <span>{{ d.timestamp | date: 'dd.MM.yyyy HH:mm:ss' }}</span>
            <span class="badge bg-slate-100 text-slate-700">{{ d.operation }}</span>
            <span>{{ d.model_name }}</span>
            <span>{{ d.user_email ?? 'system' }}</span>
            <span class="ml-auto">
              prompt {{ d.prompt_tokens | number }} · odpowiedź {{ d.completion_tokens | number }} · {{ d.duration_ms | number }} ms
            </span>
          </div>

          @if (d.error) {
            <div class="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{{ d.error }}</div>
          }

          <h2 class="mb-2 font-semibold">Wysłano do LLM</h2>
          <div class="mb-6 space-y-3">
            @for (m of messages(); track $index) {
              <div class="rounded-lg border border-slate-200">
                <div class="border-b border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold uppercase text-slate-500">{{ m.role }}</div>
                <pre class="max-h-96 overflow-auto whitespace-pre-wrap break-words px-3 py-2 text-xs">{{ m.content }}</pre>
              </div>
            }
          </div>

          <h2 class="mb-2 font-semibold">Odpowiedź</h2>
          <pre class="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-xs">{{ d.response || '—' }}</pre>
        } @else {
          <p class="text-sm text-slate-500">Wybierz wpis z listy, aby zobaczyć szczegóły.</p>
        }
      </section>
    </div>
  `,
})
export class LlmLogsComponent {
  private readonly api = inject(AdminService);

  protected readonly operations = OPERATIONS;
  protected readonly items = signal<LlmCallSummary[]>([]);
  protected readonly total = signal(0);
  protected readonly offset = signal(0);
  protected readonly operation = signal('');
  protected readonly status = signal('');
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly selected = signal<LlmCallDetail | null>(null);

  /** Embeddingi mają format { input: [...] } – pokazujemy je jak wiadomości. */
  protected readonly messages = computed<LlmMessage[]>(() => {
    const request = this.selected()?.request;
    if (!request) {
      return [];
    }
    if (Array.isArray(request)) {
      return request;
    }
    return (request.input ?? []).map((text, i) => ({ role: `input ${i + 1}`, content: text }));
  });

  constructor() {
    this.load();
  }

  protected load(): void {
    this.loading.set(true);
    this.api
      .llmCalls({
        operation: this.operation() || undefined,
        status_filter: this.status() || undefined,
        limit: PAGE_SIZE,
        offset: this.offset(),
      })
      .subscribe({
        next: (page) => {
          this.items.set(page.items);
          this.total.set(page.total);
          this.loading.set(false);
          this.error.set(null);
        },
        error: () => {
          this.loading.set(false);
          this.error.set('Nie udało się pobrać logu zapytań.');
        },
      });
  }

  protected setOperation(value: string): void {
    this.operation.set(value);
    this.offset.set(0);
    this.load();
  }

  protected setStatus(value: string): void {
    this.status.set(value);
    this.offset.set(0);
    this.load();
  }

  protected page(direction: 1 | -1): void {
    this.offset.set(Math.max(0, this.offset() + direction * PAGE_SIZE));
    this.load();
  }

  protected open(call: LlmCallSummary): void {
    this.api.llmCall(call.id).subscribe({
      next: (detail) => this.selected.set(detail),
      error: () => this.error.set('Nie udało się pobrać szczegółów wywołania.'),
    });
  }
}
