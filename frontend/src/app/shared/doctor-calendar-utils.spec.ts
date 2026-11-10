import { freeSlots, initials, layoutLanes, patientColor, textOn } from './doctor-calendar-utils';

describe('doctor-calendar-utils', () => {
  it('inicjały i stały kolor pacjenta wg identyfikatora', () => {
    expect(initials('Zofia Wiśniewska')).toBe('ZW');
    expect(initials('Jan Maria Rokita')).toBe('JR');
    expect(initials('Ola')).toBe('OL');
    expect(patientColor(7)).toBe(patientColor(13));
    expect(patientColor(7)).not.toBe(patientColor(8));
  });

  it('kontrast tekstu na tle koloru pacjenta', () => {
    expect(textOn('#f59e0b')).toBe('#0f172a'); // jasny bursztyn → ciemny tekst
    expect(textOn('#8b5cf6')).toBe('#ffffff');
  });

  it('nakładające się wydarzenia dostają osobne tory w grupie', () => {
    const lanes = layoutLanes([
      { id: 'a', start: 540, end: 600 },
      { id: 'b', start: 570, end: 630 },
      { id: 'c', start: 660, end: 700 },
    ]);
    const byId = Object.fromEntries(lanes.map((l) => [l.id, [l.lane, l.lanes]]));
    expect(byId['a']).toEqual([0, 2]);
    expect(byId['b']).toEqual([1, 2]);
    expect(byId['c']).toEqual([0, 1]);
  });

  it('wolne terminy omijają zajęte godziny, weekend i przeszłość', () => {
    const monday = new Date(2026, 10, 9); // pon 9.11.2026
    const at = (h: number, m = 0) => new Date(2026, 10, 9, h, m);
    const slots = freeSlots([{ start: at(8), end: at(9, 30) }], monday, 1, 8, 11, 45, 10, new Date(2026, 10, 1));
    expect(slots.map((s) => `${s.start.getHours()}:${String(s.start.getMinutes()).padStart(2, '0')}`)).toEqual(['9:30', '10:15']);

    const saturday = new Date(2026, 10, 14);
    expect(freeSlots([], saturday, 2, 8, 18, 45, 10, new Date(2026, 10, 1))).toEqual([]);
    const past = freeSlots([], monday, 1, 8, 10, 60, 10, at(9, 10));
    expect(past.map((s) => s.start.getHours() * 60 + s.start.getMinutes())).toEqual([]);
  });
});
