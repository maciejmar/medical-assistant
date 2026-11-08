import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MyCredits } from '../../core/billing.service';
import { CreditsComponent } from './credits.component';

const DATA: MyCredits = {
  status: {
    started_at: '2026-10-14T09:00:00Z',
    window_start: '2026-11-14T09:00:00Z',
    window_end: '2026-12-14T09:00:00Z',
    limit_pln: 20,
    topups_pln: 0,
    available_pln: 20,
    used_pln: 21.5,
    remaining_pln: 0,
    percent: 100,
    exhausted: true,
  },
  topups: [],
  payment: { recipient: 'Webaby', bank_account: '12 3456 7890', amounts: [20, 50, 100] },
};

describe('CreditsComponent', () => {
  it('po wyczerpaniu ostrzega o tańszych modelach i przyjmuje zamówienie doładowania', () => {
    TestBed.configureTestingModule({
      imports: [CreditsComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const fixture = TestBed.createComponent(CreditsComponent);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne('/api/billing/me').flush(DATA);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;

    expect(el.textContent).toContain('przechodzimy na tańsze modele');
    expect(el.textContent).not.toMatch(/gemma|lokaln/i);
    const meter = el.querySelector('[role="progressbar"]')!;
    expect(meter.getAttribute('aria-valuenow')).toBe('100');

    const buttons = Array.from(el.querySelectorAll('button')).filter((b) => /zł/.test(b.textContent ?? ''));
    expect(buttons.length).toBe(3);
    buttons[1].click();
    const order = http.expectOne('/api/billing/topups');
    expect(order.request.body).toEqual({ amount_pln: 50 });
    order.flush({ id: 7, user_id: 3, amount_pln: 50, status: 'pending', reference: 'LOGOPED-3-7', note: '', created_at: '', confirmed_at: null });
    http.expectOne('/api/billing/me').flush({ ...DATA, topups: [] });
    fixture.detectChanges();
    expect(el.textContent).toContain('LOGOPED-3-7');
    expect(el.textContent).toContain('12 3456 7890');
  });
});
