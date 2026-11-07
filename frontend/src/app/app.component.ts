import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { AuthService } from './core/auth.service';
import { FooterComponent } from './shared/footer.component';
import { NavbarComponent } from './shared/navbar.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, NavbarComponent, FooterComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (auth.isAuthenticated()) {
      <app-navbar />
    }
    <!-- pb-16: miejsce na stałą stopkę (48 px), żeby nie zasłaniała końca treści -->
    <main class="mx-auto w-full max-w-7xl px-4 pb-16 pt-6">
      <router-outlet />
    </main>
    <app-footer />
  `,
})
export class AppComponent {
  protected readonly auth = inject(AuthService);
}
