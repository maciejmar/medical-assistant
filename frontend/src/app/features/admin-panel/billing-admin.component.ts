import { DatePipe } from '@angular/common';
import { Observable } from 'rxjs';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { BillingService, TopUp, UserCredits, formatPln } from '../../core/billing.service';
import { ROLE_LABELS, Role } from '../../shared/models';
import { CreditMeterComponent } from '../../shared/credit-meter.component';

/**
 * Kredyty kont (lekarze i administratorzy): wskaźnik wykorzystania w bieżącym oknie, limit
 * miesięczny i data startu subskrypcji (edycja), doładowanie ręczne oraz potwierdzanie wpłat.
 */
@Component({
  selector: 'app-billing-admin',
  standalone: true,
  imports: [DatePipe, CreditMeterComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (pending().length > 0) {
      <section class="card mt-6 border-amber-300" aria-labelledby="topups-heading">
        <h2 id="topups-heading" class="mb-3 font-semibold">Doładowania do potwierdzenia ({{ pending().length }})</h2>
        <p class="mb-3 text-xs text-slate-500">Potwierdź dopiero po zaksięgowaniu przelewu z podanym tytułem – kwota od razu powiększa limit bieżącego okna użytkownika.</p>
        <ul class="divide-y divide-slate-100 text-sm">
          @for (t of pending(); track t.id) {
            <li class="flex flex-wrap items-center gap-3 py-2">
              <span class="w-24 font-semibold tabular-nums">{{ pln(t.amount_pln) }}</span>
              <span class="min-w-0 flex-1">{{ userName(t.user_id) }}</span>
              <span class="font-mono text-xs text-slate-600">{{ t.reference }}</span>
              <span class="text-xs text-slate-500">{{ t.created_at | date: 'dd.MM.yyyy HH:mm' }}</span>
              <button type="button" class="btn-primary !px-3 !py-1 !text-xs" [disabled]="busy()" (click)="decide(t, true)">Wpłata zaksięgowana</button>
              <button type="button" class="btn-secondary !px-3 !py-1 !text-xs" [disabled]="busy()" (click)="decide(t, false)">Odrzuć</button>
            </li>
          }
        </ul>
      </section>
    }

    <section class="card mt-6" aria-labelledby="credits-heading">
      <h2 id="credits-heading" class="mb-1 font-semibold">Kredyty użytkowników</h2>
      <p class="mb-3 text-xs text-slate-500">
        Okno rozliczeniowe: miesiąc od daty startu subskrypcji – limit zeruje się automatycznie z początkiem nowego okna.
        Po wyczerpaniu kredytów czat odpowiada modelem zastępczym (lokalnym), a użytkownik widzi komunikat o tańszych modelach.
      </p>
      @if (error(); as e) {
        <p class="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ e }}</p>
      }
      <div class="overflow-x-auto">
        <table class="w-full min-w-[52rem] text-sm">
          <thead>
            <tr class="text-left text-xs uppercase text-slate-500">
              <th class="pb-2">Użytkownik</th>
              <th class="pb-2">Wykorzystanie</th>
              <th class="pb-2">Okno (odnowienie)</th>
              <th class="pb-2">Limit / mies.</th>
              <th class="pb-2">Start subskrypcji</th>
              <th class="pb-2 text-right">Doładuj</th>
            </tr>
          </thead>
          <tbody>
            @for (u of users(); track u.user_id) {
              <tr class="border-t border-slate-100 align-middle">
                <td class="py-2 pr-3">
                  <span class="block font-medium">{{ u.full_name }}</span>
                  <span class="block text-xs text-slate-500">{{ u.email }} · {{ roleLabel(u.role) }}</span>
                </td>
                <td class="w-56 py-2 pr-3">
                  <app-credit-meter [status]="u.status" unit="pln" />
                  @if (u.status.exhausted) {
                    <span class="mt-1 inline-block text-[11px] font-semibold text-red-600">Model zastępczy</span>
                  }
                </td>
                <td class="py-2 pr-3 text-xs text-slate-600">
                  {{ u.status.window_start | date: 'dd.MM' }} – {{ u.status.window_end | date: 'dd.MM.yyyy' }}
                </td>
                <td class="py-2 pr-3">
                  <div class="flex items-center gap-1">
                    <input type="number" min="0" step="1" class="field !w-20 !py-1 !text-xs" [value]="u.status.limit_pln" #limit [attr.aria-label]="'Limit miesięczny ' + u.email" />
                    <span class="text-xs text-slate-500">zł</span>
                    <button type="button" class="btn-secondary !px-2 !py-1 !text-xs" [disabled]="busy()" (click)="saveLimit(u, limit.value)">Zapisz</button>
                  </div>
                </td>
                <td class="py-2 pr-3">
                  <input type="date" class="field !w-36 !py-1 !text-xs" [value]="dateValue(u.status.started_at)" (change)="saveStart(u, $any($event.target).value)" [attr.aria-label]="'Start subskrypcji ' + u.email" />
                </td>
                <td class="py-2 text-right">
                  <div class="flex items-center justify-end gap-1">
                    <input type="number" min="1" step="1" class="field !w-20 !py-1 !text-xs" placeholder="zł" #topup [attr.aria-label]="'Kwota doładowania ' + u.email" />
                    <button type="button" class="btn-secondary !px-2 !py-1 !text-xs" [disabled]="busy()" (click)="manual(u, topup)">Dodaj</button>
                  </div>
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    </section>
  `,
})
export class BillingAdminComponent implements OnInit {
  private readonly api = inject(BillingService);

  protected readonly users = signal<UserCredits[]>([]);
  protected readonly pending = signal<TopUp[]>([]);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  private readonly names = computed(() => new Map(this.users().map((u) => [u.user_id, `${u.full_name} (${u.email})`])));

  ngOnInit(): void {
    this.load();
  }

  protected pln(value: number): string {
    return formatPln(value);
  }

  protected roleLabel(role: string): string {
    return ROLE_LABELS[role as Role] ?? role;
  }

  protected userName(id: number): string {
    return this.names().get(id) ?? `Użytkownik #${id}`;
  }

  /** Data startu w czasie lokalnym (RRRR-MM-DD) do pola typu date. */
  protected dateValue(iso: string): string {
    const d = new Date(iso);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  protected saveLimit(u: UserCredits, value: string): void {
    const limit = Number(value);
    if (!Number.isFinite(limit) || limit < 0) {
      return;
    }
    this.run(this.api.updateSubscription(u.user_id, { monthly_limit_pln: limit }));
  }

  protected saveStart(u: UserCredits, value: string): void {
    if (!value) {
      return;
    }
    const [y, m, d] = value.split('-').map(Number);
    this.run(this.api.updateSubscription(u.user_id, { started_at: new Date(y, m - 1, d).toISOString() }));
  }

  protected manual(u: UserCredits, input: HTMLInputElement): void {
    const amount = Number(input.value);
    if (!Number.isFinite(amount) || amount <= 0) {
      return;
    }
    if (!confirm(`Doładować konto ${u.full_name} kwotą ${this.pln(amount)}?`)) {
      return;
    }
    input.value = '';
    this.run(this.api.manualTopUp(u.user_id, amount, 'doładowanie przez administratora'));
  }

  protected decide(t: TopUp, confirmed: boolean): void {
    const question = confirmed
      ? `Potwierdzić wpłatę ${this.pln(t.amount_pln)} (${t.reference})?`
      : `Odrzucić zamówienie ${t.reference}?`;
    if (confirm(question)) {
      this.run(confirmed ? this.api.confirmTopUp(t.id) : this.api.rejectTopUp(t.id));
    }
  }

  private run(request: Observable<unknown>): void {
    this.busy.set(true);
    this.error.set(null);
    request.subscribe({
      next: () => {
        this.busy.set(false);
        this.load();
        this.api.refresh();
      },
      error: () => {
        this.busy.set(false);
        this.error.set('Nie udało się zapisać zmian.');
      },
    });
  }

  private load(): void {
    this.api.usersCredits().subscribe({
      next: (users) => this.users.set(users),
      error: () => this.error.set('Nie udało się wczytać kredytów użytkowników.'),
    });
    this.api.topUps('pending').subscribe({ next: (t) => this.pending.set(t) });
  }
}
