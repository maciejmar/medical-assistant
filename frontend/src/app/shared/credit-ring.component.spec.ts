import { TestBed } from '@angular/core/testing';
import { CreditStatus, creditsWord, formatCredits } from '../core/billing.service';
import { CreditRingComponent, percentLabel } from './credit-ring.component';

function status(used: number, available: number): CreditStatus {
  return {
    started_at: '',
    window_start: '',
    window_end: '',
    limit_pln: available,
    topups_pln: 0,
    available_pln: available,
    used_pln: used,
    remaining_pln: Math.max(0, available - used),
    limit_credits: available * 100,
    topups_credits: 0,
    available_credits: available * 100,
    used_credits: used * 100,
    remaining_credits: Math.max(0, available - used) * 100,
    percent: Math.min(100, (100 * used) / available),
    exhausted: used >= available,
  };
}

describe('CreditRingComponent', () => {
  it('etykieta procentu: śladowe zużycie jako „<1%”', () => {
    expect(percentLabel(0)).toBe('0%');
    expect(percentLabel(0.05)).toBe('<1%');
    expect(percentLabel(44.6)).toBe('45%');
    expect(percentLabel(100)).toBe('100%');
  });

  it('łuk proporcjonalny do zużycia, kolor wg poziomu i opis dostępności z kwotami', () => {
    TestBed.configureTestingModule({ imports: [CreditRingComponent] });
    const fixture = TestBed.createComponent(CreditRingComponent);
    fixture.componentInstance.status = status(16, 20);
    fixture.componentInstance.size = 40;
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const arc = el.querySelectorAll('circle')[1];
    const circumference = Number(arc.getAttribute('stroke-dasharray'));
    expect(Number(arc.getAttribute('stroke-dashoffset'))).toBeCloseTo(circumference * 0.2, 3);
    expect(arc.getAttribute('class')).toContain('stroke-amber-500');
    expect(el.querySelector('text')!.textContent).toBe('80%');
    expect(el.querySelector('svg')!.getAttribute('aria-label')).toContain('Wykorzystano 80%');
    expect(el.querySelector('svg')!.getAttribute('aria-label')).toContain('1 600 z 2 000 kredytów');
  });
});

describe('formatCredits', () => {
  it('odmienia i grupuje tysiące', () => {
    expect([1, 2, 4, 5, 12, 22, 25, 500].map(creditsWord)).toEqual([
      'kredyt', 'kredyty', 'kredyty', 'kredytów', 'kredytów', 'kredyty', 'kredytów', 'kredytów',
    ]);
    expect(formatCredits(500)).toBe('500 kredytów');
    expect(formatCredits(2000)).toBe('2 000 kredytów');
    expect(formatCredits(1234567, false)).toBe('1 234 567');
  });
});
