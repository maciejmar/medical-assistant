import { ChangeDetectionStrategy, Component, Input, OnDestroy, signal } from '@angular/core';
import { InterviewForm } from '../../core/interview.service';
import { PatientInterviewComponent } from './patient-interview.component';

export const LEAVE_MS = 260;

const OPTIONS: { form: InterviewForm; label: string; hint: string }[] = [
  { form: 'interview', label: 'Wywiad', hint: 'Uniwersalny wywiad i badanie logopedyczne' },
  { form: 'ankyloglossia', label: 'Diagnoza ankyloglosji', hint: 'Karta badania – diagnoza ankyloglosji' },
];

/**
 * Przełącznik formularzy pacjenta: uniwersalny wywiad (domyślnie) albo diagnoza ankyloglosji.
 * Zmiana: bieżąca karta znika (zanikanie + przesunięcie + rozmycie), po niej pojawia się druga.
 * Oba formularze zostają w pamięci po pierwszym otwarciu – przełączanie nie gubi niezapisanych
 * zmian ani trwającego nagrania; karta ankyloglosji zakłada się dopiero przy pierwszym wyborze.
 */
@Component({
  selector: 'app-patient-exams',
  standalone: true,
  imports: [PatientInterviewComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    .exam-enter { animation: exam-enter 420ms cubic-bezier(0.22, 1, 0.36, 1) both; }
    .exam-leave { animation: exam-leave ${LEAVE_MS}ms cubic-bezier(0.4, 0, 1, 1) both; pointer-events: none; }
    @keyframes exam-enter {
      from { opacity: 0; transform: translateY(14px) scale(0.985); filter: blur(6px); }
      to { opacity: 1; transform: none; filter: none; }
    }
    @keyframes exam-leave {
      from { opacity: 1; transform: none; filter: none; }
      to { opacity: 0; transform: translateY(-10px) scale(0.985); filter: blur(6px); }
    }
    @media (prefers-reduced-motion: reduce) {
      .exam-enter, .exam-leave { animation-duration: 1ms; }
    }
  `,
  template: `
    <div class="mt-6">
      <div class="mb-3 flex justify-center sm:justify-start">
        <div class="relative grid w-full grid-cols-2 rounded-full bg-slate-100 p-1 shadow-inner sm:w-auto" role="tablist" aria-label="Formularz badania">
          <span
            class="absolute inset-y-1 left-1 w-[calc(50%-0.25rem)] rounded-full bg-white shadow ring-1 ring-slate-200 transition-transform duration-300 ease-out"
            [style.transform]="selected() === 'ankyloglossia' ? 'translateX(100%)' : 'none'"
            aria-hidden="true"
          ></span>
          @for (option of options; track option.form) {
            <button
              type="button"
              role="tab"
              class="relative z-10 rounded-full px-5 py-2 text-sm font-semibold transition-colors duration-300 sm:min-w-[13rem]"
              [class]="selected() === option.form ? 'text-brand-700' : 'text-slate-500 hover:text-slate-700'"
              [attr.aria-selected]="selected() === option.form"
              [attr.aria-controls]="'exam-panel-' + option.form"
              [title]="option.hint"
              (click)="select(option.form)"
            >
              {{ option.label }}
            </button>
          }
        </div>
      </div>

      @for (option of options; track option.form) {
        @if (mounted()[option.form]) {
          <div
            role="tabpanel"
            [id]="'exam-panel-' + option.form"
            [hidden]="shown() !== option.form"
            [class.exam-enter]="shown() === option.form && !leaving()"
            [class.exam-leave]="shown() === option.form && leaving()"
          >
            <app-patient-interview [patientId]="patientId" [form]="option.form" />
          </div>
        }
      }
    </div>
  `,
})
export class PatientExamsComponent implements OnDestroy {
  @Input({ required: true }) patientId!: number;

  protected readonly options = OPTIONS;
  /** Wybrany przycisk (przełącznik reaguje od razu) i karta faktycznie widoczna (po animacji). */
  protected readonly selected = signal<InterviewForm>('interview');
  protected readonly shown = signal<InterviewForm>('interview');
  protected readonly leaving = signal(false);
  protected readonly mounted = signal<Record<InterviewForm, boolean>>({ interview: true, ankyloglossia: false });

  private timer: ReturnType<typeof setTimeout> | null = null;

  ngOnDestroy(): void {
    if (this.timer) clearTimeout(this.timer);
  }

  protected select(form: InterviewForm): void {
    if (form === this.selected()) return;
    this.selected.set(form);
    if (this.timer) clearTimeout(this.timer);
    this.leaving.set(true);
    this.timer = setTimeout(() => {
      this.timer = null;
      this.mounted.update((m) => ({ ...m, [form]: true }));
      this.shown.set(this.selected());
      this.leaving.set(false);
    }, LEAVE_MS);
  }
}
