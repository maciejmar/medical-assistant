import { TestBed } from '@angular/core/testing';
import { CreditStatus } from '../core/billing.service';
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
  });
});
