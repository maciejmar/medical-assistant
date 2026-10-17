import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideCharts, withDefaultRegisterables } from 'ng2-charts';
import { User } from '../../shared/models';
import { AdminPanelComponent } from './admin-panel.component';

const USERS: User[] = [
  { id: 2, email: 'pacjent@example.com', full_name: 'P', role: 'ROLE_PATIENT', is_active: true, created_at: '' },
  { id: 3, email: 'admin2@example.com', full_name: 'A', role: 'ROLE_ADMIN', is_active: true, created_at: '' },
  { id: 4, email: 'lekarz@example.com', full_name: 'L', role: 'ROLE_DOCTOR', is_active: true, created_at: '' },
];

describe('AdminPanelComponent', () => {
  it('lista ról w tabeli pokazuje faktyczną rolę konta', () => {
    TestBed.configureTestingModule({
      imports: [AdminPanelComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideCharts(withDefaultRegisterables()),
      ],
    });
    const fixture = TestBed.createComponent(AdminPanelComponent);
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/api/admin/users').flush(USERS);
    fixture.detectChanges();

    const selects = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLSelectElement>('select[aria-label^="Rola"]'),
    );
    expect(selects.map((s) => s.value)).toEqual(['ROLE_PATIENT', 'ROLE_ADMIN', 'ROLE_DOCTOR']);
  });
});
