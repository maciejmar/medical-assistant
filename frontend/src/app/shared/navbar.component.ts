import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { AuthService } from '../core/auth.service';

@Component({
  selector: 'app-navbar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
      <div class="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3">
        <a [routerLink]="auth.homeRoute()" class="flex items-center gap-3 text-brand-700" aria-label="Logoped Assistant – strona główna">
          <img src="assets/images/logopedic-logo-384.png" alt="" width="120" height="120" class="h-[120px] w-[120px] rounded-full bg-white object-cover ring-1 ring-slate-200" />
          <span class="flex flex-col leading-tight">
            <span class="text-2xl font-bold">Logoped</span>
            <span class="text-sm font-medium tracking-wide text-brand-600">Assistant</span>
          </span>
        </a>

        <button
          type="button"
          class="btn-secondary sm:hidden"
          [attr.aria-expanded]="open()"
          aria-label="Menu"
          (click)="open.set(!open())"
        >
          ☰
        </button>

        <nav
          class="absolute left-0 right-0 top-full flex-col gap-1 border-b border-slate-200 bg-white p-3 sm:static sm:flex sm:flex-row sm:items-center sm:gap-2 sm:border-0 sm:p-0"
          [class.hidden]="!open()"
          [class.flex]="open()"
        >
          @if (auth.canTreat()) {
            <a routerLink="/dashboard" routerLinkActive="bg-brand-50 text-brand-700" class="rounded-lg px-3 py-2 text-sm font-medium hover:bg-slate-100" (click)="open.set(false)">Pacjenci</a>
            <a routerLink="/chat" routerLinkActive="bg-brand-50 text-brand-700" class="rounded-lg px-3 py-2 text-sm font-medium hover:bg-slate-100" (click)="open.set(false)">Asystent</a>
          }
          @if (auth.isAdmin()) {
            <a routerLink="/admin" routerLinkActive="bg-brand-50 text-brand-700" [routerLinkActiveOptions]="{ exact: true }" class="rounded-lg px-3 py-2 text-sm font-medium hover:bg-slate-100" (click)="open.set(false)">Panel administratora</a>
            <a routerLink="/admin/knowledge" routerLinkActive="bg-brand-50 text-brand-700" class="rounded-lg px-3 py-2 text-sm font-medium hover:bg-slate-100" (click)="open.set(false)">Baza wiedzy</a>
            <a routerLink="/admin/llm" routerLinkActive="bg-brand-50 text-brand-700" class="rounded-lg px-3 py-2 text-sm font-medium hover:bg-slate-100" (click)="open.set(false)">Log LLM</a>
          }
          @if (auth.isPatient()) {
            <a routerLink="/patient" routerLinkActive="bg-brand-50 text-brand-700" class="rounded-lg px-3 py-2 text-sm font-medium hover:bg-slate-100" (click)="open.set(false)">Mój panel</a>
          }
          <span class="px-3 py-1 text-xs text-slate-500 sm:ml-2">{{ auth.user()?.full_name }}</span>
          <button type="button" class="btn-secondary" (click)="auth.logout()">Wyloguj</button>
          <a href="https://webaby.io" target="_blank" rel="noopener noreferrer" class="px-3 py-1 sm:ml-3 sm:border-l sm:border-slate-200 sm:pl-5" aria-label="Webaby – twórca aplikacji">
            <img src="assets/images/webabylogo-mark.png" alt="Webaby" width="34" height="48" class="h-12 w-auto opacity-80 transition hover:opacity-100" />
          </a>
        </nav>
      </div>
    </header>
  `,
})
export class NavbarComponent {
  protected readonly auth = inject(AuthService);
  protected readonly open = signal(false);
}
