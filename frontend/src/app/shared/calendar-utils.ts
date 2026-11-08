/** Pomocnicze funkcje dat kalendarza (czas lokalny przeglądarki, tydzień od poniedziałku). */

export const WEEKDAYS = ['Pn', 'Wt', 'Śr', 'Cz', 'Pt', 'So', 'Nd'];

const pad = (n: number) => String(n).padStart(2, '0');

/** Klucz dnia w czasie lokalnym: RRRR-MM-DD. */
export function dayKey(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function timeOf(date: Date): string {
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

export function addMonths(date: Date, months: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + months, 1);
}

/** 6 lub mniej pełnych tygodni (pon–niedz) obejmujących dany miesiąc. */
export function monthGrid(month: Date): Date[] {
  const first = startOfMonth(month);
  const offset = (first.getDay() + 6) % 7; // poniedziałek = 0
  const start = new Date(first.getFullYear(), first.getMonth(), 1 - offset);
  const last = new Date(first.getFullYear(), first.getMonth() + 1, 0);
  const tail = 6 - ((last.getDay() + 6) % 7);
  const total = offset + last.getDate() + tail;
  return Array.from({ length: total }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
}

export function monthTitle(month: Date): string {
  const text = new Intl.DateTimeFormat('pl-PL', { month: 'long', year: 'numeric' }).format(month);
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function longDate(date: Date): string {
  return new Intl.DateTimeFormat('pl-PL', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(date);
}

/** Łączy datę (RRRR-MM-DD) i godzinę (GG:MM) z formularza w czasie lokalnym → ISO (UTC). */
export function toIso(day: string, time: string): string {
  const [y, m, d] = day.split('-').map(Number);
  const [h, min] = (time || '00:00').split(':').map(Number);
  return new Date(y, m - 1, d, h, min).toISOString();
}
