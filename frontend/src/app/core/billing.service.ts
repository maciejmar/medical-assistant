import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

export interface CreditStatus {
  started_at: string;
  window_start: string;
  window_end: string;
  limit_pln: number;
  topups_pln: number;
  available_pln: number;
  used_pln: number;
  remaining_pln: number;
  percent: number;
  exhausted: boolean;
}

export interface TopUp {
  id: number;
  user_id: number;
  amount_pln: number;
  status: 'pending' | 'confirmed' | 'rejected' | 'cancelled';
  reference: string;
  note: string;
  created_at: string;
  confirmed_at: string | null;
}

export interface PaymentDetails {
  recipient: string;
  bank_account: string;
  amounts: number[];
}

export interface MyCredits {
  status: CreditStatus;
  topups: TopUp[];
  payment: PaymentDetails;
}

export interface UserCredits {
  user_id: number;
  email: string;
  full_name: string;
  role: string;
  status: CreditStatus;
}

const PLN = new Intl.NumberFormat('pl-PL', { style: 'currency', currency: 'PLN', minimumFractionDigits: 2 });

export function formatPln(value: number): string {
  return PLN.format(value);
}

/** Poziom wskaźnika: ok < 75% ≤ warn < 100% ≤ exhausted. */
export function creditLevel(status: CreditStatus): 'ok' | 'warn' | 'exhausted' {
  if (status.exhausted) {
    return 'exhausted';
  }
  return status.percent >= 75 ? 'warn' : 'ok';
}

export const EXHAUSTED_MESSAGE = 'Wykorzystano limit kredytów – przechodzimy na tańsze modele.';

@Injectable({ providedIn: 'root' })
export class BillingService {
  private readonly http = inject(HttpClient);

  /** Ostatnio pobrany stan kredytów zalogowanego użytkownika (wskaźnik w nawigacji, czat). */
  readonly mine = signal<MyCredits | null>(null);

  refresh(): void {
    this.http.get<MyCredits>('/api/billing/me').subscribe({
      next: (data) => this.mine.set(data),
      error: () => undefined,
    });
  }

  me(): Observable<MyCredits> {
    return this.http.get<MyCredits>('/api/billing/me').pipe(tap((data) => this.mine.set(data)));
  }

  orderTopUp(amount: number): Observable<TopUp> {
    return this.http.post<TopUp>('/api/billing/topups', { amount_pln: amount });
  }

  cancelTopUp(id: number): Observable<void> {
    return this.http.delete<void>(`/api/billing/topups/${id}`);
  }

  // --- administrator ---

  usersCredits(): Observable<UserCredits[]> {
    return this.http.get<UserCredits[]>('/api/admin/billing/users');
  }

  updateSubscription(userId: number, patch: { monthly_limit_pln?: number; started_at?: string }): Observable<CreditStatus> {
    return this.http.patch<CreditStatus>(`/api/admin/billing/users/${userId}`, patch);
  }

  topUps(status: string | null = 'pending'): Observable<TopUp[]> {
    const params: Record<string, string> = status ? { status_filter: status } : { status_filter: '' };
    return this.http.get<TopUp[]>('/api/admin/billing/topups', { params });
  }

  confirmTopUp(id: number): Observable<TopUp> {
    return this.http.post<TopUp>(`/api/admin/billing/topups/${id}/confirm`, {});
  }

  rejectTopUp(id: number): Observable<TopUp> {
    return this.http.post<TopUp>(`/api/admin/billing/topups/${id}/reject`, {});
  }

  manualTopUp(userId: number, amount: number, note: string): Observable<TopUp> {
    return this.http.post<TopUp>(`/api/admin/billing/users/${userId}/topups`, { amount_pln: amount, note });
  }
}
