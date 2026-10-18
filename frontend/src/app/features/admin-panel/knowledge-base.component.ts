import { DatePipe, DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AdminService } from '../../core/admin.service';
import { KbAudience, KbCategory, KbDocument, KbImportStatus } from '../../shared/models';

const ACCEPT = '.pdf,.docx,.odt,.md,.txt,.jpg,.jpeg,.png';
const POLL_MS = 3000;

export const CATEGORY_LABELS: Record<KbCategory, string> = {
  technique: 'Techniki terapii',
  disorder: 'Jednostki chorobowe',
  diagnostics: 'Diagnostyka',
  icd: 'Klasyfikacja ICD',
};

export const AUDIENCE_LABELS: Record<KbAudience, string> = {
  all: 'Wszyscy',
  children: 'Dzieci',
  adults: 'Dorośli',
};

const SUPPORTED_EXTENSIONS = ACCEPT.split(',');

function isSupportedFile(name: string): boolean {
  const lower = name.toLowerCase();
  return !lower.startsWith('.') && SUPPORTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

function apiError(err: unknown, fallback: string): string {
  if (err instanceof HttpErrorResponse && typeof err.error?.detail === 'string') {
    return err.error.detail;
  }
  if (err instanceof HttpErrorResponse && err.status === 413) {
    return 'Plik jest zbyt duży (limit 20 MB).';
  }
  return fallback;
}

@Component({
  selector: 'app-knowledge-base',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink, DatePipe, DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="mb-6">
      <a routerLink="/admin" class="mb-1 inline-block text-sm text-brand-700 hover:underline">← Panel administratora</a>
      <h1 class="text-2xl font-bold">Baza wiedzy</h1>
      <p class="text-sm text-slate-500">
        Materiały RAG: dzielone na fragmenty, indeksowane w Qdrant i od razu dostępne dla asystenta (z cytowaniem w źródłach).
        Wbudowanych haseł: {{ builtin() }}.
      </p>
    </div>

    <section class="card mb-6">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 class="font-semibold">Katalog z materiałami</h2>
          <p class="text-sm text-slate-500">
            Wgraj folder z materiałami poniżej (folder = jeden dokument ze zdjęć) albo skopiuj pliki na serwer.
            Nowe i zmienione pliki są wykrywane i indeksowane automatycznie; zdjęcia stron przechodzą OCR (tylko druk).
          </p>
          @if (importStatus(); as st) {
            <p class="mt-1 text-xs text-slate-500">
              Katalog na serwerze: <code>{{ st.source_dir }}</code>
              @if (!st.source_available) { <span class="badge ml-1 bg-red-100 text-red-700">niedostępny</span> }
              @if (st.auto_scan_seconds > 0) { · automatyczne sprawdzanie co {{ st.auto_scan_seconds / 60 | number: '1.0-0' }} min }
            </p>
          }
        </div>
        <button type="button" class="btn-primary" [disabled]="importStatus()?.running || !importStatus()?.source_available" (click)="startImport()">
          {{ importStatus()?.running ? 'Synchronizacja trwa…' : 'Synchronizuj katalog' }}
        </button>
      </div>
      @if (importStatus(); as st) {
        @if (st.running) {
          <p class="mt-3 animate-pulse text-sm text-brand-700">{{ st.current || 'Przygotowanie…' }}</p>
          <p class="text-xs text-slate-500">Pierwszy import zdjęć potrwa długo (OCR kilka sekund na stronę). Możesz zamknąć tę stronę – import działa w tle.</p>
        } @else if (st.finished_at) {
          <p class="mt-3 text-sm" [class.text-red-600]="st.error" [class.text-brand-700]="!st.error">
            Ostatnia synchronizacja {{ st.finished_at | date: 'dd.MM.yyyy HH:mm' }}: {{ st.error || st.summary }}
          </p>
          @for (f of st.failed; track f) {
            <p class="text-xs text-red-600">{{ f }}</p>
          }
        }
      }

      <div class="mt-4 rounded-lg border border-dashed border-slate-300 p-3">
        <label class="label" for="kb-folder">Wgraj folder z komputera</label>
        <div class="flex flex-wrap items-center gap-3">
          <input id="kb-folder" #folderInput class="field max-w-md" type="file" webkitdirectory multiple
                 [disabled]="folderUploading()" (change)="pickFolder(folderInput.files)" />
          <button type="button" class="btn-primary" [disabled]="!folderFiles().length || folderUploading() || !importStatus()?.source_available"
                  (click)="uploadFolder(folderInput)">
            {{ folderUploading() ? 'Wysyłanie…' : 'Wyślij na serwer i zaindeksuj' }}
          </button>
        </div>
        @if (folderFiles().length) {
          <p class="mt-2 text-xs text-slate-500">
            {{ folderFiles().length }} plików ({{ folderMegabytes() | number: '1.0-1' }} MB)
            @if (folderSkipped()) { · pominięto nieobsługiwanych: {{ folderSkipped() }} }
          </p>
        }
        @if (folderUploading() || folderDone()) {
          <div class="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div class="h-full bg-brand-600 transition-all" [style.width.%]="folderProgress()"></div>
          </div>
          <p class="mt-1 text-xs text-slate-500">
            {{ folderDone() }} / {{ folderTotal() }}
            @if (folderErrors().length) { · błędy: {{ folderErrors().length }} }
          </p>
          @for (e of folderErrors(); track e) {
            <p class="text-xs text-red-600">{{ e }}</p>
          }
        }
      </div>
    </section>

    <form class="card mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" [formGroup]="form" (ngSubmit)="upload(fileInput)">
      <div class="sm:col-span-2">
        <label class="label" for="kb-file">Pojedynczy plik (PDF z tekstem, DOCX, ODT, MD, TXT, zdjęcie strony · do 20 MB)</label>
        <input id="kb-file" #fileInput class="field" type="file" [accept]="accept" (change)="pickFile(fileInput.files)" />
      </div>
      <div class="sm:col-span-2">
        <label class="label" for="kb-title">Tytuł (widoczny w źródłach odpowiedzi)</label>
        <input id="kb-title" class="field" formControlName="title" maxlength="300" />
      </div>
      <div>
        <label class="label" for="kb-category">Kategoria</label>
        <select id="kb-category" class="field" formControlName="category">
          @for (c of categories; track c) {
            <option [value]="c">{{ categoryLabels[c] }}</option>
          }
        </select>
      </div>
      <div>
        <label class="label" for="kb-audience">Dotyczy</label>
        <select id="kb-audience" class="field" formControlName="audience">
          @for (a of audiences; track a) {
            <option [value]="a">{{ audienceLabels[a] }}</option>
          }
        </select>
      </div>
      <div>
        <label class="label" for="kb-icd10">ICD-10 (opcjonalnie)</label>
        <input id="kb-icd10" class="field" formControlName="icd10" placeholder="np. F80.0" maxlength="50" />
      </div>
      <div>
        <label class="label" for="kb-icd11">ICD-11 (opcjonalnie)</label>
        <input id="kb-icd11" class="field" formControlName="icd11" maxlength="50" />
      </div>
      <div class="sm:col-span-2 lg:col-span-3">
        <label class="label" for="kb-tags">Słowa kluczowe (pomagają w wyszukiwaniu)</label>
        <input id="kb-tags" class="field" formControlName="tags" placeholder="np. miofunkcjonalna, połykanie, ssanie" maxlength="500" />
      </div>
      <div class="flex items-end">
        <button type="submit" class="btn-primary w-full" [disabled]="!file() || form.invalid || uploading()">
          {{ uploading() ? 'Indeksowanie…' : 'Wgraj i zaindeksuj' }}
        </button>
      </div>
      @if (message()) {
        <p class="text-sm sm:col-span-2 lg:col-span-4" [class.text-red-600]="failed()" [class.text-brand-700]="!failed()">{{ message() }}</p>
      }
      <p class="text-xs text-slate-500 sm:col-span-2 lg:col-span-4">
        Skany PDF bez warstwy tekstowej (np. z CamScannera) nie są obsługiwane – użyj zdjęć stron (katalog) albo transkrypcji .md.
        Z obrazów odczytywany jest tylko druk. Nie wgrywaj materiałów z danymi pacjentów.
      </p>
    </form>

    <section class="card">
      <div class="mb-3 flex items-center justify-between gap-2">
        <h2 class="font-semibold">Materiały w bazie ({{ documents().length }})</h2>
        <button type="button" class="btn-secondary !px-2 !py-1 !text-xs" (click)="load()">Odśwież</button>
      </div>
      @if (documents().length === 0) {
        <p class="text-sm text-slate-500">Brak materiałów – zsynchronizuj katalog lub wgraj plik.</p>
      }
      <ul class="space-y-3">
        @for (d of documents(); track d.id) {
          <li class="rounded-lg border border-slate-200 p-3">
            <div class="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p class="font-semibold">{{ d.title }}</p>
                <p class="text-xs text-slate-500">
                  {{ d.source_path ?? d.filename }}
                  @if (d.pages) { ({{ d.pages }} zdjęć) }
                  · {{ categoryLabels[d.category] }} · {{ audienceLabels[d.audience] }}
                  @if (d.icd10) { · ICD-10 {{ d.icd10 }} }
                  · {{ d.characters | number }} znaków · {{ d.chunks }} fragm. · {{ d.created_at | date: 'dd.MM.yyyy HH:mm' }}
                </p>
              </div>
              <div class="flex items-center gap-2">
                <span class="badge" [class]="statusClass(d)">{{ statusLabel(d) }}</span>
                <button type="button" class="btn-secondary !px-2 !py-1 !text-xs" [disabled]="busyId() === d.id" (click)="edit(d)">Edytuj</button>
                <button type="button" class="btn-secondary !px-2 !py-1 !text-xs" [disabled]="busyId() === d.id" (click)="reindex(d)">Indeksuj ponownie</button>
                <button type="button" class="btn-danger !px-2 !py-1 !text-xs" [disabled]="busyId() === d.id" (click)="remove(d)">Usuń</button>
              </div>
            </div>
            @if (d.error) {
              <p class="mt-2 text-xs text-red-600">{{ d.error }}</p>
            }
            @if (editingId() === d.id) {
              <form class="mt-3 grid gap-3 rounded-lg border border-dashed border-slate-300 p-3 sm:grid-cols-2 lg:grid-cols-4" [formGroup]="editForm" (ngSubmit)="saveEdit(d)">
                <div class="sm:col-span-2 lg:col-span-4">
                  <label class="label" [for]="'e-title-' + d.id">Tytuł</label>
                  <input [id]="'e-title-' + d.id" class="field" formControlName="title" maxlength="300" />
                </div>
                <div>
                  <label class="label" [for]="'e-cat-' + d.id">Kategoria</label>
                  <select [id]="'e-cat-' + d.id" class="field" formControlName="category">
                    @for (c of categories; track c) { <option [value]="c">{{ categoryLabels[c] }}</option> }
                  </select>
                </div>
                <div>
                  <label class="label" [for]="'e-aud-' + d.id">Dotyczy</label>
                  <select [id]="'e-aud-' + d.id" class="field" formControlName="audience">
                    @for (a of audiences; track a) { <option [value]="a">{{ audienceLabels[a] }}</option> }
                  </select>
                </div>
                <div>
                  <label class="label" [for]="'e-icd10-' + d.id">ICD-10</label>
                  <input [id]="'e-icd10-' + d.id" class="field" formControlName="icd10" maxlength="50" />
                </div>
                <div>
                  <label class="label" [for]="'e-icd11-' + d.id">ICD-11</label>
                  <input [id]="'e-icd11-' + d.id" class="field" formControlName="icd11" maxlength="50" />
                </div>
                <div class="sm:col-span-2 lg:col-span-3">
                  <label class="label" [for]="'e-tags-' + d.id">Słowa kluczowe</label>
                  <input [id]="'e-tags-' + d.id" class="field" formControlName="tags" maxlength="500" />
                </div>
                <div class="flex items-end gap-2">
                  <button type="button" class="btn-secondary" (click)="editingId.set(null)">Anuluj</button>
                  <button type="submit" class="btn-primary" [disabled]="editForm.invalid || busyId() === d.id">Zapisz</button>
                </div>
              </form>
            }
            <details class="mt-2">
              <summary class="cursor-pointer text-xs text-slate-500">Podgląd odczytanego tekstu</summary>
              <pre class="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-2 text-xs">{{ d.preview }}…</pre>
            </details>
          </li>
        }
      </ul>
    </section>
  `,
})
export class KnowledgeBaseComponent {
  private readonly api = inject(AdminService);

  protected readonly accept = ACCEPT;
  protected readonly categories = Object.keys(CATEGORY_LABELS) as KbCategory[];
  protected readonly audiences = Object.keys(AUDIENCE_LABELS) as KbAudience[];
  protected readonly categoryLabels = CATEGORY_LABELS;
  protected readonly audienceLabels = AUDIENCE_LABELS;

  protected readonly documents = signal<KbDocument[]>([]);
  protected readonly builtin = signal(0);
  protected readonly file = signal<File | null>(null);
  protected readonly uploading = signal(false);
  protected readonly busyId = signal<number | null>(null);
  protected readonly message = signal<string | null>(null);
  protected readonly failed = signal(false);
  protected readonly importStatus = signal<KbImportStatus | null>(null);
  protected readonly editingId = signal<number | null>(null);
  private pollTimer: ReturnType<typeof setTimeout> | null = null;

  protected readonly folderFiles = signal<File[]>([]);
  protected readonly folderSkipped = signal(0);
  protected readonly folderUploading = signal(false);
  protected readonly folderDone = signal(0);
  protected readonly folderTotal = signal(0);
  protected readonly folderErrors = signal<string[]>([]);
  protected readonly folderMegabytes = computed(
    () => this.folderFiles().reduce((sum, f) => sum + f.size, 0) / 1_000_000,
  );
  protected readonly folderProgress = computed(() =>
    this.folderTotal() ? (100 * this.folderDone()) / this.folderTotal() : 0,
  );

  protected readonly form = inject(FormBuilder).nonNullable.group({
    title: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(300)]],
    category: ['technique' as KbCategory, Validators.required],
    audience: ['all' as KbAudience, Validators.required],
    icd10: [''],
    icd11: [''],
    tags: [''],
  });

  protected readonly editForm = inject(FormBuilder).nonNullable.group({
    title: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(300)]],
    category: ['technique' as KbCategory, Validators.required],
    audience: ['all' as KbAudience, Validators.required],
    icd10: [''],
    icd11: [''],
    tags: [''],
  });

  constructor() {
    this.load();
    this.pollImport();
    inject(DestroyRef).onDestroy(() => this.stopPolling());
  }

  protected pickFolder(files: FileList | null): void {
    const all = Array.from(files ?? []);
    const supported = all.filter((f) => isSupportedFile(f.name));
    this.folderFiles.set(supported);
    this.folderSkipped.set(all.length - supported.length);
    this.folderDone.set(0);
    this.folderTotal.set(0);
    this.folderErrors.set([]);
  }

  /** Wysyła pliki po kolei (limit rozmiaru żądania), a na końcu uruchamia indeksowanie. */
  protected async uploadFolder(folderInput: HTMLInputElement): Promise<void> {
    const files = this.folderFiles();
    this.folderUploading.set(true);
    this.folderTotal.set(files.length);
    this.folderDone.set(0);
    this.folderErrors.set([]);
    for (const file of files) {
      const relativePath = file.webkitRelativePath || file.name;
      try {
        await firstValueFrom(this.api.storeKnowledgeFile(file, relativePath));
      } catch (err: unknown) {
        this.folderErrors.update((list) => [...list, `${relativePath}: ${apiError(err, 'błąd wysyłania')}`]);
      }
      this.folderDone.update((n) => n + 1);
    }
    this.folderUploading.set(false);
    this.folderFiles.set([]);
    folderInput.value = '';
    this.startImport();
  }

  protected startImport(): void {
    this.api.startImport().subscribe({
      next: (status) => {
        this.importStatus.set(status);
        this.pollImport();
      },
      error: (err: unknown) => {
        // Import już trwa – nowe pliki obejmie automatyczne wykrywanie zmian po jego zakończeniu.
        this.pollImport();
        if (!(err instanceof HttpErrorResponse && err.status === 409 && this.importStatus()?.running)) {
          this.failed.set(true);
          this.message.set(apiError(err, 'Nie udało się uruchomić synchronizacji.'));
        }
      },
    });
  }

  /** Odpytuje status co kilka sekund, dopóki import trwa; po zakończeniu odświeża listę. */
  private pollImport(): void {
    this.stopPolling();
    this.api.importStatus().subscribe({
      next: (status) => {
        const wasRunning = this.importStatus()?.running;
        this.importStatus.set(status);
        if (status.running) {
          this.pollTimer = setTimeout(() => this.pollImport(), POLL_MS);
        } else if (wasRunning) {
          this.load();
        }
      },
    });
  }

  private stopPolling(): void {
    if (this.pollTimer) {
      clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
  }

  protected edit(doc: KbDocument): void {
    this.editingId.set(doc.id);
    this.editForm.reset({
      title: doc.title,
      category: doc.category,
      audience: doc.audience,
      icd10: doc.icd10,
      icd11: doc.icd11,
      tags: doc.tags,
    });
  }

  protected saveEdit(doc: KbDocument): void {
    this.busyId.set(doc.id);
    this.api.updateKnowledge(doc.id, this.editForm.getRawValue()).subscribe({
      next: (updated) => {
        this.busyId.set(null);
        this.editingId.set(null);
        this.documents.update((list) => list.map((d) => (d.id === updated.id ? updated : d)));
      },
      error: () => this.busyId.set(null),
    });
  }

  protected load(): void {
    this.api.knowledgeBase().subscribe({
      next: (kb) => {
        this.documents.set(kb.documents);
        this.builtin.set(kb.builtin_documents);
      },
    });
  }

  protected pickFile(files: FileList | null): void {
    const file = files?.item(0) ?? null;
    this.file.set(file);
    if (file && !this.form.controls.title.value) {
      this.form.controls.title.setValue(file.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' '));
    }
  }

  protected upload(fileInput: HTMLInputElement): void {
    const file = this.file();
    if (!file || this.form.invalid || this.uploading()) {
      return;
    }
    const v = this.form.getRawValue();
    this.uploading.set(true);
    this.message.set(null);
    this.api.uploadKnowledge({ ...v, title: v.title.trim(), file }).subscribe({
      next: (doc) => {
        this.uploading.set(false);
        this.documents.update((list) => [doc, ...list]);
        this.failed.set(doc.status !== 'indexed');
        this.message.set(
          doc.status === 'indexed'
            ? `Zaindeksowano „${doc.title}” (${doc.chunks} fragm.).`
            : `Plik zapisano, ale indeksowanie nie powiodło się – użyj „Indeksuj ponownie”.`,
        );
        this.form.reset({ title: '', category: v.category, audience: v.audience, icd10: '', icd11: '', tags: '' });
        this.file.set(null);
        fileInput.value = '';
      },
      error: (err: unknown) => {
        this.uploading.set(false);
        this.failed.set(true);
        this.message.set(apiError(err, 'Nie udało się wgrać pliku.'));
      },
    });
  }

  protected reindex(doc: KbDocument): void {
    this.busyId.set(doc.id);
    this.api.reindexKnowledge(doc.id).subscribe({
      next: (updated) => {
        this.busyId.set(null);
        this.documents.update((list) => list.map((d) => (d.id === updated.id ? updated : d)));
      },
      error: () => this.busyId.set(null),
    });
  }

  protected remove(doc: KbDocument): void {
    const fromDirectory = doc.source_path
      ? '\n\nMateriał pochodzi z katalogu – wróci przy kolejnej synchronizacji, jeśli nie usuniesz go z katalogu.'
      : '';
    if (!confirm(`Usunąć „${doc.title}” z bazy wiedzy? Asystent przestanie z niego korzystać.${fromDirectory}`)) {
      return;
    }
    this.busyId.set(doc.id);
    this.api.deleteKnowledge(doc.id).subscribe({
      next: () => {
        this.busyId.set(null);
        this.documents.update((list) => list.filter((d) => d.id !== doc.id));
      },
      error: (err: unknown) => {
        this.busyId.set(null);
        this.failed.set(true);
        this.message.set(apiError(err, 'Nie udało się usunąć dokumentu.'));
      },
    });
  }

  protected statusLabel(doc: KbDocument): string {
    return { indexed: 'zaindeksowany', error: 'błąd indeksowania', pending: 'w toku' }[doc.status];
  }

  protected statusClass(doc: KbDocument): string {
    return {
      indexed: 'bg-green-100 text-green-700',
      error: 'bg-red-100 text-red-700',
      pending: 'bg-amber-100 text-amber-700',
    }[doc.status];
  }
}
