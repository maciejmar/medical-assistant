import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { timeOf } from './calendar-utils';
import { IconComponent } from './icon.component';

export interface TimeConflict {
  id: number;
  title: string;
  patient_id: number;
  patient_name: string;
  starts_at: string;
  ends_at: string;
}

/** Kolizje z odpowiedzi 409 `time_conflict` serwera albo null (inny błąd). */
export function parseTimeConflict(err: unknown): TimeConflict[] | null {
  if (err instanceof HttpErrorResponse && err.status === 409 && err.error?.detail?.code === 'time_conflict') {
    return (err.error.detail.conflicts ?? []) as TimeConflict[];
  }
  return null;
}

/**
 * Ostrzeżenie „termin zajęty” w oknie wydarzenia: lista kolidujących wydarzeń, prośba o zmianę
 * terminu i świadome potwierdzenie zapisu mimo kolizji.
 */
@Component({
  selector: 'app-time-conflict',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" role="alert">
      <p class="flex items-center gap-2 font-semibold">
        <span class="grid h-6 w-6 place-items-center rounded-full bg-amber-200 text-amber-900"><app-icon name="clock" [size]="13" /></span>
        Ten termin jest już zajęty
      </p>
      <ul class="mt-2 space-y-0.5 pl-8">
        @for (c of conflicts; track c.id) {
          <li><span class="font-medium">{{ c.title }}</span> – {{ c.patient_name }}, {{ day(c.starts_at) }} {{ time(c.starts_at) }}–{{ time(c.ends_at) }}</li>
        }
      </ul>
      <p class="mt-2 pl-8">Zmień termin tego wydarzenia.</p>
      <div class="mt-3 flex flex-wrap gap-2 pl-8">
        <button type="button" class="btn-primary !px-3 !py-1.5 !text-xs" (click)="changeTerm.emit()">Zmień termin</button>
        <button type="button" class="rounded-lg border border-amber-400 bg-white px-3 py-1.5 text-xs font-semibold text-amber-900 hover:bg-amber-100" [disabled]="busy" (click)="confirmOverlap.emit()">
          Zapisz mimo to
        </button>
      </div>
    </div>
  `,
})
export class TimeConflictComponent {
  @Input({ required: true }) conflicts: TimeConflict[] = [];
  @Input() busy = false;
  @Output() readonly changeTerm = new EventEmitter<void>();
  @Output() readonly confirmOverlap = new EventEmitter<void>();

  protected time(iso: string): string {
    return timeOf(new Date(iso));
  }

  protected day(iso: string): string {
    return new Intl.DateTimeFormat('pl-PL', { day: 'numeric', month: 'short' }).format(new Date(iso));
  }
}
