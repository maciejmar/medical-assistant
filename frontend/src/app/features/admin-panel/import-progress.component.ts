import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { KbImportStatus } from '../../shared/models';

export interface UploadState {
  active: boolean;
  done: number;
  total: number;
  errors: number;
}

interface Step {
  key: 'upload' | 'scan' | 'ocr' | 'embed' | 'done';
  label: string;
}

const STEPS: Step[] = [
  { key: 'upload', label: 'Wysyłanie' },
  { key: 'scan', label: 'Skanowanie' },
  { key: 'ocr', label: 'Odczyt / OCR' },
  { key: 'embed', label: 'Embedding' },
  { key: 'done', label: 'Gotowe' },
];

/** Czas w formie „ok. 12 min”, „1 h 5 min”, „< 1 min”. */
export function humanDuration(seconds: number): string {
  if (seconds < 60) {
    return '< 1 min';
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

/** Wskaźnik postępu: wysyłanie plików → skanowanie → OCR → embedding → gotowe. */
@Component({
  selector: 'app-import-progress',
  standalone: true,
  imports: [DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: [
    `
      .bar-stripes {
        background-image: linear-gradient(
          45deg,
          rgba(255, 255, 255, 0.22) 25%,
          transparent 25%,
          transparent 50%,
          rgba(255, 255, 255, 0.22) 50%,
          rgba(255, 255, 255, 0.22) 75%,
          transparent 75%,
          transparent
        );
        background-size: 1.25rem 1.25rem;
        animation: bar-move 1s linear infinite;
      }
      @keyframes bar-move {
        from {
          background-position: 1.25rem 0;
        }
        to {
          background-position: 0 0;
        }
      }
      @media (prefers-reduced-motion: reduce) {
        .bar-stripes {
          animation: none;
        }
      }
    `,
  ],
  template: `
    @if (visible()) {
      <div class="mt-4 rounded-xl border border-brand-100 bg-gradient-to-br from-brand-50 to-white p-4" role="status" aria-live="polite">
        <!-- Etapy -->
        <ol class="mb-4 flex items-center gap-1 overflow-x-auto text-xs">
          @for (step of steps; track step.key; let i = $index; let last = $last) {
            <li class="flex shrink-0 items-center gap-1">
              <span
                class="grid h-6 w-6 place-items-center rounded-full font-semibold transition-colors"
                [class]="i < activeStep() ? 'bg-green-500 text-white' : i === activeStep() ? (finished() ? 'bg-green-500 text-white' : 'bg-brand-600 text-white ring-4 ring-brand-100') : 'bg-slate-200 text-slate-500'"
              >
                {{ i < activeStep() || (i === activeStep() && finished()) ? '✓' : i + 1 }}
              </span>
              <span [class.font-semibold]="i === activeStep()" [class.text-slate-400]="i > activeStep()">{{ step.label }}</span>
              @if (!last) {
                <span class="mx-1 h-px w-6 sm:w-10" [class]="i < activeStep() ? 'bg-green-400' : 'bg-slate-300'"></span>
              }
            </li>
          }
        </ol>

        <!-- Postęp ogólny -->
        <div class="flex items-end justify-between gap-3">
          <div>
            <p class="text-3xl font-bold tabular-nums text-brand-700">{{ percent() }}%</p>
            <p class="text-sm text-slate-600">{{ headline() }}</p>
          </div>
          <div class="text-right text-xs text-slate-500">
            @if (status()?.running) {
              <p>Upłynęło: {{ elapsed() }}</p>
              <p class="font-semibold text-slate-700">{{ eta() }}</p>
            } @else if (finished() && status()?.finished_at) {
              <p>Zakończono {{ status()!.finished_at | date: 'dd.MM.yyyy HH:mm' }}</p>
              <p>Czas: {{ elapsed() }}</p>
            }
          </div>
        </div>
        <div class="mt-2 h-3 w-full overflow-hidden rounded-full bg-slate-200">
          <div
            class="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-700 transition-[width] duration-700 ease-out"
            [class.bar-stripes]="busy()"
            [class.from-green-500]="finished() && !hasErrors()"
            [class.to-green-600]="finished() && !hasErrors()"
            [style.width.%]="percent()"
          ></div>
        </div>

        <!-- Bieżący dokument -->
        @if (status()?.running && progress()?.unit_title && progress()!.phase !== 'scan') {
          <div class="mt-4 rounded-lg bg-white/80 p-3 shadow-sm">
            <div class="flex items-center justify-between gap-2 text-sm">
              <p class="truncate font-medium" [title]="progress()!.unit_path">📄 {{ progress()!.unit_title }}</p>
              <span class="shrink-0 text-xs text-slate-500">dokument {{ progress()!.units_done + 1 }} z {{ progress()!.units_total }}</span>
            </div>
            <div class="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
              <div class="h-full rounded-full bg-amber-400 transition-[width] duration-500" [style.width.%]="stepPercent()"></div>
            </div>
            <p class="mt-1 text-xs text-slate-500">{{ stepLabel() }}</p>
          </div>
        }

        <!-- Liczniki -->
        @if (progress(); as p) {
          @if (p.units_total || p.unchanged) {
            <div class="mt-3 flex flex-wrap gap-2 text-xs">
              <span class="badge bg-green-100 text-green-700">nowe: {{ p.created }}</span>
              <span class="badge bg-sky-100 text-sky-700">zaktualizowane: {{ p.updated }}</span>
              <span class="badge bg-slate-100 text-slate-600">bez zmian: {{ p.unchanged }}</span>
              @if (p.failed) { <span class="badge bg-red-100 text-red-700">błędy: {{ p.failed }}</span> }
            </div>
          }

          <!-- Ostatnio przetworzone -->
          @if (p.recent.length) {
            <ul class="mt-3 divide-y divide-slate-100 rounded-lg bg-white/80 text-sm">
              @for (r of p.recent; track r.path) {
                <li class="flex items-start gap-2 px-3 py-2">
                  <span [class]="r.status === 'failed' ? 'text-red-600' : 'text-green-600'">{{ r.status === 'failed' ? '✗' : '✓' }}</span>
                  <div class="min-w-0">
                    <p class="truncate" [title]="r.path">{{ r.title }}</p>
                    <p class="text-xs" [class]="r.status === 'failed' ? 'text-red-600' : 'text-slate-500'">
                      @if (r.status === 'failed') {
                        {{ r.error }}
                      } @else {
                        {{ r.status === 'created' ? 'dodano' : 'zaktualizowano' }}
                        @if (r.pages) { · {{ r.pages }} stron OCR }
                        · {{ r.chunks }} fragmentów w indeksie
                      }
                    </p>
                  </div>
                </li>
              }
            </ul>
          }
        }

        @if (status()?.running) {
          <p class="mt-3 text-xs text-slate-500">Import działa na serwerze w tle – możesz zamknąć tę stronę i wrócić później.</p>
        }
        @if (status()?.error) {
          <p class="mt-3 text-sm text-red-600">Import przerwany: {{ status()!.error }}</p>
        }
      </div>
    }
  `,
})
export class ImportProgressComponent {
  readonly status = input<KbImportStatus | null>(null);
  readonly upload = input<UploadState>({ active: false, done: 0, total: 0, errors: 0 });

  protected readonly steps = STEPS;
  protected readonly progress = computed(() => this.status()?.progress ?? null);

  protected readonly uploading = computed(() => this.upload().active);
  protected readonly busy = computed(() => this.uploading() || !!this.status()?.running);
  protected readonly finished = computed(
    () => !this.busy() && !!this.status()?.finished_at && this.progress()?.phase === 'done',
  );
  protected readonly hasErrors = computed(() => (this.progress()?.failed ?? 0) > 0);

  protected readonly visible = computed(
    () => this.busy() || (!!this.status()?.finished_at && !!this.progress()),
  );

  protected readonly activeStep = computed(() => {
    if (this.uploading()) {
      return 0;
    }
    switch (this.progress()?.phase) {
      case 'scan':
        return 1;
      case 'ocr':
      case 'extract':
        return 2;
      case 'embed':
        return 3;
      case 'done':
        return 4;
      default:
        return 1;
    }
  });

  protected readonly percent = computed(() => {
    const upload = this.upload();
    if (upload.active) {
      return upload.total ? Math.floor((100 * upload.done) / upload.total) : 0;
    }
    return Math.floor(100 * (this.progress()?.fraction ?? 0));
  });

  protected readonly headline = computed(() => {
    const upload = this.upload();
    if (upload.active) {
      return `Wysyłanie plików na serwer: ${upload.done} z ${upload.total}`;
    }
    const p = this.progress();
    if (!p) {
      return '';
    }
    if (p.phase === 'scan') {
      return 'Skanowanie katalogu i wykrywanie nowych materiałów…';
    }
    if (this.finished()) {
      if (!p.units_total) {
        return 'Brak nowych materiałów – baza wiedzy jest aktualna.';
      }
      return `Zaindeksowano ${p.created + p.updated} z ${p.units_total} dokumentów${p.failed ? `, błędy: ${p.failed}` : ''}.`;
    }
    return `Przetwarzanie dokumentów: ${p.units_done} z ${p.units_total} gotowe`;
  });

  protected readonly stepPercent = computed(() => {
    const p = this.progress();
    return p && p.step_total ? (100 * p.step_done) / p.step_total : 0;
  });

  protected readonly stepLabel = computed(() => {
    const p = this.progress();
    if (!p) {
      return '';
    }
    switch (p.phase) {
      case 'ocr':
        return `OCR: strona ${p.step_done} z ${p.step_total}`;
      case 'extract':
        return 'Odczyt tekstu z pliku…';
      case 'embed':
        return `Embedding: fragment ${p.step_done} z ${p.step_total}`;
      default:
        return '';
    }
  });

  protected readonly elapsed = computed(() => humanDuration(this.progress()?.elapsed_seconds ?? 0));

  protected readonly eta = computed(() => {
    const seconds = this.progress()?.eta_seconds;
    return seconds == null ? 'Szacowanie czasu…' : `Pozostało ok. ${humanDuration(seconds)}`;
  });
}
