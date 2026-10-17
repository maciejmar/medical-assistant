import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, Input, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { PatientsService } from '../../core/patients.service';
import { PatientAccount, PatientNotification, Recommendation } from '../../shared/models';
import { emptyToNull } from '../../shared/utils';

function apiError(err: unknown, fallback: string): string {
  if (err instanceof HttpErrorResponse && typeof err.error?.detail === 'string') {
    return err.error.detail;
  }
  return fallback;
}

/** Konto pacjenta, zalecenia widoczne w panelu pacjenta i powiadomienia e-mail. */
@Component({
  selector: 'app-patient-care',
  standalone: true,
  imports: [ReactiveFormsModule, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="mt-6 grid gap-6 lg:grid-cols-2">
      <section class="card space-y-4">
        <h2 class="font-semibold">Konto pacjenta</h2>
        @if (account(); as a) {
          <div class="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-brand-50 px-3 py-2 text-sm">
            <span>
              <strong>{{ a.full_name }}</strong> · {{ a.email }}
              @if (!a.is_active) { <span class="badge ml-1 bg-slate-200 text-slate-600">zablokowane</span> }
            </span>
            <button type="button" class="btn-secondary !px-2 !py-1 !text-xs" (click)="unlink()">Odłącz konto</button>
          </div>
          <p class="text-xs text-slate-500">Pacjent widzi w swoim panelu rozpoznanie, zalecenia i powiadomienia. Notatki z sesji pozostają prywatne.</p>
        } @else {
          <p class="text-sm text-slate-500">
            Pacjent nie ma jeszcze konta. Podaj e-mail – jeśli konto pacjenta istnieje, zostanie powiązane;
            w przeciwnym razie powstanie nowe z podanym hasłem początkowym.
          </p>
          <form class="grid gap-3 sm:grid-cols-2" [formGroup]="accountForm" (ngSubmit)="link()">
            <div>
              <label class="label" for="acc-email">E-mail pacjenta</label>
              <input id="acc-email" class="field" type="email" formControlName="email" />
            </div>
            <div>
              <label class="label" for="acc-password">Hasło początkowe</label>
              <input id="acc-password" class="field" type="password" autocomplete="new-password" formControlName="password" placeholder="tylko dla nowego konta" />
            </div>
            <div class="flex items-center justify-end gap-3 sm:col-span-2">
              @if (accountError()) {
                <span class="mr-auto text-sm text-red-600">{{ accountError() }}</span>
              }
              <button type="submit" class="btn-primary" [disabled]="accountForm.invalid || busy()">Utwórz / powiąż konto</button>
            </div>
          </form>
        }
      </section>

      <section class="card space-y-4">
        <h2 class="font-semibold">Powiadomienie e-mail</h2>
        <form class="space-y-3" [formGroup]="notifyForm" (ngSubmit)="notify()">
          <div>
            <label class="label" for="n-subject">Temat</label>
            <input id="n-subject" class="field" formControlName="subject" maxlength="200" />
          </div>
          <div>
            <label class="label" for="n-body">Treść</label>
            <textarea id="n-body" class="field" rows="3" formControlName="body" maxlength="20000"></textarea>
          </div>
          <div class="flex items-center justify-end gap-3">
            @if (notifyMessage()) {
              <span class="mr-auto text-sm" [class.text-red-600]="notifyFailed()" [class.text-brand-700]="!notifyFailed()">{{ notifyMessage() }}</span>
            }
            <button type="submit" class="btn-primary" [disabled]="!account() || notifyForm.invalid || busy()">Wyślij</button>
          </div>
          @if (!account()) {
            <p class="text-xs text-slate-500">Wysyłka wymaga powiązanego konta pacjenta.</p>
          }
        </form>
        @if (notifications().length) {
          <ul class="max-h-56 space-y-2 overflow-auto text-sm">
            @for (n of notifications(); track n.id) {
              <li class="rounded-lg border border-slate-200 px-3 py-2">
                <div class="flex items-center justify-between gap-2 text-xs text-slate-500">
                  <span>{{ n.created_at | date: 'dd.MM.yyyy HH:mm' }} · {{ n.recipient }}</span>
                  <span class="badge" [class]="n.status === 'sent' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'" [attr.title]="n.error">
                    {{ n.status === 'sent' ? 'wysłano' : 'błąd wysyłki' }}
                  </span>
                </div>
                <p class="font-medium">{{ n.subject }}</p>
              </li>
            }
          </ul>
        }
      </section>
    </div>

    <section class="card mt-6">
      <h2 class="mb-4 font-semibold">Zalecenia i wskazania do leczenia ({{ recommendations().length }})</h2>
      <form class="mb-4 space-y-3 rounded-lg border border-dashed border-slate-300 p-3" [formGroup]="recForm" (ngSubmit)="saveRecommendation()">
        <div>
          <label class="label" for="r-title">{{ editingId() ? 'Edytuj zalecenie' : 'Nowe zalecenie' }}</label>
          <input id="r-title" class="field" formControlName="title" placeholder="np. Ćwiczenia pionizacji języka" maxlength="200" />
        </div>
        <textarea class="field" rows="4" formControlName="content" placeholder="Opis ćwiczeń, częstotliwość, zalecenia domowe…" maxlength="20000" aria-label="Treść zalecenia"></textarea>
        <div class="flex flex-wrap items-center justify-end gap-3">
          <label class="mr-auto flex items-center gap-2 text-sm" [class.opacity-50]="!account()">
            <input type="checkbox" formControlName="notify" />
            Powiadom pacjenta e-mailem
          </label>
          @if (editingId()) {
            <button type="button" class="btn-secondary" (click)="cancelEdit()">Anuluj</button>
          }
          <button type="submit" class="btn-primary" [disabled]="recForm.invalid || busy()">{{ editingId() ? 'Zapisz zmiany' : 'Dodaj zalecenie' }}</button>
        </div>
      </form>

      @if (recommendations().length === 0) {
        <p class="text-sm text-slate-500">Brak zaleceń.</p>
      }
      <ul class="space-y-3">
        @for (r of recommendations(); track r.id) {
          <li class="rounded-lg border border-slate-200 p-3">
            <div class="mb-1 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
              <span>{{ r.updated_at | date: 'dd.MM.yyyy HH:mm' }}</span>
              <span class="flex gap-3">
                <button type="button" class="hover:text-brand-700" (click)="edit(r)">Edytuj</button>
                <button type="button" class="hover:text-red-600" (click)="removeRecommendation(r)">Usuń</button>
              </span>
            </div>
            <p class="font-semibold">{{ r.title }}</p>
            <p class="whitespace-pre-wrap text-sm">{{ r.content }}</p>
          </li>
        }
      </ul>
    </section>
  `,
})
export class PatientCareComponent implements OnInit {
  @Input({ required: true }) patientId!: number;

  private readonly api = inject(PatientsService);
  private readonly fb = inject(FormBuilder);

  protected readonly account = signal<PatientAccount | null>(null);
  protected readonly recommendations = signal<Recommendation[]>([]);
  protected readonly notifications = signal<PatientNotification[]>([]);
  protected readonly busy = signal(false);
  protected readonly accountError = signal<string | null>(null);
  protected readonly notifyMessage = signal<string | null>(null);
  protected readonly notifyFailed = signal(false);
  protected readonly editingId = signal<number | null>(null);

  protected readonly accountForm = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.minLength(8), Validators.maxLength(72)]],
  });

  protected readonly notifyForm = this.fb.nonNullable.group({
    subject: ['', [Validators.required, Validators.maxLength(200)]],
    body: ['', [Validators.required]],
  });

  protected readonly recForm = this.fb.nonNullable.group({
    title: ['', [Validators.required, Validators.maxLength(200)]],
    content: ['', [Validators.required]],
    notify: [false],
  });

  ngOnInit(): void {
    this.api.account(this.patientId).subscribe({ next: (a) => this.account.set(a) });
    this.api.recommendations(this.patientId).subscribe({ next: (r) => this.recommendations.set(r) });
    this.loadNotifications();
  }

  protected link(): void {
    const v = this.accountForm.getRawValue();
    this.busy.set(true);
    this.accountError.set(null);
    this.api
      .linkAccount(this.patientId, {
        email: v.email.trim(),
        full_name: null,
        password: emptyToNull(v.password),
      })
      .subscribe({
        next: (account) => {
          this.account.set(account);
          this.accountForm.reset();
          this.busy.set(false);
        },
        error: (err: unknown) => {
          this.busy.set(false);
          this.accountError.set(apiError(err, 'Nie udało się powiązać konta.'));
        },
      });
  }

  protected unlink(): void {
    if (!confirm('Odłączyć konto od karty? Pacjent straci dostęp do zaleceń.')) {
      return;
    }
    this.api.unlinkAccount(this.patientId).subscribe({ next: () => this.account.set(null) });
  }

  protected notify(): void {
    const v = this.notifyForm.getRawValue();
    this.busy.set(true);
    this.notifyMessage.set(null);
    this.api.sendNotification(this.patientId, v.subject.trim(), v.body.trim()).subscribe({
      next: (n) => {
        this.busy.set(false);
        this.notifications.update((list) => [n, ...list]);
        this.notifyFailed.set(n.status !== 'sent');
        this.notifyMessage.set(
          n.status === 'sent' ? 'Wysłano.' : `Nie wysłano e-maila: ${n.error ?? 'błąd SMTP'}`,
        );
        if (n.status === 'sent') {
          this.notifyForm.reset();
        }
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.notifyFailed.set(true);
        this.notifyMessage.set(apiError(err, 'Nie udało się wysłać powiadomienia.'));
      },
    });
  }

  protected saveRecommendation(): void {
    const v = this.recForm.getRawValue();
    const input = {
      title: v.title.trim(),
      content: v.content.trim(),
      notify: v.notify && !!this.account(),
    };
    const editing = this.editingId();
    const request = editing
      ? this.api.updateRecommendation(this.patientId, editing, input)
      : this.api.addRecommendation(this.patientId, input);
    this.busy.set(true);
    request.subscribe({
      next: (saved) => {
        this.recommendations.update((list) =>
          editing ? list.map((r) => (r.id === saved.id ? saved : r)) : [saved, ...list],
        );
        this.cancelEdit();
        this.busy.set(false);
        if (input.notify) {
          this.loadNotifications();
        }
      },
      error: () => this.busy.set(false),
    });
  }

  protected edit(recommendation: Recommendation): void {
    this.editingId.set(recommendation.id);
    this.recForm.reset({ title: recommendation.title, content: recommendation.content, notify: false });
  }

  protected cancelEdit(): void {
    this.editingId.set(null);
    this.recForm.reset({ title: '', content: '', notify: false });
  }

  protected removeRecommendation(recommendation: Recommendation): void {
    if (!confirm('Usunąć to zalecenie?')) {
      return;
    }
    this.api.removeRecommendation(this.patientId, recommendation.id).subscribe({
      next: () =>
        this.recommendations.update((list) => list.filter((r) => r.id !== recommendation.id)),
    });
  }

  private loadNotifications(): void {
    this.api.notifications(this.patientId).subscribe({ next: (n) => this.notifications.set(n) });
  }
}
