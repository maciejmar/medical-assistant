/** Pomocnicze funkcje zbiorczego kalendarza lekarza (czas lokalny). */

/**
 * Paleta pacjentów – ta sama zweryfikowana paleta kategorialna co w wykresach (stała kolejność,
 * rozróżnialna przy daltonizmie). Kolor zależy od identyfikatora pacjenta (nie od pozycji na liście),
 * więc nie zmienia się przy filtrowaniu; przy > 6 pacjentach kolory się powtarzają, ale pacjenta
 * zawsze identyfikują też inicjały – kolor nigdy nie jest jedynym nośnikiem informacji.
 */
export const PATIENT_COLORS = ['#0d9488', '#4f7cff', '#f59e0b', '#e4572e', '#8b5cf6', '#db2777'] as const;

/** Typy zajmujące czas lekarza (konsultacje u innych specjalistów i etapy terapii – nie). */
export const BLOCKING_TYPES = new Set(['visit', 'other']);

export const DEFAULT_DURATION_MIN = 45;

export function patientColor(patientId: number): string {
  return PATIENT_COLORS[Math.abs(patientId) % PATIENT_COLORS.length];
}

/** Kolor tekstu na tle koloru pacjenta (jasne tła – ciemny tekst). */
export function textOn(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return luminance > 0.36 ? '#0f172a' : '#ffffff';
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return '?';
  }
  const first = parts[0][0] ?? '';
  const last = parts.length > 1 ? parts[parts.length - 1][0] : (parts[0][1] ?? '');
  return (first + last).toUpperCase();
}

export function startOfWeek(date: Date): Date {
  const offset = (date.getDay() + 6) % 7;
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() - offset);
}

export function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

export interface TimedBlock {
  start: number; // minuty od północy
  end: number;
}

/**
 * Układ nakładających się wydarzeń w kolumnie dnia: każde dostaje tor (lane) i liczbę torów
 * w swojej grupie nakładań – szerokość bloku = 1 / lanes.
 */
export function layoutLanes<T extends TimedBlock>(blocks: T[]): (T & { lane: number; lanes: number })[] {
  const sorted = [...blocks].sort((a, b) => a.start - b.start || a.end - b.end);
  const result: (T & { lane: number; lanes: number })[] = [];
  let group: (T & { lane: number; lanes: number })[] = [];
  let groupEnd = -1;
  const flush = () => {
    const lanes = Math.max(1, ...group.map((g) => g.lane + 1));
    group.forEach((g) => (g.lanes = lanes));
    result.push(...group);
    group = [];
  };
  for (const block of sorted) {
    if (group.length && block.start >= groupEnd) {
      flush();
      groupEnd = -1;
    }
    const taken = new Set(group.filter((g) => g.end > block.start).map((g) => g.lane));
    let lane = 0;
    while (taken.has(lane)) {
      lane++;
    }
    group.push({ ...block, lane, lanes: 1 });
    groupEnd = Math.max(groupEnd, block.end);
  }
  if (group.length) {
    flush();
  }
  return result;
}

export interface FreeSlot {
  start: Date;
  end: Date;
}

/**
 * Wolne terminy: dni robocze (pon–pt), godziny pracy [workStart, workEnd), sloty co 15 min
 * o zadanej długości, niekolidujące z zajętymi przedziałami i nie w przeszłości.
 */
export function freeSlots(
  busy: { start: Date; end: Date }[],
  from: Date,
  days: number,
  workStart: number,
  workEnd: number,
  durationMin: number,
  limit = 8,
  now = new Date(),
): FreeSlot[] {
  const slots: FreeSlot[] = [];
  for (let d = 0; d < days && slots.length < limit; d++) {
    const day = addDays(from, d);
    if (day.getDay() === 0 || day.getDay() === 6) {
      continue;
    }
    let cursor = new Date(day.getFullYear(), day.getMonth(), day.getDate(), workStart, 0);
    const dayEnd = new Date(day.getFullYear(), day.getMonth(), day.getDate(), workEnd, 0);
    while (cursor.getTime() + durationMin * 60000 <= dayEnd.getTime() && slots.length < limit) {
      const end = new Date(cursor.getTime() + durationMin * 60000);
      const clash = busy.find((b) => b.start < end && b.end > cursor);
      if (cursor < now) {
        cursor = new Date(cursor.getTime() + 15 * 60000);
      } else if (clash) {
        // przeskok za koniec kolidującego wydarzenia, wyrównany do 15 min
        const next = Math.ceil(clash.end.getTime() / (15 * 60000)) * 15 * 60000;
        cursor = new Date(Math.max(next, cursor.getTime() + 15 * 60000));
      } else {
        slots.push({ start: cursor, end });
        cursor = end;
      }
    }
  }
  return slots;
}
