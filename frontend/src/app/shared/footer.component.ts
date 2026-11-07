import { ChangeDetectionStrategy, Component } from '@angular/core';

/**
 * Stopka całej aplikacji (stała, 48 px – na tej wysokości opiera się położenie grafiki tła
 * w .page-bg-dashboard). Logo Webaby jest czarne na przezroczystym tle, więc na ciemnej stopce
 * odwracamy je do bieli filtrem CSS (`invert`).
 */
@Component({
  selector: 'app-footer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <footer class="fixed inset-x-0 bottom-0 z-10 flex h-12 items-center justify-between gap-3 bg-[#02121c] px-4 text-xs text-slate-300">
      <div class="flex min-w-0 items-center gap-2">
        <a href="https://webaby.io" target="_blank" rel="noopener noreferrer" class="shrink-0" aria-label="Webaby – strona firmy">
          <img src="assets/images/webabylogo-mark.png" alt="Webaby" width="20" height="28" class="h-7 w-auto invert" />
        </a>
        <p class="truncate">
          © {{ year }} Webaby<span class="hidden sm:inline">. Wszelkie prawa zastrzeżone.</span>
        </p>
      </div>

      <div class="flex shrink-0 items-center gap-4">
        <a href="https://webaby.io" target="_blank" rel="noopener noreferrer" class="hidden font-medium text-slate-200 transition hover:text-white md:inline">webaby.io</a>
        <a href="mailto:contact@webaby.io" class="font-medium text-slate-200 transition hover:text-white">
          <span class="hidden sm:inline">contact&#64;webaby.io</span>
          <span class="sm:hidden" aria-label="Napisz: contact@webaby.io">Kontakt</span>
        </a>
        <span class="hidden h-4 w-px bg-slate-600 sm:block" aria-hidden="true"></span>
        <div class="hidden items-center gap-4 sm:flex">
          <a href="#" target="_blank" rel="noopener noreferrer" aria-label="WhatsApp" class="text-slate-300 transition hover:text-white">
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.288.173-1.413-.074-.124-.272-.198-.57-.347z" />
              <path d="M12.04 2C6.52 2 2.04 6.48 2.04 12c0 1.86.51 3.6 1.4 5.1l-1.48 5.4 5.54-1.45c1.45.8 3.08 1.25 4.54 1.25 5.52 0 10-4.48 10-10S17.56 2 12.04 2zm0 18.2c-1.5 0-2.97-.4-4.25-1.16l-.3-.18-3.28.86.88-3.21-.2-.33A8.19 8.19 0 0 1 3.84 12c0-4.56 3.72-8.28 8.3-8.28 4.57 0 8.28 3.72 8.28 8.28 0 4.57-3.71 8.3-8.28 8.3z" />
            </svg>
          </a>
          <a href="#" target="_blank" rel="noopener noreferrer" aria-label="Facebook" class="text-slate-300 transition hover:text-white">
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M22.675 0h-21.35C.593 0 0 .592 0 1.325v21.351C0 23.408.593 24 1.325 24H12.82v-9.294H9.692v-3.622h3.128V8.413c0-3.1 1.893-4.788 4.659-4.788 1.325 0 2.464.099 2.795.143v3.24l-1.918.001c-1.504 0-1.795.715-1.795 1.763v2.313h3.587l-.467 3.622h-3.12V24h6.116C23.407 24 24 23.408 24 22.676V1.325C24 .592 23.407 0 22.675 0z" />
            </svg>
          </a>
          <a href="#" target="_blank" rel="noopener noreferrer" aria-label="Instagram" class="text-slate-300 transition hover:text-white">
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072c-4.358.2-6.78 2.618-6.98 6.98C.014 8.332 0 8.74 0 12s.014 3.668.072 4.948c.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24s3.668-.014 4.948-.072c4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 1 0 0 12.324 6.162 6.162 0 0 0 0-12.324zM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm6.406-11.845a1.44 1.44 0 1 0 0 2.881 1.44 1.44 0 0 0 0-2.881z" />
            </svg>
          </a>
          <a href="#" target="_blank" rel="noopener noreferrer" aria-label="X (Twitter)" class="text-slate-300 transition hover:text-white">
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231 5.451-6.231zm-1.161 17.52h1.833L7.084 4.126H5.117l11.966 15.644z" />
            </svg>
          </a>
        </div>
      </div>
    </footer>
  `,
})
export class FooterComponent {
  protected readonly year = new Date().getFullYear();
}
