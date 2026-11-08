import { dayKey, monthGrid, monthTitle, toIso } from './calendar-utils';

describe('calendar-utils', () => {
  it('siatka miesiąca zaczyna się w poniedziałek i obejmuje pełne tygodnie', () => {
    const grid = monthGrid(new Date(2026, 10, 15)); // listopad 2026: 1.11 to niedziela
    expect(grid.length % 7).toBe(0);
    expect(grid[0].getDay()).toBe(1);
    expect(dayKey(grid[0])).toBe('2026-10-26');
    expect(grid[grid.length - 1].getDay()).toBe(0);
    expect(dayKey(grid[grid.length - 1])).toBe('2026-12-06');
  });

  it('tytuł miesiąca po polsku, wielką literą', () => {
    expect(monthTitle(new Date(2026, 10, 1))).toBe('Listopad 2026');
  });

  it('data i godzina z formularza to czas lokalny', () => {
    const iso = toIso('2026-11-12', '10:30');
    const back = new Date(iso);
    expect(dayKey(back)).toBe('2026-11-12');
    expect(back.getHours()).toBe(10);
    expect(back.getMinutes()).toBe(30);
  });
});
