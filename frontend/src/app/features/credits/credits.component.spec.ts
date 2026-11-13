import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { MyCredits } from '../../core/billing.service';
import { CreditsComponent } from './credits.component';

const DATA: MyCredits = {
  status: {
    started_at: '2026-10-14T09:00:00Z',
    window_start: '2026-11-14T09:00:00Z',
    window_end: '2026-12-14T09:00:00Z',
    limit_pln: 5,
    topups_pln: 0,
    available_pln: 5,
    used_pln: 5.25,
    remaining_pln: 0,
    limit_credits: 500,
    topups_credits: 0,
    available_credits: 500,
    used_credits: 525,
    remaining_credits: 0,
    percent: 100,
    exhausted: true,
  },
  topups: [],
  payment: { recipient: 'Webaby', bank_account: '12 3456 7890', amounts: [20, 50, 100], credits_per_pln: 100, online_enabled: true, online_methods: ['blik', 'card'] },
};

describe('CreditsComponent', () => {
  it('po wyczerpaniu ostrzega o tańszych modelach i przyjmuje zamówienie doładowania', () => {
    TestBed.configureTestingModule({
      imports: [CreditsComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
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

    // Klient widzi kredyty, nie złotówki; pakiety – cena w zł i liczba kredytów.
    expect(el.textContent).toContain('525 z 500 kredytów wykorzystano');
    expect(el.textContent).not.toContain('5,25');
    const amounts = Array.from(el.querySelectorAll('fieldset button')) as HTMLButtonElement[];
    expect(amounts.length).toBe(3);
    expect(amounts[0].textContent).toContain('2 000 kredytów');
    expect(amounts[0].textContent).toContain('20,00');
    expect(amounts[2].textContent).toContain('10 000 kredytów');
    amounts[1].click();
    fixture.detectChanges();
    expect(el.textContent).toContain('BLIK, karta');
    const transfer = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Przelew tradycyjny'))!;
    transfer.click();
    const order = http.expectOne('/api/billing/topups');
    expect(order.request.body).toEqual({ amount_pln: 50 });
    order.flush({ id: 7, user_id: 3, amount_pln: 50, status: 'pending', reference: 'LOGOPED-3-7', note: '', created_at: '', confirmed_at: null });
    http.expectOne('/api/billing/me').flush({ ...DATA, topups: [] });
    fixture.detectChanges();
    expect(el.textContent).toContain('LOGOPED-3-7');
    expect(el.textContent).toContain('12 3456 7890');
  });
});

describe('CreditsComponent – płatność online', () => {
  it('przekierowuje na stronę operatora dla wybranej kwoty', () => {
    TestBed.configureTestingModule({
      imports: [CreditsComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    const fixture = TestBed.createComponent(CreditsComponent);
    const redirects: string[] = [];
    (fixture.componentInstance as unknown as { redirect: (u: string) => void }).redirect = (u) => redirects.push(u);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne('/api/billing/me').flush({
      ...DATA,
      payment: { ...DATA.payment, online_enabled: true, online_methods: ['blik'] },
    });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    (el.querySelectorAll('fieldset button')[0] as HTMLButtonElement).click();
    fixture.detectChanges();
    Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Zapłać online'))!.click();
    const req = http.expectOne('/api/billing/checkout');
    expect(req.request.body).toEqual({ amount_pln: 20 });
    req.flush({ topup_id: 1, url: 'https://checkout.stripe.com/c/pay/cs_test_1' });
    expect(redirects).toEqual(['https://checkout.stripe.com/c/pay/cs_test_1']);
  });
});
