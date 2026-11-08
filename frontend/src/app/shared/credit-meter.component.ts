import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { CreditStatus, creditLevel, formatPln } from '../core/billing.service';

const BAR: Record<'ok' | 'warn' | 'exhausted', string> = {
  ok: 'bg-brand-500',
  warn: 'bg-amber-500',
  exhausted: 'bg-red-500',
};

/** Wskaźnik wykorzystania kredytów: pasek + „zużyte / dostępne zł” (kolor zawsze z liczbą). */
@Component({
  selector: 'app-credit-meter',
  standalone: true,
  imports: [DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="min-w-0" [class.w-36]="compact">
      <div class="flex items-baseline justify-between gap-2" [class]="compact ? 'text-[11px]' : 'text-xs'">
        <span class="font-semibold tabular-nums text-slate-700">{{ pln(status.used_pln) }} / {{ pln(status.available_pln) }}</span>
        @if (!compact) {
          <span class="tabular-nums text-slate-500">{{ status.percent | number: '1.0-0' }}%</span>
        }
      </div>
      <div
        class="mt-1 overflow-hidden rounded-full bg-slate-200"
        [class]="compact ? 'h-1.5' : 'h-2'"
        role="progressbar"
        aria-valuemin="0"
        aria-valuemax="100"
        [attr.aria-valuenow]="status.percent"
        [attr.aria-label]="'Wykorzystanie kredytów: ' + pln(status.used_pln) + ' z ' + pln(status.available_pln)"
      >
        <div class="h-full rounded-full transition-all" [class]="bar()" [style.width.%]="status.percent"></div>
      </div>
    </div>
  `,
})
export class CreditMeterComponent {
  @Input({ required: true }) status!: CreditStatus;
  @Input() compact = false;

  protected pln(value: number): string {
    return formatPln(value);
  }

  protected bar(): string {
    return BAR[creditLevel(this.status)];
  }
}
