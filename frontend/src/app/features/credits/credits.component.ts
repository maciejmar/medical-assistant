import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { BillingService, EXHAUSTED_MESSAGE, TopUp, formatPln } from '../../core/billing.service';
import { CreditMeterComponent } from '../../shared/credit-meter.component';

const STATUS_LABELS: Record<TopUp['status'], { label: string; css: string }> = {
  pending: { label: 'Oczekuje na wpłatę', css: 'bg-amber-100 text-amber-800' },
  confirmed: { label: 'Zaksięgowane', css: 'bg-emerald-100 text-emerald-800' },
  rejected: { label: 'Odrzucone', css: 'bg-red-100 text-red-700' },
  cancelled: { label: 'Anulowane', css: 'bg-slate-100 text-slate-600' },
};

/** Kredyty użytkownika: wykorzystanie w bieżącym oknie subskrypcji i doładowania przelewem. */
@Component({
  selector: 'app-credits',
  standalone: true,
  imports: [DatePipe, CreditMeterComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 class="text-2xl font-bold">Kredyty</h1>
        <p class="text-sm text-slate-500">Wykorzystanie asystenta w bieżącym okresie rozliczeniowym.</p>
      </div>

      @if (data(); as d) {
        @if (d.status.exhausted) {
          <p class="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-900" role="status">
            {{ exhaustedMessage }} Dokup kredyty, aby wrócić do pełnej jakości odpowiedzi.
          </p>
        }

        <section class="card space-y-4">
          <app-credit-meter [status]="d.status" />
          <dl class="grid gap-3 text-sm sm:grid-cols-4">
            <div><dt class="label">Limit miesięczny</dt><dd class="font-semibold">{{ pln(d.status.limit_pln) }}</dd></div>
            <div><dt class="label">Doładowania</dt><dd class="font-semibold">{{ pln(d.status.topups_pln) }}</dd></div>
            <div><dt class="label">Pozostało</dt><dd class="font-semibold">{{ pln(d.status.remaining_pln) }}</dd></div>
            <div><dt class="label">Odnowienie limitu</dt><dd class="font-semibold">{{ d.status.window_end | date: 'dd.MM.yyyy HH:mm' }}</dd></div>
          </dl>
          <p class="text-xs text-slate-500">
            Okres rozliczeniowy: {{ d.status.window_start | date: 'dd.MM.yyyy' }} – {{ d.status.window_end | date: 'dd.MM.yyyy' }}
            (co miesiąc od {{ d.status.started_at | date: 'd' }}. dnia). Koszt liczony jest z liczby tokenów według cennika modeli.
          </p>
        </section>

        <section class="card space-y-4">
          <h2 class="font-semibold">Dokup kredyty</h2>
          <div class="flex flex-wrap gap-3">
            @for (amount of d.payment.amounts; track amount) {
              <button type="button" class="btn-secondary min-w-[6rem] !py-3 text-base" [disabled]="busy()" (click)="order(amount)">{{ pln(amount) }}</button>
            }
          </div>
          @if (error(); as e) {
            <p class="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ e }}</p>
          }
          @if (ordered(); as t) {
            <div class="rounded-xl border border-brand-200 bg-brand-50/60 p-4 text-sm" role="status">
              <p class="mb-2 font-semibold text-brand-800">Zamówienie przyjęte – wykonaj przelew:</p>
              <dl class="grid gap-x-4 gap-y-1 sm:grid-cols-[9rem_1fr]">
                <dt class="text-slate-500">Odbiorca</dt><dd class="font-medium">{{ d.payment.recipient }}</dd>
                <dt class="text-slate-500">Numer konta</dt>
                <dd class="font-mono font-medium">{{ d.payment.bank_account || 'numer konta przekaże administrator' }}</dd>
                <dt class="text-slate-500">Kwota</dt><dd class="font-medium">{{ pln(t.amount_pln) }}</dd>
                <dt class="text-slate-500">Tytuł przelewu</dt>
                <dd class="flex items-center gap-2 font-mono font-medium">{{ t.reference }}
                  <button type="button" class="rounded px-1.5 py-0.5 font-sans text-xs text-brand-700 hover:bg-brand-100" (click)="copy(t.reference)">{{ copied() ? 'Skopiowano' : 'Kopiuj' }}</button>
                </dd>
              </dl>
              <p class="mt-2 text-xs text-slate-500">Kredyty zostaną dodane po zaksięgowaniu wpłaty (zwykle w ciągu 1 dnia roboczego).</p>
            </div>
          }
        </section>

        @if (d.topups.length > 0) {
          <section class="card">
            <h2 class="mb-3 font-semibold">Twoje doładowania</h2>
            <ul class="divide-y divide-slate-100 text-sm">
              @for (t of d.topups; track t.id) {
                <li class="flex flex-wrap items-center gap-3 py-2">
                  <span class="w-24 font-semibold tabular-nums">{{ pln(t.amount_pln) }}</span>
                  <span class="badge" [class]="label(t).css">{{ label(t).label }}</span>
                  <span class="font-mono text-xs text-slate-500">{{ t.reference }}</span>
                  <span class="ml-auto text-xs text-slate-500">{{ t.created_at | date: 'dd.MM.yyyy HH:mm' }}</span>
                  @if (t.status === 'pending') {
                    <button type="button" class="text-xs font-medium text-slate-500 hover:text-red-600" (click)="cancel(t)">Anuluj</button>
                  }
                </li>
              }
            </ul>
          </section>
        }
      } @else {
        <p class="text-sm text-slate-500">Wczytywanie…</p>
      }
    </div>
  `,
})
export class CreditsComponent implements OnInit {
  private readonly api = inject(BillingService);

  protected readonly data = this.api.mine;
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly ordered = signal<TopUp | null>(null);
  protected readonly copied = signal(false);
  protected readonly exhaustedMessage = EXHAUSTED_MESSAGE;

  ngOnInit(): void {
    this.api.refresh();
  }

  protected pln(value: number): string {
    return formatPln(value);
  }

  protected label(t: TopUp) {
    return STATUS_LABELS[t.status] ?? STATUS_LABELS.pending;
  }

  protected order(amount: number): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.orderTopUp(amount).subscribe({
      next: (topup) => {
        this.busy.set(false);
        this.ordered.set(topup);
        this.copied.set(false);
        this.api.refresh();
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.error.set(
          err instanceof HttpErrorResponse && typeof err.error?.detail === 'string'
            ? err.error.detail
            : 'Nie udało się złożyć zamówienia.',
        );
      },
    });
  }

  protected cancel(t: TopUp): void {
    if (!confirm(`Anulować zamówienie doładowania ${this.pln(t.amount_pln)}?`)) {
      return;
    }
    this.api.cancelTopUp(t.id).subscribe({
      next: () => {
        if (this.ordered()?.id === t.id) {
          this.ordered.set(null);
        }
        this.api.refresh();
      },
    });
  }

  protected copy(text: string): void {
    void navigator.clipboard?.writeText(text).then(() => this.copied.set(true));
  }
}
