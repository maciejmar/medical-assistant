import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ChartConfiguration, ChartData } from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';
import { AdminService } from '../../core/admin.service';
import { AuthService } from '../../core/auth.service';
import { SystemStats, UsageReport, User } from '../../shared/models';

const PALETTE = ['#237d75', '#4f7cff', '#f59e0b', '#e4572e', '#8b5cf6', '#14b8a6', '#64748b'];

@Component({
  selector: 'app-admin-panel',
  standalone: true,
  imports: [BaseChartDirective, DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="mb-6 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-2xl font-bold">Panel administratora</h1>
        <p class="text-sm text-slate-500">Zanonimizowane metryki zużycia zasobów. Brak wglądu w dane medyczne.</p>
      </div>
      <div class="flex items-center gap-2">
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
        <p class="label">Lekarze (aktywni / wszyscy)</p>
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
      <h2 class="mb-3 font-semibold">Konta użytkowników</h2>
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
                  <span class="badge" [class]="u.role === 'ROLE_ADMIN' ? 'bg-purple-100 text-purple-700' : 'bg-brand-50 text-brand-700'">
                    {{ u.role === 'ROLE_ADMIN' ? 'Admin' : 'Lekarz' }}
                  </span>
                </td>
                <td class="py-2">
                  <span class="badge" [class]="u.is_active ? 'bg-green-100 text-green-700' : 'bg-slate-200 text-slate-600'">
                    {{ u.is_active ? 'Aktywne' : 'Zablokowane' }}
                  </span>
                </td>
                <td class="py-2 text-right">
                  @if (u.id !== auth.user()?.id) {
                    <button type="button" class="btn-secondary !px-2 !py-1 !text-xs" (click)="toggleActive(u)">{{ u.is_active ? 'Zablokuj' : 'Odblokuj' }}</button>
                    <button type="button" class="btn-secondary ml-1 !px-2 !py-1 !text-xs" (click)="toggleRole(u)">{{ u.role === 'ROLE_ADMIN' ? 'Zmień na lekarza' : 'Nadaj admina' }}</button>
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

  protected toggleRole(user: User): void {
    const role = user.role === 'ROLE_ADMIN' ? 'ROLE_DOCTOR' : 'ROLE_ADMIN';
    if (!confirm(`Zmienić rolę użytkownika ${user.email}?`)) {
      return;
    }
    this.api.updateUser(user.id, { role }).subscribe({
      next: (updated) => this.replaceUser(updated),
      error: () => this.error.set('Nie udało się zmienić roli.'),
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
