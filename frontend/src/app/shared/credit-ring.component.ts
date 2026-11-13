import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { CreditStatus, creditLevel, formatCredits } from '../core/billing.service';

const STROKE: Record<'ok' | 'warn' | 'exhausted', string> = {
  ok: 'stroke-brand-500',
  warn: 'stroke-amber-500',
  exhausted: 'stroke-red-500',
};

/** Procent do wyświetlenia: „<1%” dla śladowego zużycia, zamiast mylącego „0%”. */
export function percentLabel(percent: number): string {
  if (percent > 0 && percent < 1) {
    return '<1%';
  }
  return `${Math.round(percent)}%`;
}

/**
 * Kółko wykorzystania kredytów (SVG): łuk proporcjonalny do zużycia, procent w środku.
 * Kolor jak w pasku – brand < 75% ≤ amber < 100% ≤ red – zawsze z liczbą, nie zamiast niej.
 */
@Component({
  selector: 'app-credit-ring',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'inline-flex shrink-0' },
  template: `
    <svg
      [attr.width]="size"
      [attr.height]="size"
      [attr.viewBox]="'0 0 ' + size + ' ' + size"
      role="img"
      [attr.aria-label]="'Wykorzystano ' + label() + ' kredytów (' + credits(status.used_credits, false) + ' z ' + credits(status.available_credits) + ')'"
    >
      <circle [attr.cx]="center" [attr.cy]="center" [attr.r]="radius" fill="none" class="stroke-slate-200" [attr.stroke-width]="stroke" />
      <circle
        [attr.cx]="center"
        [attr.cy]="center"
        [attr.r]="radius"
        fill="none"
        stroke-linecap="round"
        class="transition-[stroke-dashoffset] duration-700"
        [class]="arcClass()"
        [attr.stroke-width]="stroke"
        [attr.stroke-dasharray]="circumference"
        [attr.stroke-dashoffset]="offset()"
        [attr.transform]="'rotate(-90 ' + center + ' ' + center + ')'"
      />
      <text
        [attr.x]="center"
        [attr.y]="center"
        text-anchor="middle"
        dominant-baseline="central"
        class="fill-slate-800 font-semibold tabular-nums"
        [attr.font-size]="fontSize"
      >{{ label() }}</text>
    </svg>
  `,
})
export class CreditRingComponent {
  @Input({ required: true }) status!: CreditStatus;
  /** Średnica w px (pasek nawigacji ~40, strona Kredyty ~140). */
  @Input() size = 40;

  get stroke(): number {
    return Math.max(4, Math.round(this.size / 9));
  }

  get center(): number {
    return this.size / 2;
  }

  get radius(): number {
    return (this.size - this.stroke) / 2;
  }

  get circumference(): number {
    return 2 * Math.PI * this.radius;
  }

  get fontSize(): number {
    return Math.round(this.size * (this.size < 60 ? 0.27 : 0.22));
  }

  protected label(): string {
    return percentLabel(this.status.percent);
  }

  protected offset(): number {
    const percent = Math.min(100, Math.max(0, this.status.percent));
    // Śladowe zużycie nadal widoczne jako kropka łuku.
    const visible = percent > 0 ? Math.max(percent, 1.5) : 0;
    return this.circumference * (1 - visible / 100);
  }

  protected arcClass(): string {
    return STROKE[creditLevel(this.status)];
  }

  protected credits(value: number, withWord = true): string {
    return formatCredits(value, withWord);
  }
}
