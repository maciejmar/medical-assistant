import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { BillingService, EXHAUSTED_MESSAGE } from '../../core/billing.service';
import { ChatService } from '../../core/chat.service';
import { MarkdownPipe } from '../../shared/markdown.pipe';
import { PatientsService } from '../../core/patients.service';
import { PromptTemplate, TemplatesService } from '../../core/templates.service';
import {
  ChatEvent,
  ChatSource,
  ConversationSummary,
  Patient,
  TokenCounter,
} from '../../shared/models';

interface UiMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  sources: ChatSource[];
  tokens: number;
  pending: boolean;
  failed: boolean;
  templateName?: string | null;
}

/** Treść pytania wysyłanego z pastylką: nazwa szablonu + opcjonalne uwagi lekarza. */
export function templateQuestion(template: Pick<PromptTemplate, 'name'>, notes: string): string {
  const base = `Przygotuj plan: ${template.name}`;
  return notes.trim() ? `${base}\nUwagi lekarza: ${notes.trim()}` : base;
}

const STAGE_LABELS: Record<string, string> = {
  rewrite: 'Optymalizuję zapytanie…',
  retrieve: 'Przeszukuję bazę wiedzy…',
  rerank: 'Wybieram najtrafniejsze źródła…',
  generate: 'Generuję odpowiedź…',
};

const EMPTY_USAGE: TokenCounter = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [FormsModule, DatePipe, MarkdownPipe, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="assistant-page">
    <div class="page-bg-assistant"></div>
    <div class="grid gap-4 lg:grid-cols-[16rem_1fr]">
      <aside class="card h-fit lg:sticky lg:top-20">
        <button type="button" class="btn-primary mb-3 w-full" (click)="newConversation()">Nowa rozmowa</button>
        <h2 class="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Historia</h2>
        @if (conversations().length === 0) {
          <p class="text-sm text-slate-500">Brak zapisanych rozmów.</p>
        }
        <ul class="max-h-64 space-y-1 overflow-y-auto lg:max-h-[60vh]">
          @for (c of conversations(); track c.conversation_id) {
            <li class="group flex items-center gap-1">
              <button
                type="button"
                class="min-w-0 flex-1 rounded-lg px-2 py-2 text-left text-sm hover:bg-slate-100"
                [class.bg-brand-50]="c.conversation_id === conversationId()"
                (click)="open(c)"
              >
                <span class="block truncate">{{ c.title }}</span>
                <span class="block text-[11px] text-slate-400">{{ c.updated_at | date: 'dd.MM HH:mm' }}</span>
              </button>
              <button type="button" class="rounded p-1 text-slate-400 hover:text-red-600" aria-label="Usuń rozmowę" (click)="remove(c)">✕</button>
            </li>
          }
        </ul>
      </aside>

      <section class="card flex min-h-[70vh] flex-col !p-0">
        @if (billing.mine()?.status?.exhausted) {
          <p class="rounded-t-xl border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900" role="status">
            {{ exhaustedMessage }} <a routerLink="/kredyty" class="font-semibold underline">Dokup kredyty</a>
          </p>
        }
        <div class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div class="flex items-center gap-2">
            <label class="text-xs font-semibold uppercase text-slate-500" for="patient">Pacjent</label>
            <select
              id="patient"
              class="field !w-auto"
              [class.!border-red-400]="needsPatient()"
              [class.ring-2]="needsPatient()"
              [class.ring-red-200]="needsPatient()"
              [attr.aria-invalid]="needsPatient()"
              [ngModel]="patientId()"
              (ngModelChange)="patientId.set($event)"
              [disabled]="streaming()"
            >
              <option [ngValue]="null">— bez kontekstu pacjenta —</option>
              @for (p of patients(); track p.id) {
                <option [ngValue]="p.id">{{ p.last_name }} {{ p.first_name }}</option>
              }
            </select>
          </div>
          <div class="flex items-center gap-2 text-xs" aria-live="polite">
            <span class="badge bg-brand-50 text-brand-700">Tokeny w sesji: {{ sessionUsage().total_tokens }}</span>
            <span class="badge bg-slate-100 text-slate-600">↑ {{ sessionUsage().prompt_tokens }} · ↓ {{ sessionUsage().completion_tokens }}</span>
          </div>
        </div>

        <div #scroller class="flex-1 space-y-4 overflow-y-auto px-4 py-4">
          @if (messages().length === 0) {
            <div class="mx-auto mt-10 max-w-md text-center text-sm text-slate-500">
              <p class="mb-2 text-base font-semibold text-slate-700">W czym mogę pomóc?</p>
              <p>Zapytaj o techniki terapeutyczne, kody ICD, normy rozwoju mowy lub diagnostykę różnicową.</p>
              <div class="mt-4 flex flex-wrap justify-center gap-2">
                @for (s of suggestions; track s) {
                  <button type="button" class="btn-secondary !px-3 !py-1.5 !text-xs" (click)="ask(s)">{{ s }}</button>
                }
              </div>
            </div>
          }

          @for (m of messages(); track m.id) {
            <article class="flex" [class.justify-end]="m.role === 'user'">
              <div
                class="max-w-[92%] rounded-2xl px-4 py-3 text-sm shadow-sm sm:max-w-[80%]"
                [class]="m.role === 'user' ? 'bg-brand-600 text-white' : 'border border-slate-200 bg-white'"
              >
                @if (m.templateName) {
                  <p class="mb-1 text-[11px] font-semibold uppercase tracking-wide" [class]="m.role === 'user' ? 'text-brand-100' : 'text-brand-700'">Szablon: {{ m.templateName }}</p>
                }
                @if (m.role === 'assistant') {
                  <div class="md break-words" [innerHTML]="m.content | markdown"></div>
                  @if (m.pending && m.content) {<span class="animate-pulse text-brand-600" aria-hidden="true">▍</span>}
                } @else {
                  <p class="whitespace-pre-wrap break-words">{{ m.content }}</p>
                }
                @if (m.pending && !m.content) {
                  <p class="animate-pulse text-slate-500">{{ status() }}</p>
                }
                @if (m.failed) {
                  <p class="mt-2 text-xs text-red-600">Odpowiedź nie została ukończona.</p>
                }
                @if (m.role === 'assistant' && m.sources.length > 0) {
                  <details class="mt-3 rounded-lg bg-slate-50 p-2 text-xs text-slate-600">
                    <summary class="cursor-pointer font-semibold">Źródła ({{ m.sources.length }})</summary>
                    <ul class="mt-2 space-y-2">
                      @for (s of m.sources; track s.index) {
                        <li>
                          <p class="font-medium text-slate-700">[{{ s.index }}] {{ s.title }}</p>
                          <p class="text-[11px] text-slate-400">
                            {{ s.category }} · {{ s.audience }}
                            @if (s.icd10) { · ICD-10 {{ s.icd10 }} }
                            @if (s.icd11) { · ICD-11 {{ s.icd11 }} }
                            · trafność {{ s.score }}
                            @if (s.low_relevance) {
                              <span class="badge ml-1 bg-amber-100 text-amber-700">luźno związane z pytaniem</span>
                            }
                          </p>
                          <p class="mt-0.5">{{ s.snippet }}…</p>
                        </li>
                      }
                    </ul>
                  </details>
                }
                @if (m.role === 'assistant' && m.tokens > 0 && !m.pending) {
                  <p class="mt-2 text-[11px] text-slate-400">{{ m.tokens }} tokenów</p>
                }
              </div>
            </article>
          }
        </div>

        <form class="border-t border-slate-200 p-3" (ngSubmit)="send()">
          @if (templates().length > 0) {
            <div class="mb-2 flex flex-wrap items-center gap-1.5" role="group" aria-label="Szablon odpowiedzi">
              <span class="mr-1 text-xs font-semibold uppercase text-slate-500">Szablon</span>
              @for (t of templates(); track t.id) {
                <span
                  class="inline-flex items-center overflow-hidden rounded-full border text-xs font-medium transition"
                  [class]="selectedTemplateId() === t.id ? 'border-brand-600 bg-brand-600 text-white' : 'border-slate-300 bg-white text-slate-700 hover:border-brand-400'"
                >
                  <button type="button" class="py-1 pl-3 pr-2" [attr.aria-pressed]="selectedTemplateId() === t.id" [title]="t.description" [disabled]="streaming()" (click)="toggleTemplate(t)">
                    {{ t.name }}
                  </button>
                  <button
                    type="button"
                    class="border-l py-1 pl-1.5 pr-2.5"
                    [class]="selectedTemplateId() === t.id ? 'border-brand-500' : 'border-slate-200 text-slate-400 hover:text-brand-700'"
                    [attr.aria-label]="'Podgląd szablonu ' + t.name"
                    [attr.aria-expanded]="previewId() === t.id"
                    (click)="togglePreview(t)"
                  >👁</button>
                </span>
              }
              <a routerLink="/szablony" class="ml-1 text-xs font-medium text-brand-700 hover:underline">Moje szablony</a>
            </div>
          }
          @if (previewTemplate(); as pt) {
            <div class="mb-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
              <div class="mb-1 flex items-start justify-between gap-2">
                <p class="font-semibold text-slate-800">{{ pt.name }} <span class="font-normal text-slate-500">{{ pt.shared ? '· wspólny' : '· mój' }}</span></p>
                <button type="button" class="text-slate-400 hover:text-slate-700" aria-label="Zamknij podgląd" (click)="previewId.set(null)">✕</button>
              </div>
              @if (pt.description) { <p class="mb-2 text-slate-600">{{ pt.description }}</p> }
              <pre class="max-h-60 overflow-y-auto whitespace-pre-wrap font-sans text-slate-700">{{ pt.body }}</pre>
              <p class="mt-2 text-[11px] text-slate-500">
                Do szablonu dołączane są zasady: dobór tylko z listy, uzasadnienie danymi pacjenta, opis wykonania ze źródeł z bazy wiedzy.
              </p>
            </div>
          }
          @if (selectedTemplate(); as st) {
            <p class="mb-2 text-xs" [class]="needsPatient() ? 'font-medium text-red-700' : 'text-slate-500'" role="status">
              @if (needsPatient()) {
                Wybierz pacjenta – szablon „{{ st.name }}” opiera plan na jego danych.
              } @else {
                Plan wg szablonu „{{ st.name }}”{{ st.long_answer ? ' – dłuższa odpowiedź, mocniejszy model (ok. 3–6 kredytów)' : '' }}. Możesz dopisać uwagi poniżej.
              }
            </p>
          }
          <div class="flex items-end gap-2">
            <textarea
              class="field max-h-40 min-h-[2.75rem] flex-1 resize-y"
              rows="2"
              name="draft"
              [placeholder]="selectedTemplate() ? 'Uwagi do planu (opcjonalnie)… Enter – wyślij' : 'Napisz pytanie… (Enter – wyślij, Shift+Enter – nowa linia)'"
              [ngModel]="draft()"
              (ngModelChange)="draft.set($event)"
              (keydown.enter)="onEnter($event)"
              [disabled]="streaming()"
              maxlength="4000"
            ></textarea>
            @if (streaming()) {
              <button type="button" class="btn-secondary" (click)="stop()">Stop</button>
            } @else {
              <button type="submit" class="btn-primary" [disabled]="!canSend()">Wyślij</button>
            }
          </div>
          <p class="mt-2 text-[11px] text-slate-400">
            Asystent wspiera, ale nie zastępuje oceny klinicznej. Do modelu nie są przesyłane dane identyfikujące pacjenta.
          </p>
        </form>
      </section>
    </div>
    </div>
  `,
})
export class ChatComponent implements OnDestroy {
  private readonly chatApi = inject(ChatService);
  protected readonly billing = inject(BillingService);
  protected readonly exhaustedMessage = EXHAUSTED_MESSAGE;
  private readonly patientsApi = inject(PatientsService);
  private readonly templatesApi = inject(TemplatesService);
  private readonly scroller = viewChild<ElementRef<HTMLDivElement>>('scroller');

  protected readonly suggestions = [
    'Jak wywołać głoskę r u 6-latka?',
    'Jakie kody ICD dotyczą jąkania?',
    'Techniki terapii afazji Broca',
  ];

  protected readonly messages = signal<UiMessage[]>([]);
  protected readonly conversations = signal<ConversationSummary[]>([]);
  protected readonly patients = signal<Patient[]>([]);
  protected readonly patientId = signal<number | null>(null);
  protected readonly conversationId = signal<string | null>(null);
  protected readonly sessionUsage = signal<TokenCounter>({ ...EMPTY_USAGE });
  protected readonly status = signal('Łączenie…');
  protected readonly streaming = signal(false);
  protected readonly draft = signal('');
  protected readonly templates = signal<PromptTemplate[]>([]);
  protected readonly selectedTemplateId = signal<number | null>(null);
  protected readonly previewId = signal<number | null>(null);
  protected readonly selectedTemplate = computed(() => this.templates().find((t) => t.id === this.selectedTemplateId()) ?? null);
  protected readonly previewTemplate = computed(() => this.templates().find((t) => t.id === this.previewId()) ?? null);
  /** Szablon wymagający pacjenta wybrany bez pacjenta – wysyłka zablokowana. */
  protected readonly needsPatient = computed(() => !!this.selectedTemplate()?.requires_patient && this.patientId() === null);
  protected readonly canSend = computed(
    () => !this.streaming() && !this.needsPatient() && (!!this.selectedTemplate() || !!this.draft().trim()),
  );

  private nextId = 1;
  private abort: AbortController | null = null;

  constructor() {
    this.loadConversations();
    this.patientsApi.list().subscribe({ next: (list) => this.patients.set(list) });
    this.templatesApi.list().subscribe({ next: (list) => this.templates.set(list) });
    // Wejście z historii pacjenta: /chat?conversation=<id>&patient=<id>
    const params = inject(ActivatedRoute).snapshot.queryParamMap;
    const patient = Number(params.get('patient'));
    if (Number.isInteger(patient) && patient > 0) {
      this.patientId.set(patient);
    }
    const conversation = params.get('conversation');
    if (conversation) {
      this.open({ conversation_id: conversation });
    }
    effect(() => {
      this.messages();
      queueMicrotask(() => {
        const el = this.scroller()?.nativeElement;
        if (el) {
          el.scrollTop = el.scrollHeight;
        }
      });
    });
  }

  ngOnDestroy(): void {
    this.abort?.abort();
  }

  protected onEnter(event: Event): void {
    const keyboard = event as KeyboardEvent;
    if (!keyboard.shiftKey) {
      keyboard.preventDefault();
      void this.send();
    }
  }

  protected toggleTemplate(template: PromptTemplate): void {
    this.selectedTemplateId.set(this.selectedTemplateId() === template.id ? null : template.id);
  }

  protected togglePreview(template: PromptTemplate): void {
    this.previewId.set(this.previewId() === template.id ? null : template.id);
  }

  protected ask(question: string): void {
    this.draft.set(question);
    void this.send();
  }

  protected newConversation(): void {
    this.stop();
    this.messages.set([]);
    this.conversationId.set(null);
    this.sessionUsage.set({ ...EMPTY_USAGE });
  }

  protected open(conversation: Pick<ConversationSummary, 'conversation_id'>): void {
    this.stop();
    this.chatApi.conversation(conversation.conversation_id).subscribe({
      next: (stored) => {
        this.conversationId.set(conversation.conversation_id);
        this.messages.set(
          stored.map((m) => ({
            id: this.nextId++,
            role: m.role,
            content: m.content,
            sources: m.sources ?? [],
            tokens: m.total_tokens,
            pending: false,
            failed: false,
            templateName: m.template_name ?? null,
          })),
        );
        this.sessionUsage.set({
          ...EMPTY_USAGE,
          total_tokens: stored.reduce((sum, m) => sum + m.total_tokens, 0),
        });
      },
    });
  }

  protected remove(conversation: ConversationSummary): void {
    if (!confirm('Usunąć tę rozmowę?')) {
      return;
    }
    this.chatApi.deleteConversation(conversation.conversation_id).subscribe({
      next: () => {
        if (this.conversationId() === conversation.conversation_id) {
          this.newConversation();
        }
        this.loadConversations();
      },
    });
  }

  protected stop(): void {
    this.abort?.abort();
  }

  protected async send(): Promise<void> {
    if (!this.canSend()) {
      return;
    }
    const template = this.selectedTemplate();
    const text = template ? templateQuestion(template, this.draft()) : this.draft().trim();
    this.draft.set('');
    // Pastylka działa na jedno pytanie – kolejne pytania w rozmowie są już zwykłe.
    this.selectedTemplateId.set(null);
    this.previewId.set(null);
    this.streaming.set(true);
    this.status.set('Łączenie…');

    const assistantId = this.nextId + 1;
    this.messages.update((list) => [
      ...list,
      { id: this.nextId++, role: 'user', content: text, sources: [], tokens: 0, pending: false, failed: false, templateName: template?.name ?? null },
      { id: this.nextId++, role: 'assistant', content: '', sources: [], tokens: 0, pending: true, failed: false },
    ]);

    this.abort = new AbortController();
    try {
      const events = this.chatApi.stream(
        {
          message: text,
          conversation_id: this.conversationId(),
          patient_id: this.patientId(),
          template_id: template?.id ?? null,
        },
        this.abort.signal,
      );
      for await (const event of events) {
        this.apply(event, assistantId);
      }
    } catch (err) {
      const aborted = err instanceof DOMException && err.name === 'AbortError';
      this.patchMessage(assistantId, (m) => ({
        ...m,
        failed: !aborted,
        content: m.content || (aborted ? 'Przerwano generowanie.' : 'Wystąpił błąd połączenia.'),
      }));
    } finally {
      this.patchMessage(assistantId, (m) => ({ ...m, pending: false }));
      this.streaming.set(false);
      this.abort = null;
      this.loadConversations();
    }
  }

  private apply(event: ChatEvent, assistantId: number): void {
    switch (event.type) {
      case 'meta':
        this.conversationId.set(event.conversation_id);
        break;
      case 'status':
        this.status.set(STAGE_LABELS[event.stage] ?? 'Pracuję…');
        break;
      case 'sources':
        this.patchMessage(assistantId, (m) => ({ ...m, sources: event.sources }));
        break;
      case 'token':
        this.patchMessage(assistantId, (m) => ({ ...m, content: m.content + event.text }));
        break;
      case 'usage':
        this.patchMessage(assistantId, (m) => ({ ...m, tokens: event.total_tokens }));
        this.sessionUsage.update((u) => ({
          prompt_tokens: u.prompt_tokens + event.prompt_tokens,
          completion_tokens: u.completion_tokens + event.completion_tokens,
          total_tokens: u.total_tokens + event.total_tokens,
        }));
        break;
      case 'error':
        this.patchMessage(assistantId, (m) => ({ ...m, failed: true, content: m.content || event.message }));
        break;
      case 'done':
        this.billing.refresh();
        break;
    }
  }

  private patchMessage(id: number, patch: (m: UiMessage) => UiMessage): void {
    this.messages.update((list) => list.map((m) => (m.id === id ? patch(m) : m)));
  }

  private loadConversations(): void {
    this.chatApi.conversations().subscribe({ next: (list) => this.conversations.set(list) });
  }
}
