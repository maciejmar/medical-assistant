import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { AuthService } from '../../core/auth.service';
import { PortalService } from '../../core/portal.service';
import { PatientPortal } from '../../shared/models';
import { ageFromBirthDate } from '../../shared/utils';

@Component({
  selector: 'app-patient-home',
  standalone: true,
  imports: [DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="dashboard-page">
      <div class="page-bg-dashboard"></div>
      <div class="mb-6">
        <h1 class="text-2xl font-bold">Dzień dobry, {{ auth.user()?.full_name }}</h1>
        <p class="text-sm text-slate-500">Twoje informacje i zalecenia od logopedy.</p>
      </div>

      @if (data(); as d) {
        <div class="grid gap-6 lg:grid-cols-3">
          <section class="card space-y-3">
            <h2 class="font-semibold">Informacje</h2>
            <dl class="space-y-2 text-sm">
              <div>
                <dt class="label">Pacjent</dt>
                <dd>{{ d.first_name }} {{ d.last_name }}@if (age() !== null) {, {{ age() }} lat}</dd>
              </div>
              <div>
                <dt class="label">Rozpoznanie</dt>
                <dd>{{ d.diagnosis || '—' }}@if (d.icd_code) { <span class="badge ml-1 bg-brand-50 text-brand-700">{{ d.icd_code }}</span> }</dd>
              </div>
              <div>
                <dt class="label">Logopeda prowadzący</dt>
                <dd>{{ d.doctor_name }}<br /><a class="text-brand-700 hover:underline" [href]="'mailto:' + d.doctor_email">{{ d.doctor_email }}</a></dd>
              </div>
            </dl>
          </section>

          <section class="card lg:col-span-2">
            <h2 class="mb-4 font-semibold">Zalecenia i wskazania do terapii</h2>
            @if (d.recommendations.length === 0) {
              <p class="text-sm text-slate-500">Logopeda nie dodał jeszcze zaleceń.</p>
            }
            <ul class="space-y-3">
              @for (r of d.recommendations; track r.id) {
                <li class="rounded-lg border border-slate-200 bg-white/70 p-3">
                  <div class="mb-1 text-xs text-slate-500">{{ r.updated_at | date: 'dd.MM.yyyy' }}</div>
                  <p class="font-semibold">{{ r.title }}</p>
                  <p class="whitespace-pre-wrap text-sm">{{ r.content }}</p>
                </li>
              }
            </ul>
          </section>

          <section class="card lg:col-span-3">
            <h2 class="mb-4 font-semibold">Powiadomienia</h2>
            @if (d.notifications.length === 0) {
              <p class="text-sm text-slate-500">Brak powiadomień.</p>
            }
            <ul class="space-y-3">
              @for (n of d.notifications; track n.id) {
                <li class="rounded-lg border border-slate-200 bg-white/70 p-3">
                  <div class="mb-1 text-xs text-slate-500">{{ n.created_at | date: 'dd.MM.yyyy HH:mm' }}</div>
                  <p class="font-semibold">{{ n.subject }}</p>
                  <p class="whitespace-pre-wrap text-sm">{{ n.body }}</p>
                </li>
              }
            </ul>
          </section>
        </div>
      } @else if (error()) {
        <div class="card text-sm text-slate-700">{{ error() }}</div>
      } @else {
        <p class="text-sm text-slate-500">Ładowanie…</p>
      }
    </div>
  `,
})
export class PatientHomeComponent {
  protected readonly auth = inject(AuthService);
  private readonly api = inject(PortalService);

  protected readonly data = signal<PatientPortal | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly age = computed(() => ageFromBirthDate(this.data()?.birth_date ?? null));

  constructor() {
    this.api.me().subscribe({
      next: (d) => this.data.set(d),
      error: (err: unknown) =>
        this.error.set(
          err instanceof HttpErrorResponse && err.status === 404
            ? 'Twoje konto nie zostało jeszcze powiązane z kartą pacjenta. Skontaktuj się z logopedą.'
            : 'Nie udało się pobrać danych.',
        ),
    });
  }
}
