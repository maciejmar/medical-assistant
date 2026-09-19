import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-register',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="mx-auto mt-10 w-full max-w-md">
      <form class="card space-y-4" [formGroup]="form" (ngSubmit)="submit()">
        <h2 class="text-lg font-semibold">Rejestracja lekarza</h2>

        @if (error()) {
          <div class="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ error() }}</div>
        }

        <div>
          <label class="label" for="name">Imię i nazwisko</label>
          <input id="name" class="field" type="text" autocomplete="name" formControlName="fullName" />
        </div>
        <div>
          <label class="label" for="email">E-mail</label>
          <input id="email" class="field" type="email" autocomplete="username" formControlName="email" />
        </div>
        <div>
          <label class="label" for="password">Hasło (min. 8 znaków)</label>
          <input id="password" class="field" type="password" autocomplete="new-password" formControlName="password" />
        </div>
        <div>
          <label class="label" for="confirm">Powtórz hasło</label>
          <input id="confirm" class="field" type="password" autocomplete="new-password" formControlName="confirm" />
          @if (form.hasError('mismatch') && form.controls.confirm.touched) {
            <p class="mt-1 text-xs text-red-600">Hasła nie są takie same.</p>
          }
        </div>

        <button class="btn-primary w-full" type="submit" [disabled]="form.invalid || loading()">
          {{ loading() ? 'Tworzenie konta…' : 'Utwórz konto' }}
        </button>

        <p class="text-center text-sm text-slate-500">
          Masz już konto?
          <a routerLink="/login" class="font-semibold text-brand-700 hover:underline">Zaloguj się</a>
        </p>
      </form>
    </div>
  `,
})
export class RegisterComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);

  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly form = this.fb.nonNullable.group(
    {
      fullName: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(200)]],
      email: ['', [Validators.required, Validators.email]],
      password: ['', [Validators.required, Validators.minLength(8), Validators.maxLength(72)]],
      confirm: ['', [Validators.required]],
    },
    {
      validators: (group) =>
        group.get('password')?.value === group.get('confirm')?.value ? null : { mismatch: true },
    },
  );

  protected submit(): void {
    if (this.form.invalid || this.loading()) {
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    const { fullName, email, password } = this.form.getRawValue();
    this.auth.register(fullName.trim(), email, password).subscribe({
      next: () => void this.router.navigate([this.auth.homeRoute()]),
      error: (err: unknown) => {
        this.loading.set(false);
        this.error.set(
          err instanceof HttpErrorResponse && err.status === 409
            ? 'Konto z tym adresem e-mail już istnieje.'
            : 'Nie udało się utworzyć konta. Sprawdź dane i spróbuj ponownie.',
        );
      },
    });
  }
}
