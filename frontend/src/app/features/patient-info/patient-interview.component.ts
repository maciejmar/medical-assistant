import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  Input,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { AudioRecordingService } from '../../core/audio-recording.service';
import { Interview, InterviewEntry, InterviewItem, InterviewService } from '../../core/interview.service';
import { IconComponent } from '../../shared/icon.component';

function apiError(err: unknown, fallback: string): string {
  if (err instanceof HttpErrorResponse && typeof err.error?.detail === 'string') {
    return err.error.detail;
  }
  return fallback;
}

/** Dokleja transkrypcję do istniejącej odpowiedzi (nic nie nadpisuje). */
export function mergeTranscript(answer: string, transcript: string): string {
  const current = answer.trim();
  const addition = transcript.trim();
  if (!addition) {
    return answer;
  }
  return current ? `${current} ${addition}` : addition;
}

/**
 * Wywiad pacjenta: tabela pytanie – odpowiedź. Odpowiedź lekarz wpisuje albo nagrywa (mikrofon) –
 * nagranie jest zapisywane przy pytaniu (głośnik = odsłuch), a jego transkrypcja doklejana do pola
 * odpowiedzi do poprawienia. „Zatwierdź” zapisuje wszystko i od tej chwili ta wersja trafia
 * do kontekstu asystenta.
 */
@Component({
  selector: 'app-patient-interview',
  standalone: true,
  imports: [DatePipe, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="card mt-6" aria-labelledby="interview-heading">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 id="interview-heading" class="font-semibold">Wywiad pacjenta</h2>
        @if (interview(); as iv) {
          @if (dirty()) {
            <span class="badge bg-amber-100 text-amber-800">Niezapisane zmiany</span>
          } @else if (iv.status === 'approved') {
            <span class="badge bg-emerald-100 text-emerald-800"><app-icon name="check" [size]="12" class="mr-1" /> Zatwierdzony {{ iv.approved_at | date: 'dd.MM.yyyy HH:mm' }}</span>
          } @else if (iv.approved_at) {
            <span class="badge bg-amber-100 text-amber-800">Zmiany po zatwierdzeniu {{ iv.approved_at | date: 'dd.MM.yyyy' }} – czekają na zatwierdzenie</span>
          } @else {
            <span class="badge bg-slate-100 text-slate-600">Niezatwierdzony</span>
          }
        }
      </div>
      <p class="mb-4 text-xs text-slate-500">
        Odpowiedź wpisz albo nagraj mikrofonem – nagranie zostaje zapisane przy pytaniu (przycisk głośnika odtwarza je), a transkrypcja trafia
        do pola odpowiedzi do poprawienia. Asystent uwzględnia wyłącznie <strong>zatwierdzoną</strong> wersję wywiadu.
      </p>

      @if (error(); as e) {
        <p class="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ e }}</p>
      }
      @if (recorder.error(); as e) {
        <p class="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ e }}</p>
      }

      @if (loading()) {
        <p class="text-sm text-slate-500">Wczytywanie wywiadu…</p>
      } @else {
        <div class="overflow-hidden rounded-lg border border-slate-200">
          <table class="w-full text-sm">
            <thead class="hidden bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 md:table-header-group">
              <tr>
                <th scope="col" class="w-2/5 px-3 py-2">Pytanie</th>
                <th scope="col" class="px-3 py-2">Odpowiedź</th>
              </tr>
            </thead>
            <tbody>
              @for (item of rows(); track item.id; let i = $index) {
                <tr class="block border-t border-slate-200 first:border-t-0 md:table-row">
                  <td class="block px-3 pb-1 pt-3 align-top md:table-cell md:py-3">
                    <p class="font-medium text-slate-800">{{ i + 1 }}. {{ item.question }}</p>
                    <div class="mt-2 flex flex-wrap items-center gap-1.5">
                      @if (recordingId() === item.id) {
                        <button type="button" class="inline-flex h-8 items-center gap-1.5 rounded-full bg-red-600 pl-2.5 pr-3 text-xs font-semibold text-white shadow-sm transition hover:bg-red-700" (click)="stopRecording(item)" [attr.aria-label]="'Zakończ nagrywanie odpowiedzi na pytanie ' + (i + 1)" title="Zakończ nagrywanie">
                          <span class="h-2 w-2 animate-pulse rounded-full bg-white" aria-hidden="true"></span>
                          <app-icon name="stop" [size]="14" />
                          <span class="tabular-nums">{{ recorder.elapsedSeconds() }} s</span>
                        </button>
                      } @else if (uploadingId() === item.id) {
                        <span class="inline-flex h-8 items-center gap-2 px-2 text-xs text-slate-500" role="status">
                          <span class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-brand-600 border-t-transparent" aria-hidden="true"></span>
                          Transkrypcja…
                        </span>
                      } @else {
                        <button type="button" class="grid h-8 w-8 place-items-center rounded-full border border-slate-300 bg-white text-slate-600 transition hover:border-red-300 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40" [disabled]="recordingId() !== null || uploadingId() !== null" (click)="startRecording(item)" [attr.aria-label]="'Nagraj odpowiedź na pytanie ' + (i + 1)" title="Nagraj odpowiedź pacjenta">
                          <app-icon name="mic" />
                        </button>
                      }
                      @if (item.has_audio) {
                        <button type="button" class="grid h-8 w-8 place-items-center rounded-full transition" [class]="playingId() === item.id ? 'bg-brand-600 text-white hover:bg-brand-700' : 'bg-brand-50 text-brand-700 hover:bg-brand-100'" (click)="togglePlayback(item)" [attr.aria-label]="(playingId() === item.id ? 'Zatrzymaj odsłuch' : 'Odsłuchaj odpowiedź pacjenta') + ' – pytanie ' + (i + 1)" [attr.aria-pressed]="playingId() === item.id" [title]="playingId() === item.id ? 'Zatrzymaj odsłuch' : 'Odsłuchaj nagraną odpowiedź'">
                          <app-icon [name]="playingId() === item.id ? 'pause' : 'volume-up'" />
                        </button>
                        <button type="button" class="grid h-8 w-8 place-items-center rounded-full text-slate-400 transition hover:bg-red-50 hover:text-red-600" (click)="deleteRecording(item)" [attr.aria-label]="'Usuń nagranie – pytanie ' + (i + 1)" title="Usuń nagranie">
                          <app-icon name="trash" [size]="14" />
                        </button>
                      }
                      <button type="button" class="ml-auto inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-slate-400 transition hover:bg-red-50 hover:text-red-700" (click)="removeQuestion(item)" [attr.aria-label]="'Usuń pytanie ' + (i + 1)" title="Usuń pytanie">
                        <app-icon name="trash" [size]="12" /> Usuń pytanie
                      </button>
                    </div>
                  </td>
                  <td class="block px-3 pb-3 pt-1 md:table-cell md:py-3">
                    <textarea
                      rows="3"
                      class="field w-full"
                      [value]="item.answer"
                      (input)="setAnswer(item.id, $any($event.target).value)"
                      [attr.aria-label]="'Odpowiedź na pytanie ' + (i + 1)"
                      placeholder="Odpowiedź pacjenta / opiekuna"
                    ></textarea>
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>

        <form class="mt-4 flex flex-col gap-2 sm:flex-row" (submit)="$event.preventDefault(); addQuestion()">
          <input
            class="field flex-1"
            [value]="newQuestion()"
            (input)="newQuestion.set($any($event.target).value)"
            placeholder="Własne pytanie do tego pacjenta"
            aria-label="Treść nowego pytania"
            maxlength="2000"
          />
          <button type="submit" class="btn-secondary" [disabled]="busy() || !newQuestion().trim()"><app-icon name="plus" /> Dodaj pytanie</button>
        </form>

        <div class="mt-4 flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 pt-4">
          @if (message(); as m) {
            <span class="mr-auto text-sm text-emerald-700" role="status">{{ m }}</span>
          }
          <button type="button" class="btn-secondary" [disabled]="busy() || !dirty()" (click)="save()">Zapisz szkic</button>
          <button type="button" class="btn-primary" [disabled]="busy() || recordingId() !== null || uploadingId() !== null" (click)="approve()"><app-icon name="check" /> Zatwierdź</button>
        </div>
      }
    </section>
  `,
})
export class PatientInterviewComponent implements OnInit, OnDestroy {
  @Input({ required: true }) patientId!: number;

  private readonly api = inject(InterviewService);
  protected readonly recorder = inject(AudioRecordingService);

  protected readonly interview = signal<Interview | null>(null);
  protected readonly rows = signal<InterviewItem[]>([]);
  protected readonly loading = signal(true);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly message = signal<string | null>(null);
  protected readonly newQuestion = signal('');
  protected readonly recordingId = signal<number | null>(null);
  protected readonly uploadingId = signal<number | null>(null);
  protected readonly playingId = signal<number | null>(null);

  /** Czy treść formularza różni się od zapisanej na serwerze. */
  protected readonly dirty = computed(() => {
    const saved = new Map((this.interview()?.items ?? []).map((i) => [i.id, i.answer.trim()]));
    return this.rows().some((row) => saved.get(row.id) !== row.answer.trim());
  });

  private audio: HTMLAudioElement | null = null;
  private audioUrl: string | null = null;

  ngOnInit(): void {
    this.api.get(this.patientId).subscribe({
      next: (interview) => {
        this.apply(interview);
        this.loading.set(false);
      },
      error: (err: unknown) => {
        this.loading.set(false);
        this.error.set(apiError(err, 'Nie udało się wczytać wywiadu.'));
      },
    });
  }

  ngOnDestroy(): void {
    if (this.recordingId() !== null) {
      this.recorder.cancel();
    }
    this.stopPlayback();
  }

  protected setAnswer(id: number, answer: string): void {
    this.message.set(null);
    this.rows.update((rows) => rows.map((r) => (r.id === id ? { ...r, answer } : r)));
  }

  protected save(): void {
    this.submit(this.api.save(this.patientId, this.entries()), 'Zapisano szkic wywiadu.');
  }

  protected approve(): void {
    this.submit(
      this.api.approve(this.patientId, this.entries()),
      'Wywiad zatwierdzony – asystent uwzględni go w odpowiedziach o tym pacjencie.',
    );
  }

  protected addQuestion(): void {
    const question = this.newQuestion().trim();
    if (!question) {
      return;
    }
    this.busy.set(true);
    this.api.addQuestion(this.patientId, question).subscribe({
      next: (item) => {
        this.busy.set(false);
        this.newQuestion.set('');
        this.rows.update((rows) => [...rows, item]);
        this.interview.update((iv) => iv && { ...iv, status: 'draft', items: [...iv.items, item] });
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.error.set(apiError(err, 'Nie udało się dodać pytania.'));
      },
    });
  }

  protected removeQuestion(item: InterviewItem): void {
    if (!confirm(`Usunąć pytanie „${item.question}” wraz z odpowiedzią i nagraniem?`)) {
      return;
    }
    if (this.playingId() === item.id) {
      this.stopPlayback();
    }
    this.api.deleteQuestion(this.patientId, item.id).subscribe({
      next: () => {
        this.rows.update((rows) => rows.filter((r) => r.id !== item.id));
        this.interview.update(
          (iv) => iv && { ...iv, status: 'draft', items: iv.items.filter((i) => i.id !== item.id) },
        );
      },
      error: (err: unknown) => this.error.set(apiError(err, 'Nie udało się usunąć pytania.')),
    });
  }

  protected async startRecording(item: InterviewItem): Promise<void> {
    this.error.set(null);
    this.stopPlayback();
    await this.recorder.start();
    if (this.recorder.state() === 'recording') {
      this.recordingId.set(item.id);
    }
  }

  protected async stopRecording(item: InterviewItem): Promise<void> {
    let blob: Blob;
    try {
      blob = await this.recorder.stop();
    } catch {
      this.recordingId.set(null);
      return;
    }
    this.recordingId.set(null);
    this.uploadingId.set(item.id);
    this.api.uploadRecording(this.patientId, item.id, blob).subscribe({
      next: (result) => {
        this.uploadingId.set(null);
        this.markAudio(item.id, true);
        if (result.transcript) {
          const current = this.rows().find((r) => r.id === item.id)?.answer ?? '';
          this.setAnswer(item.id, mergeTranscript(current, result.transcript));
        }
        if (result.error) {
          this.error.set(`Nagranie zapisano, ale transkrypcja się nie powiodła: ${result.error}. Wpisz odpowiedź ręcznie.`);
        }
      },
      error: (err: unknown) => {
        this.uploadingId.set(null);
        this.error.set(apiError(err, 'Nie udało się zapisać nagrania.'));
      },
    });
  }

  protected togglePlayback(item: InterviewItem): void {
    if (this.playingId() === item.id) {
      this.stopPlayback();
      return;
    }
    this.stopPlayback();
    this.playingId.set(item.id);
    this.api.recording(this.patientId, item.id).subscribe({
      next: (blob) => {
        if (this.playingId() !== item.id) {
          return;
        }
        this.audioUrl = URL.createObjectURL(blob);
        this.audio = new Audio(this.audioUrl);
        this.audio.onended = () => this.stopPlayback();
        this.audio.play().catch(() => {
          this.stopPlayback();
          this.error.set('Nie udało się odtworzyć nagrania.');
        });
      },
      error: () => {
        this.playingId.set(null);
        this.error.set('Nie udało się pobrać nagrania.');
      },
    });
  }

  protected deleteRecording(item: InterviewItem): void {
    if (!confirm('Usunąć nagranie odpowiedzi? Tekst odpowiedzi pozostanie.')) {
      return;
    }
    if (this.playingId() === item.id) {
      this.stopPlayback();
    }
    this.api.deleteRecording(this.patientId, item.id).subscribe({
      next: () => this.markAudio(item.id, false),
      error: (err: unknown) => this.error.set(apiError(err, 'Nie udało się usunąć nagrania.')),
    });
  }

  private stopPlayback(): void {
    if (this.audio) {
      this.audio.onended = null;
      this.audio.pause();
      this.audio = null;
    }
    if (this.audioUrl) {
      URL.revokeObjectURL(this.audioUrl);
      this.audioUrl = null;
    }
    this.playingId.set(null);
  }

  private markAudio(id: number, hasAudio: boolean): void {
    const patch = (items: InterviewItem[]) =>
      items.map((i) => (i.id === id ? { ...i, has_audio: hasAudio } : i));
    this.rows.update(patch);
    this.interview.update((iv) => iv && { ...iv, items: patch(iv.items) });
  }

  private entries(): InterviewEntry[] {
    return this.rows().map(({ id, question, answer }) => ({ id, question, answer }));
  }

  private submit(request: ReturnType<InterviewService['save']>, success: string): void {
    this.busy.set(true);
    this.error.set(null);
    this.message.set(null);
    request.subscribe({
      next: (interview) => {
        this.busy.set(false);
        this.apply(interview);
        this.message.set(success);
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.error.set(apiError(err, 'Nie udało się zapisać wywiadu.'));
      },
    });
  }

  private apply(interview: Interview): void {
    this.interview.set(interview);
    this.rows.set(interview.items.map((i) => ({ ...i })));
  }
}
