import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormBuilder, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { AudioRecordingService } from '../../core/audio-recording.service';
import { PatientsService } from '../../core/patients.service';
import { NoteSource, Patient, PatientNote } from '../../shared/models';
import { ageFromBirthDate, emptyToNull, formatDuration } from '../../shared/utils';

@Component({
  selector: 'app-patient-info',
  standalone: true,
  imports: [ReactiveFormsModule, FormsModule, RouterLink, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a routerLink="/dashboard" class="mb-4 inline-block text-sm text-brand-700 hover:underline">← Wróć do pacjentów</a>

    @if (patient(); as p) {
      <div class="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 class="text-2xl font-bold">{{ p.first_name }} {{ p.last_name }}</h1>
          <p class="text-sm text-slate-500">
            @if (age() !== null) { {{ age() }} lat · }
            {{ p.diagnosis || 'Brak rozpoznania' }}
            @if (p.icd_code) { · ICD {{ p.icd_code }} }
          </p>
        </div>
        <button type="button" class="btn-danger" (click)="removePatient()">Usuń pacjenta</button>
      </div>

      <div class="grid gap-6 lg:grid-cols-2">
        <form class="card space-y-4" [formGroup]="form" (ngSubmit)="save()">
          <h2 class="font-semibold">Dane pacjenta</h2>
          <div class="grid gap-4 sm:grid-cols-2">
            <div>
              <label class="label" for="first">Imię</label>
              <input id="first" class="field" formControlName="first_name" />
            </div>
            <div>
              <label class="label" for="last">Nazwisko</label>
              <input id="last" class="field" formControlName="last_name" />
            </div>
            <div>
              <label class="label" for="birth">Data urodzenia</label>
              <input id="birth" class="field" type="date" formControlName="birth_date" />
            </div>
            <div>
              <label class="label" for="icd">Kod ICD</label>
              <input id="icd" class="field" formControlName="icd_code" />
            </div>
          </div>
          <div>
            <label class="label" for="diag">Rozpoznanie</label>
            <input id="diag" class="field" formControlName="diagnosis" />
          </div>
          <div>
            <label class="label" for="desc">Opis, cele terapii</label>
            <textarea id="desc" class="field" rows="4" formControlName="description"></textarea>
          </div>
          <div class="flex items-center justify-end gap-3">
            @if (saveMessage()) {
              <span class="mr-auto text-sm text-brand-700">{{ saveMessage() }}</span>
            }
            <button type="submit" class="btn-primary" [disabled]="form.invalid || form.pristine || saving()">Zapisz zmiany</button>
          </div>
        </form>

        <section class="card space-y-4">
          <h2 class="font-semibold">Nowa notatka</h2>

          <div class="rounded-lg border border-dashed border-slate-300 p-3">
            <div class="flex flex-wrap items-center gap-3">
              @if (recorder.state() === 'recording') {
                <button type="button" class="btn-danger" (click)="stopDictation()">■ Zatrzymaj i transkrybuj</button>
                <button type="button" class="btn-secondary" (click)="recorder.cancel()">Anuluj</button>
                <span class="flex items-center gap-2 text-sm font-mono text-red-600">
                  <span class="h-2.5 w-2.5 animate-pulse rounded-full bg-red-600"></span>
                  {{ elapsed() }}
                </span>
              } @else if (recorder.state() === 'processing') {
                <span class="animate-pulse text-sm text-slate-600">Transkrypcja nagrania…</span>
              } @else {
                <button type="button" class="btn-primary" (click)="recorder.start()" [disabled]="!recorder.isSupported">🎙 Dyktuj notatkę</button>
                @if (!recorder.isSupported) {
                  <span class="text-xs text-slate-500">Nagrywanie wymaga nowoczesnej przeglądarki i połączenia HTTPS.</span>
                }
              }
            </div>
            @if (recorder.error()) {
              <p class="mt-2 text-sm text-red-600" role="alert">{{ recorder.error() }}</p>
            }
          </div>

          <textarea
            class="field"
            rows="6"
            placeholder="Wpisz notatkę lub użyj dyktowania. Możesz poprawić tekst po transkrypcji."
            [ngModel]="draft()"
            (ngModelChange)="draft.set($event)"
            [ngModelOptions]="{ standalone: true }"
            maxlength="20000"
          ></textarea>
          <div class="flex items-center justify-between gap-3">
            <span class="text-xs text-slate-500">{{ dictated() ? 'Zawiera tekst z transkrypcji audio' : '' }}</span>
            <button type="button" class="btn-primary" [disabled]="!draft().trim() || savingNote()" (click)="addNote()">Zapisz notatkę</button>
          </div>
        </section>
      </div>

      <section class="card mt-6">
        <h2 class="mb-4 font-semibold">Historia sesji i notatek ({{ notes().length }})</h2>
        @if (notes().length === 0) {
          <p class="text-sm text-slate-500">Brak notatek.</p>
        }
        <ul class="space-y-3">
          @for (n of notes(); track n.id) {
            <li class="rounded-lg border border-slate-200 p-3">
              <div class="mb-1 flex items-center justify-between gap-2 text-xs text-slate-500">
                <span>
                  {{ n.created_at | date: 'dd.MM.yyyy HH:mm' }}
                  @if (n.source === 'dictated') { <span class="badge ml-1 bg-brand-50 text-brand-700">dyktowana</span> }
                </span>
                <button type="button" class="text-slate-400 hover:text-red-600" (click)="removeNote(n)">Usuń</button>
              </div>
              <p class="whitespace-pre-wrap text-sm">{{ n.content }}</p>
            </li>
          }
        </ul>
      </section>
    } @else if (loadError()) {
      <div class="card text-sm text-red-700">{{ loadError() }}</div>
    } @else {
      <p class="text-sm text-slate-500">Ładowanie…</p>
    }
  `,
})
export class PatientInfoComponent implements OnDestroy {
  protected readonly recorder = inject(AudioRecordingService);
  private readonly api = inject(PatientsService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);

  protected readonly patient = signal<Patient | null>(null);
  protected readonly notes = signal<PatientNote[]>([]);
  protected readonly loadError = signal<string | null>(null);
  protected readonly saving = signal(false);
  protected readonly saveMessage = signal<string | null>(null);
  protected readonly draft = signal('');
  protected readonly dictated = signal(false);
  protected readonly savingNote = signal(false);

  protected readonly age = computed(() => ageFromBirthDate(this.patient()?.birth_date ?? null));
  protected readonly elapsed = computed(() => formatDuration(this.recorder.elapsedSeconds()));

  protected readonly form = this.fb.nonNullable.group({
    first_name: ['', [Validators.required, Validators.maxLength(100)]],
    last_name: ['', [Validators.required, Validators.maxLength(100)]],
    birth_date: [''],
    icd_code: [''],
    diagnosis: [''],
    description: [''],
  });

  private readonly patientId = Number(this.route.snapshot.paramMap.get('id'));

  constructor() {
    this.api.get(this.patientId).subscribe({
      next: (patient) => {
        this.patient.set(patient);
        this.form.reset({
          first_name: patient.first_name,
          last_name: patient.last_name,
          birth_date: patient.birth_date ?? '',
          icd_code: patient.icd_code ?? '',
          diagnosis: patient.diagnosis ?? '',
          description: patient.description ?? '',
        });
      },
      error: () => this.loadError.set('Nie znaleziono pacjenta lub brak dostępu.'),
    });
    this.api.notes(this.patientId).subscribe({ next: (notes) => this.notes.set(notes) });
  }

  ngOnDestroy(): void {
    this.recorder.cancel();
  }

  protected save(): void {
    if (this.form.invalid || this.saving()) {
      return;
    }
    const v = this.form.getRawValue();
    this.saving.set(true);
    this.saveMessage.set(null);
    this.api
      .update(this.patientId, {
        first_name: v.first_name.trim(),
        last_name: v.last_name.trim(),
        birth_date: emptyToNull(v.birth_date),
        icd_code: emptyToNull(v.icd_code),
        diagnosis: emptyToNull(v.diagnosis),
        description: emptyToNull(v.description),
      })
      .subscribe({
        next: (patient) => {
          this.patient.set(patient);
          this.form.markAsPristine();
          this.saving.set(false);
          this.saveMessage.set('Zapisano zmiany.');
        },
        error: () => {
          this.saving.set(false);
          this.saveMessage.set('Nie udało się zapisać zmian.');
        },
      });
  }

  protected async stopDictation(): Promise<void> {
    const text = await this.recorder.stopAndTranscribe('pl');
    if (text) {
      this.draft.update((current) => (current.trim() ? `${current.trimEnd()}\n${text}` : text));
      this.dictated.set(true);
    }
  }

  protected addNote(): void {
    const content = this.draft().trim();
    if (!content || this.savingNote()) {
      return;
    }
    const source: NoteSource = this.dictated() ? 'dictated' : 'typed';
    this.savingNote.set(true);
    this.api.addNote(this.patientId, content, source).subscribe({
      next: (note) => {
        this.notes.update((list) => [note, ...list]);
        this.draft.set('');
        this.dictated.set(false);
        this.savingNote.set(false);
      },
      error: () => this.savingNote.set(false),
    });
  }

  protected removeNote(note: PatientNote): void {
    if (!confirm('Usunąć tę notatkę?')) {
      return;
    }
    this.api.removeNote(this.patientId, note.id).subscribe({
      next: () => this.notes.update((list) => list.filter((n) => n.id !== note.id)),
    });
  }

  protected removePatient(): void {
    if (!confirm('Usunąć pacjenta wraz ze wszystkimi notatkami? Tej operacji nie można cofnąć.')) {
      return;
    }
    this.api.remove(this.patientId).subscribe({
      next: () => void this.router.navigate(['/dashboard']),
    });
  }
}
