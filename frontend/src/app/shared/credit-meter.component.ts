import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { CreditStatus, creditLevel, formatCredits, formatPln } from '../core/billing.service';

const BAR: Record<'ok' | 'warn' | 'exhausted', string> = {
  ok: 'bg-brand-500',
  warn: 'bg-amber-500',
  exhausted: 'bg-red-500',
};

/** Wskaźnik wykorzystania: pasek + „zużyte / dostępne” w kredytach (klient) lub zł (administrator). */
@Component({
  selector: 'app-credit-meter',
  standalone: true,
  imports: [DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="min-w-0" [class.w-36]="compact">
      <div class="flex items-baseline justify-between gap-2" [class]="compact ? 'text-[11px]' : 'text-xs'">
        <span class="font-semibold tabular-nums text-slate-700">{{ usedLabel() }} / {{ availableLabel() }}</span>
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
        [attr.aria-label]="'Wykorzystanie kredytów: ' + usedLabel() + ' z ' + availableLabel()"
      >
        <div class="h-full rounded-full transition-all" [class]="bar()" [style.width.%]="status.percent"></div>
      </div>
    </div>
  `,
})
export class CreditMeterComponent {
  @Input({ required: true }) status!: CreditStatus;
  @Input() compact = false;
  /** Klient widzi kredyty; panel administratora – złotówki (tam ustawia się limity w zł). */
  @Input() unit: 'credits' | 'pln' = 'credits';

  protected usedLabel(): string {
    return this.unit === 'pln' ? formatPln(this.status.used_pln) : formatCredits(this.status.used_credits, false);
  }

  protected availableLabel(): string {
    return this.unit === 'pln' ? formatPln(this.status.available_pln) : formatCredits(this.status.available_credits);
  }

  protected bar(): string {
    return BAR[creditLevel(this.status)];
  }
}
