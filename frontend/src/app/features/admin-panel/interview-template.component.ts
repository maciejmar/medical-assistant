import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { InterviewService, InterviewTemplate } from '../../core/interview.service';

/** Edycja szablonu pytań wywiadu – jedno pytanie w wierszu. Dotyczy nowo zakładanych wywiadów. */
@Component({
  selector: 'app-interview-template',
  standalone: true,
  imports: [DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="card mt-6" aria-labelledby="template-heading">
      <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 id="template-heading" class="font-semibold">Szablon wywiadu pacjenta ({{ count() }} pytań)</h2>
        @if (template(); as t) {
          <span class="badge" [class]="t.is_default ? 'bg-slate-100 text-slate-600' : 'bg-brand-50 text-brand-700'">
            {{ t.is_default ? 'Szablon domyślny' : 'Zmieniony ' + (t.updated_at | date: 'dd.MM.yyyy HH:mm') }}
          </span>
        }
      </div>
      <p class="mb-3 text-xs text-slate-500">
        Jedno pytanie w wierszu; wiersz zaczynający się od „## ” to nagłówek sekcji. Szablon jest kopiowany do wywiadu przy jego pierwszym otwarciu – zmiana nie wpływa na
        wywiady już założone. Lekarz może u konkretnego pacjenta dodawać i usuwać pytania.
      </p>
      <textarea
        class="field font-mono text-sm"
        rows="20"
        [value]="text()"
        (input)="text.set($any($event.target).value); message.set(null)"
        aria-label="Pytania szablonu wywiadu, jedno w wierszu"
      ></textarea>
      <div class="mt-3 flex flex-wrap items-center justify-end gap-2">
        @if (message(); as m) {
          <span class="mr-auto text-sm" [class]="failed() ? 'text-red-700' : 'text-emerald-700'" role="status">{{ m }}</span>
        }
        <button type="button" class="btn-secondary" [disabled]="busy() || template()?.is_default" (click)="reset()">Przywróć domyślny</button>
        <button type="button" class="btn-primary" [disabled]="busy() || count() === 0" (click)="save()">Zapisz szablon</button>
      </div>
    </section>
  `,
})
export class InterviewTemplateComponent implements OnInit {
  private readonly api = inject(InterviewService);

  protected readonly template = signal<InterviewTemplate | null>(null);
  protected readonly text = signal('');
  protected readonly busy = signal(false);
  protected readonly message = signal<string | null>(null);
  protected readonly failed = signal(false);
  protected readonly questions = computed(() =>
    this.text()
      .split('\n')
      .map((q) => q.trim())
      .filter(Boolean),
  );
  protected readonly count = computed(() => this.questions().filter((q) => !q.startsWith('## ')).length);

  ngOnInit(): void {
    this.api.template().subscribe({ next: (t) => this.apply(t) });
  }

  protected save(): void {
    this.run(this.api.saveTemplate(this.questions()), 'Zapisano szablon.');
  }

  protected reset(): void {
    if (confirm('Przywrócić domyślny zestaw pytań? Twoje zmiany w szablonie zostaną utracone.')) {
      this.run(this.api.resetTemplate(), 'Przywrócono szablon domyślny.');
    }
  }

  private run(request: ReturnType<InterviewService['template']>, success: string): void {
    this.busy.set(true);
    request.subscribe({
      next: (t) => {
        this.busy.set(false);
        this.apply(t);
        this.failed.set(false);
        this.message.set(success);
      },
      error: () => {
        this.busy.set(false);
        this.failed.set(true);
        this.message.set('Nie udało się zapisać szablonu.');
      },
    });
  }

  private apply(template: InterviewTemplate): void {
    this.template.set(template);
    this.text.set(template.questions.join('\n'));
  }
}
