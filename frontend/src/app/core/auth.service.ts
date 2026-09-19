import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, map, tap } from 'rxjs';
import { TokenResponse, User } from '../shared/models';

const TOKEN_KEY = 'logoped.token';
const USER_KEY = 'logoped.user';

function tokenExpired(token: string): boolean {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return typeof payload.exp !== 'number' || payload.exp * 1000 <= Date.now();
  } catch {
    return true;
  }
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);

  private readonly tokenSignal = signal<string | null>(null);
  private readonly userSignal = signal<User | null>(null);

  readonly token = this.tokenSignal.asReadonly();
  readonly user = this.userSignal.asReadonly();
  readonly isAuthenticated = computed(() => !!this.tokenSignal() && !!this.userSignal());
  readonly isAdmin = computed(() => this.userSignal()?.role === 'ROLE_ADMIN');
  readonly isDoctor = computed(() => this.userSignal()?.role === 'ROLE_DOCTOR');

  constructor() {
    this.restoreSession();
  }

  login(email: string, password: string): Observable<User> {
    return this.http
      .post<TokenResponse>('/api/auth/login', { email, password })
      .pipe(tap((r) => this.storeSession(r)), map((r) => r.user));
  }

  register(fullName: string, email: string, password: string): Observable<User> {
    return this.http
      .post<TokenResponse>('/api/auth/register', { full_name: fullName, email, password })
      .pipe(tap((r) => this.storeSession(r)), map((r) => r.user));
  }

  logout(): void {
    this.clearSession();
    void this.router.navigate(['/login']);
  }

  homeRoute(): string {
    return this.isAdmin() ? '/admin' : '/dashboard';
  }

  private storeSession(response: TokenResponse): void {
    this.tokenSignal.set(response.access_token);
    this.userSignal.set(response.user);
    try {
      localStorage.setItem(TOKEN_KEY, response.access_token);
      localStorage.setItem(USER_KEY, JSON.stringify(response.user));
    } catch {
      /* przechowywanie niedostępne – sesja działa tylko w pamięci */
    }
  }

  private restoreSession(): void {
    try {
      const token = localStorage.getItem(TOKEN_KEY);
      const rawUser = localStorage.getItem(USER_KEY);
      if (token && rawUser && !tokenExpired(token)) {
        this.tokenSignal.set(token);
        this.userSignal.set(JSON.parse(rawUser) as User);
      } else {
        this.clearSession();
      }
    } catch {
      this.clearSession();
    }
  }

  private clearSession(): void {
    this.tokenSignal.set(null);
    this.userSignal.set(null);
    try {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    } catch {
      /* ignorujemy */
    }
  }
}
