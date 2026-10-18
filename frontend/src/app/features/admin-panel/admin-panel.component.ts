import { DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ChartConfiguration, ChartData } from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';
import { AdminService } from '../../core/admin.service';
import { AuthService } from '../../core/auth.service';
import { ROLE_LABELS, Role, SystemStats, UsageReport, User } from '../../shared/models';

const PALETTE = ['#237d75', '#4f7cff', '#f59e0b', '#e4572e', '#8b5cf6', '#14b8a6', '#64748b'];

@Component({
  selector: 'app-admin-panel',
  standalone: true,
  imports: [BaseChartDirective, DecimalPipe, ReactiveFormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="mb-6 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-2xl font-bold">Panel administratora</h1>
        <p class="text-sm text-slate-500">Metryki zużycia zasobów i zarządzanie kontami.</p>
      </div>
      <div class="flex items-center gap-2">
        <a routerLink="/admin/knowledge" class="btn-secondary">Baza wiedzy</a>
        <a routerLink="/admin/llm" class="btn-secondary">Log zapytań LLM</a>
        <label class="text-xs font-semibold uppercase text-slate-500" for="range">Zakres</label>
        <select id="range" class="field !w-auto" [value]="days()" (change)="setDays($any($event.target).value)">
          <option value="7">7 dni</option>
          <option value="30">30 dni</option>
          <option value="90">90 dni</option>
          <option value="365">365 dni</option>
        </select>
      </div>
    </div>

    @if (error()) {
      <div class="card mb-4 text-sm text-red-700">{{ error() }}</div>
    }

    <div class="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
      <div class="card !p-4">
        <p class="label">Tokeny łącznie</p>
        <p class="text-2xl font-bold">{{ usage()?.totals?.total_tokens ?? 0 | number }}</p>
      </div>
      <div class="card !p-4">
        <p class="label">Zapytania do modeli</p>
        <p class="text-2xl font-bold">{{ usage()?.totals?.requests ?? 0 | number }}</p>
      </div>
      <div class="card !p-4">
        <p class="label">Konta (aktywne / wszystkie)</p>
        <p class="text-2xl font-bold">{{ stats()?.users_active ?? 0 }} / {{ stats()?.users_total ?? 0 }}</p>
      </div>
      <div class="card !p-4">
        <p class="label">Dokumenty w bazie wiedzy</p>
        <p class="text-2xl font-bold">{{ stats()?.knowledge_base_documents ?? '—' }}</p>
      </div>
    </div>

    <div class="grid gap-6 lg:grid-cols-3">
      <section class="card lg:col-span-2">
        <h2 class="mb-3 font-semibold">Zużycie tokenów per dzień</h2>
        <div class="h-72"><canvas baseChart type="bar" [data]="dayChart()" [options]="stackedOptions"></canvas></div>
      </section>
      <section class="card">
        <h2 class="mb-3 font-semibold">Per model</h2>
        <div class="h-72"><canvas baseChart type="doughnut" [data]="modelChart()" [options]="doughnutOptions"></canvas></div>
      </section>
      <section class="card lg:col-span-2">
        <h2 class="mb-3 font-semibold">Per użytkownik</h2>
        <div class="h-72"><canvas baseChart type="bar" [data]="userChart()" [options]="horizontalOptions"></canvas></div>
      </section>
      <section class="card">
        <h2 class="mb-3 font-semibold">Per typ operacji</h2>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs uppercase text-slate-500"><th class="pb-2">Operacja</th><th class="pb-2 text-right">Zapytania</th><th class="pb-2 text-right">Tokeny</th></tr>
          </thead>
          <tbody>
            @for (o of usage()?.by_operation ?? []; track o.operation) {
              <tr class="border-t border-slate-100">
                <td class="py-2">{{ o.operation }}</td>
                <td class="py-2 text-right">{{ o.requests | number }}</td>
                <td class="py-2 text-right">{{ o.total_tokens | number }}</td>
              </tr>
            }
          </tbody>
        </table>
      </section>
    </div>

    <section class="card mt-6">
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 class="font-semibold">Konta użytkowników</h2>
        <button type="button" class="btn-primary" (click)="showCreate.set(!showCreate())">
          {{ showCreate() ? 'Zamknij' : 'Dodaj użytkownika' }}
        </button>
      </div>

      @if (showCreate()) {
        <form class="mb-4 grid gap-3 rounded-lg border border-slate-200 p-3 sm:grid-cols-2 lg:grid-cols-5" [formGroup]="createForm" (ngSubmit)="createUser()">
          <div class="lg:col-span-1">
            <label class="label" for="new-name">Imię i nazwisko</label>
            <input id="new-name" class="field" formControlName="full_name" />
          </div>
          <div class="lg:col-span-1">
            <label class="label" for="new-email">E-mail</label>
            <input id="new-email" class="field" type="email" formControlName="email" />
          </div>
          <div class="lg:col-span-1">
            <label class="label" for="new-password">Hasło (min. 8 znaków)</label>
            <input id="new-password" class="field" type="password" autocomplete="new-password" formControlName="password" />
          </div>
          <div class="lg:col-span-1">
            <label class="label" for="new-role">Rola</label>
            <select id="new-role" class="field" formControlName="role">
              @for (r of roles; track r) {
                <option [value]="r">{{ roleLabels[r] }}</option>
              }
            </select>
          </div>
          <div class="flex items-end lg:col-span-1">
            <button type="submit" class="btn-primary w-full" [disabled]="createForm.invalid || creating()">
              {{ creating() ? 'Zapisywanie…' : 'Utwórz konto' }}
            </button>
          </div>
          @if (createError()) {
            <p class="text-sm text-red-600 sm:col-span-2 lg:col-span-5">{{ createError() }}</p>
          }
          <p class="text-xs text-slate-500 sm:col-span-2 lg:col-span-5">
            Konto pacjenta powiąże z kartą pacjenta lekarz prowadzący (karta pacjenta → „Konto pacjenta”).
          </p>
        </form>
      }

      <div class="overflow-x-auto">
        <table class="w-full min-w-[36rem] text-sm">
          <thead>
            <tr class="text-left text-xs uppercase text-slate-500">
              <th class="pb-2">ID</th><th class="pb-2">Nazwa</th><th class="pb-2">E-mail</th><th class="pb-2">Rola</th><th class="pb-2">Status</th><th class="pb-2 text-right">Akcje</th>
            </tr>
          </thead>
          <tbody>
            @for (u of users(); track u.id) {
              <tr class="border-t border-slate-100">
                <td class="py-2">{{ u.id }}</td>
                <td class="py-2">{{ u.full_name }}</td>
                <td class="py-2">{{ u.email }}</td>
                <td class="py-2">
                  @if (u.id !== auth.user()?.id) {
                    <!-- [selected] na opcjach, nie [value] na select: opcje z @for powstają po
                         ustawieniu wartości selecta i przeglądarka pokazywałaby zawsze pierwszą -->
                    <select class="field !w-auto !py-1 !text-xs" [attr.aria-label]="'Rola ' + u.email" (change)="changeRole(u, $any($event.target))">
                      @for (r of roles; track r) {
                        <option [value]="r" [selected]="r === u.role">{{ roleLabels[r] }}</option>
                      }
                    </select>
                  } @else {
                    <span class="badge bg-purple-100 text-purple-700">{{ roleLabels[u.role] }}</span>
                  }
                </td>
                <td class="py-2">
                  <span class="badge" [class]="u.is_active ? 'bg-green-100 text-green-700' : 'bg-slate-200 text-slate-600'">
                    {{ u.is_active ? 'Aktywne' : 'Zablokowane' }}
                  </span>
                </td>
                <td class="py-2 text-right">
                  @if (u.id !== auth.user()?.id) {
                    <button type="button" class="btn-secondary !px-2 !py-1 !text-xs" (click)="toggleActive(u)">{{ u.is_active ? 'Zablokuj' : 'Odblokuj' }}</button>
                    <button type="button" class="btn-secondary ml-1 !px-2 !py-1 !text-xs" (click)="resetPassword(u)">Nowe hasło</button>
                    <button type="button" class="btn-danger ml-1 !px-2 !py-1 !text-xs" (click)="remove(u)">Usuń</button>
                  } @else {
                    <span class="text-xs text-slate-400">to Ty</span>
                  }
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    </section>
  `,
})
export class AdminPanelComponent {
  protected readonly auth = inject(AuthService);
  private readonly api = inject(AdminService);

  protected readonly days = signal(30);
  protected readonly usage = signal<UsageReport | null>(null);
  protected readonly stats = signal<SystemStats | null>(null);
  protected readonly users = signal<User[]>([]);
  protected readonly error = signal<string | null>(null);
  protected readonly showCreate = signal(false);
  protected readonly creating = signal(false);
  protected readonly createError = signal<string | null>(null);

  protected readonly roles: Role[] = ['ROLE_DOCTOR', 'ROLE_PATIENT', 'ROLE_ADMIN'];
  protected readonly roleLabels = ROLE_LABELS;

  protected readonly createForm = inject(FormBuilder).nonNullable.group({
    full_name: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(200)]],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(8), Validators.maxLength(72)]],
    role: ['ROLE_DOCTOR' as Role, [Validators.required]],
  });

  protected readonly dayChart = computed<ChartData<'bar'>>(() => {
    const rows = this.usage()?.by_day ?? [];
    return {
      labels: rows.map((r) => r.date),
      datasets: [
        { label: 'Prompt', data: rows.map((r) => r.prompt_tokens), backgroundColor: PALETTE[0] },
        { label: 'Completion', data: rows.map((r) => r.completion_tokens), backgroundColor: PALETTE[1] },
      ],
    };
  });

  protected readonly userChart = computed<ChartData<'bar'>>(() => {
    const rows = this.usage()?.by_user ?? [];
    return {
      labels: rows.map((r) => r.label),
      datasets: [{ label: 'Tokeny', data: rows.map((r) => r.total_tokens), backgroundColor: PALETTE[0] }],
    };
  });

  protected readonly modelChart = computed<ChartData<'doughnut'>>(() => {
    const rows = this.usage()?.by_model ?? [];
    return {
      labels: rows.map((r) => r.model_name),
      datasets: [
        {
          data: rows.map((r) => r.total_tokens),
          backgroundColor: rows.map((_, i) => PALETTE[i % PALETTE.length]),
        },
      ],
    };
  });

  protected readonly stackedOptions: ChartConfiguration<'bar'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } },
  };

  protected readonly horizontalOptions: ChartConfiguration<'bar'>['options'] = {
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: { x: { beginAtZero: true } },
  };

  protected readonly doughnutOptions: ChartConfiguration<'doughnut'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { position: 'bottom' } },
  };

  constructor() {
    this.loadUsage();
    this.api.stats().subscribe({ next: (s) => this.stats.set(s) });
    this.loadUsers();
  }

  protected setDays(value: string): void {
    this.days.set(Number(value));
    this.loadUsage();
  }

  protected toggleActive(user: User): void {
    this.api.updateUser(user.id, { is_active: !user.is_active }).subscribe({
      next: (updated) => this.replaceUser(updated),
      error: () => this.error.set('Nie udało się zmienić statusu konta.'),
    });
  }

  protected changeRole(user: User, select: HTMLSelectElement): void {
    const role = select.value as Role;
    if (!confirm(`Zmienić rolę ${user.email} na „${ROLE_LABELS[role]}”?`)) {
      select.value = user.role;
      return;
    }
    this.api.updateUser(user.id, { role }).subscribe({
      next: (updated) => this.replaceUser(updated),
      error: () => {
        select.value = user.role;
        this.error.set('Nie udało się zmienić roli.');
      },
    });
  }

  protected resetPassword(user: User): void {
    const password = prompt(`Nowe hasło dla ${user.email} (min. 8 znaków):`);
    if (password === null) {
      return;
    }
    if (password.length < 8 || password.length > 72) {
      this.error.set('Hasło musi mieć od 8 do 72 znaków.');
      return;
    }
    this.api.updateUser(user.id, { password }).subscribe({
      next: () => this.error.set(null),
      error: () => this.error.set('Nie udało się zmienić hasła.'),
    });
  }

  protected createUser(): void {
    if (this.createForm.invalid || this.creating()) {
      return;
    }
    const v = this.createForm.getRawValue();
    this.creating.set(true);
    this.createError.set(null);
    this.api
      .createUser({ ...v, email: v.email.trim(), full_name: v.full_name.trim() })
      .subscribe({
        next: (user) => {
          this.users.update((list) => [...list, user]);
          this.createForm.reset({ full_name: '', email: '', password: '', role: 'ROLE_DOCTOR' });
          this.creating.set(false);
          this.showCreate.set(false);
        },
        error: (err: unknown) => {
          this.creating.set(false);
          this.createError.set(
            err instanceof HttpErrorResponse && err.status === 409
              ? 'Konto z tym adresem e-mail już istnieje.'
              : 'Nie udało się utworzyć konta.',
          );
        },
      });
  }

  protected remove(user: User): void {
    if (!confirm(`Usunąć konto ${user.email} wraz z danymi pacjentów i czatów? Tej operacji nie można cofnąć.`)) {
      return;
    }
    this.api.deleteUser(user.id).subscribe({
      next: () => {
        this.users.update((list) => list.filter((u) => u.id !== user.id));
        this.loadUsage();
      },
      error: () => this.error.set('Nie udało się usunąć konta.'),
    });
  }

  private replaceUser(updated: User): void {
    this.users.update((list) => list.map((u) => (u.id === updated.id ? updated : u)));
  }

  private loadUsage(): void {
    this.api.usage(this.days()).subscribe({
      next: (report) => {
        this.usage.set(report);
        this.error.set(null);
      },
      error: () => this.error.set('Nie udało się pobrać statystyk zużycia.'),
    });
  }

  private loadUsers(): void {
    this.api.users().subscribe({ next: (users) => this.users.set(users) });
  }
}
