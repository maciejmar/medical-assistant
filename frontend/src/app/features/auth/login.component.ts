import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="mx-auto mt-10 w-full max-w-md">
      <div class="mb-6 text-center">
        <div class="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-xl bg-brand-600 text-xl font-bold text-white">L</div>
        <h1 class="text-2xl font-bold">Logoped Assist</h1>
        <p class="text-sm text-slate-500">Asystent dla lekarzy logopedów</p>
      </div>

      <form class="card space-y-4" [formGroup]="form" (ngSubmit)="submit()">
        <h2 class="text-lg font-semibold">Logowanie</h2>

        @if (error()) {
          <div class="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ error() }}</div>
        }

        <div>
          <label class="label" for="email">E-mail</label>
          <input id="email" class="field" type="email" autocomplete="username" formControlName="email" />
        </div>
        <div>
          <label class="label" for="password">Hasło</label>
          <input id="password" class="field" type="password" autocomplete="current-password" formControlName="password" />
        </div>

        <button class="btn-primary w-full" type="submit" [disabled]="form.invalid || loading()">
          {{ loading() ? 'Logowanie…' : 'Zaloguj się' }}
        </button>

        <p class="text-center text-sm text-slate-500">
          Nie masz konta?
          <a routerLink="/register" class="font-semibold text-brand-700 hover:underline">Zarejestruj się</a>
        </p>
      </form>
    </div>
  `,
})
export class LoginComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);

  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required]],
  });

  protected submit(): void {
    if (this.form.invalid || this.loading()) {
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    const { email, password } = this.form.getRawValue();
    this.auth.login(email, password).subscribe({
      next: () => void this.router.navigate([this.auth.homeRoute()]),
      error: (err: unknown) => {
        this.loading.set(false);
        this.error.set(
          err instanceof HttpErrorResponse && err.status === 401
            ? 'Nieprawidłowy e-mail lub hasło.'
            : 'Nie udało się zalogować. Spróbuj ponownie.',
        );
      },
    });
  }
}
