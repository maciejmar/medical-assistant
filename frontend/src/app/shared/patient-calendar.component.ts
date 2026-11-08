import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Input,
  OnInit,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CalendarEvent, CalendarEventInput, CalendarService, EventType } from '../core/calendar.service';
import { PlanService, PlanStep } from '../core/plan.service';
import { WEEKDAYS, addMonths, dayKey, longDate, monthGrid, monthTitle, startOfMonth, timeOf, toIso } from './calendar-utils';
import { IconComponent, IconName } from './icon.component';

interface TypeStyle {
  label: string;
  short: string;
  icon: IconName;
  /** Kafelek wydarzenia w siatce i na liście. */
  chip: string;
  /** Kółko z ikoną (legenda, agenda). */
  badge: string;
}

/** Kategorie wydarzeń: zawsze ikona + etykieta, kolor tylko pomocniczo. */
export const EVENT_TYPES: Record<EventType, TypeStyle> = {
  visit: { label: 'Wizyta u logopedy', short: 'Wizyta', icon: 'calendar-check', chip: 'bg-brand-50 text-brand-800 ring-brand-200', badge: 'bg-brand-100 text-brand-700' },
  consultation: { label: 'Konsultacja u specjalisty', short: 'Konsultacja', icon: 'hospital', chip: 'bg-violet-50 text-violet-800 ring-violet-200', badge: 'bg-violet-100 text-violet-700' },
  stage_start: { label: 'Początek etapu terapii', short: 'Start etapu', icon: 'flag', chip: 'bg-sky-50 text-sky-800 ring-sky-200', badge: 'bg-sky-100 text-sky-700' },
  stage_end: { label: 'Koniec etapu terapii', short: 'Koniec etapu', icon: 'flag-fill', chip: 'bg-amber-50 text-amber-800 ring-amber-200', badge: 'bg-amber-100 text-amber-700' },
  other: { label: 'Inne', short: 'Inne', icon: 'pin', chip: 'bg-slate-100 text-slate-700 ring-slate-200', badge: 'bg-slate-200 text-slate-600' },
};
const ALL_TYPES: EventType[] = ['visit', 'consultation', 'stage_start', 'stage_end', 'other'];
const PATIENT_TYPES: EventType[] = ['consultation', 'other'];
const MAX_IN_CELL = 3;

function apiError(err: unknown, fallback: string): string {
  if (err instanceof HttpErrorResponse && typeof err.error?.detail === 'string') {
    return err.error.detail;
  }
  return fallback;
}

/**
 * Kalendarz pacjenta (widok miesiąca + najbliższe wydarzenia + okno wydarzenia).
 * `patientId` podany – widok lekarza (pełna edycja, powiązanie z krokiem planu);
 * `null` – widok pacjenta (te same wydarzenia; pacjent dodaje konsultacje/inne i edytuje tylko swoje).
 */
@Component({
  selector: 'app-patient-calendar',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="card mt-6" aria-labelledby="calendar-heading">
      <div class="mb-4 flex flex-wrap items-center gap-3">
        <h2 id="calendar-heading" class="mr-auto font-semibold">{{ heading }}</h2>
        <div class="flex items-center gap-1">
          <button type="button" class="grid h-9 w-9 place-items-center rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-100" (click)="shift(-1)" aria-label="Poprzedni miesiąc"><app-icon name="chevron-left" /></button>
          <span class="min-w-[9.5rem] text-center text-sm font-semibold text-slate-800" aria-live="polite">{{ title() }}</span>
          <button type="button" class="grid h-9 w-9 place-items-center rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-100" (click)="shift(1)" aria-label="Następny miesiąc"><app-icon name="chevron-right" /></button>
        </div>
        <button type="button" class="btn-secondary !px-3 !py-1.5" (click)="goToday()">Dziś</button>
        <button type="button" class="btn-primary !px-3 !py-1.5" (click)="openNew(selectedDay())"><app-icon name="plus" /> Dodaj wydarzenie</button>
      </div>

      <ul class="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600" aria-label="Legenda">
        @for (t of allTypes; track t) {
          <li class="flex items-center gap-1.5">
            <span class="grid h-5 w-5 place-items-center rounded-full" [class]="style(t).badge"><app-icon [name]="style(t).icon" [size]="11" /></span>
            {{ style(t).label }}
          </li>
        }
      </ul>

      @if (error(); as e) {
        <p class="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ e }}</p>
      }

      <div class="grid gap-4 xl:grid-cols-[1fr_17rem]">
        <div class="overflow-hidden rounded-xl border border-slate-200" [class.opacity-60]="loading()">
          <div class="grid grid-cols-7 bg-slate-50 text-center text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            @for (d of weekdays; track d) { <div class="py-2">{{ d }}</div> }
          </div>
          <div class="grid grid-cols-7">
            @for (day of days(); track day.getTime()) {
              <div
                role="button"
                tabindex="0"
                class="group min-h-[4.5rem] cursor-pointer border-t border-slate-200 p-1 text-left transition hover:bg-brand-50/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-500 sm:min-h-[6.5rem] sm:p-1.5 [&:not(:nth-child(7n+1))]:border-l"
                [class.bg-slate-50]="day.getMonth() !== month().getMonth()"
                [class.!bg-brand-50]="key(day) === selectedKey()"
                (click)="selectDay(day)"
                (keydown.enter)="selectDay(day)"
                (dblclick)="openNew(day)"
                [attr.aria-label]="dayLabel(day)"
              >
                <span
                  class="mb-1 grid h-6 w-6 place-items-center rounded-full text-xs"
                  [class]="key(day) === todayKey ? 'bg-brand-600 font-bold text-white' : day.getMonth() === month().getMonth() ? 'font-medium text-slate-700' : 'text-slate-400'"
                >{{ day.getDate() }}</span>
                @for (e of eventsOn(day).slice(0, maxInCell); track e.id) {
                  <button
                    type="button"
                    class="mb-0.5 flex w-full items-center gap-1 rounded px-1 py-0.5 text-left text-[11px] leading-tight ring-1 ring-inset transition hover:brightness-95"
                    [class]="style(e.type).chip"
                    (click)="$event.stopPropagation(); openEvent(e)"
                    [attr.aria-label]="style(e.type).label + ': ' + e.title + (e.all_day ? '' : ', ' + time(e.starts_at))"
                  >
                    <app-icon [name]="style(e.type).icon" [size]="11" />
                    <span class="hidden truncate sm:inline">@if (!e.all_day) {<span class="mr-1 font-semibold">{{ time(e.starts_at) }}</span>}{{ e.title }}</span>
                  </button>
                }
                @if (eventsOn(day).length > maxInCell) {
                  <span class="block px-1 text-[11px] font-medium text-slate-500">+{{ eventsOn(day).length - maxInCell }} więcej</span>
                }
              </div>
            }
          </div>
        </div>

        <aside class="space-y-4">
          <div>
            <h3 class="mb-2 text-sm font-semibold text-slate-800">{{ selectedTitle() }}</h3>
            @if (selectedEvents().length === 0) {
              <p class="text-xs text-slate-500">Brak wydarzeń. <button type="button" class="font-medium text-brand-700 hover:underline" (click)="openNew(selectedDay())">Dodaj</button></p>
            }
            <ul class="space-y-2">
              @for (e of selectedEvents(); track e.id) {
                <li>
                  <button type="button" class="flex w-full items-start gap-2 rounded-lg p-2 text-left ring-1 ring-inset transition hover:brightness-95" [class]="style(e.type).chip" (click)="openEvent(e)">
                    <app-icon [name]="style(e.type).icon" [size]="14" class="mt-0.5" />
                    <span class="min-w-0">
                      <span class="block truncate text-sm font-semibold">{{ e.title }}</span>
                      <span class="block text-xs opacity-80">{{ when(e) }}@if (e.location) { · {{ e.location }}}</span>
                    </span>
                  </button>
                </li>
              }
            </ul>
          </div>

          <div class="border-t border-slate-200 pt-4">
            <h3 class="mb-2 text-sm font-semibold text-slate-800">Najbliższe wydarzenia</h3>
            @if (upcoming().length === 0) {
              <p class="text-xs text-slate-500">Nic nie zaplanowano.</p>
            }
            <ol class="relative space-y-3 border-l-2 border-slate-200 pl-4">
              @for (e of upcoming(); track e.id) {
                <li class="relative">
                  <span class="absolute -left-[1.6rem] top-0.5 grid h-6 w-6 place-items-center rounded-full ring-4 ring-white" [class]="style(e.type).badge"><app-icon [name]="style(e.type).icon" [size]="12" /></span>
                  <button type="button" class="text-left hover:underline" (click)="openEvent(e)">
                    <span class="block text-xs font-medium text-slate-500">{{ shortDate(e.starts_at) }}@if (!e.all_day) {, {{ time(e.starts_at) }}}</span>
                    <span class="block text-sm font-semibold text-slate-800">{{ e.title }}</span>
                  </button>
                </li>
              }
            </ol>
          </div>
        </aside>
      </div>
    </section>

    <dialog #dialog class="w-[min(34rem,calc(100vw-2rem))] rounded-2xl p-0 shadow-2xl backdrop:bg-slate-900/50" aria-labelledby="event-dialog-title" (close)="editing.set(null)">
      <form class="space-y-4 p-5" (submit)="$event.preventDefault(); save()">
        <div class="flex items-start justify-between gap-3">
          <h3 id="event-dialog-title" class="flex items-center gap-2 text-lg font-semibold">
            <span class="grid h-8 w-8 place-items-center rounded-full" [class]="style(fType()).badge"><app-icon [name]="style(fType()).icon" /></span>
            {{ readOnly() ? fTitle() : editing() ? 'Edycja wydarzenia' : 'Nowe wydarzenie' }}
          </h3>
          <button type="button" class="grid h-8 w-8 place-items-center rounded-full text-slate-500 hover:bg-slate-100" (click)="close()" aria-label="Zamknij okno"><app-icon name="close" /></button>
        </div>

        @if (readOnly()) {
          @if (editing(); as e) {
            <dl class="space-y-2 text-sm">
              <div class="flex gap-2"><dt class="w-24 shrink-0 text-slate-500">Rodzaj</dt><dd>{{ style(e.type).label }}</dd></div>
              <div class="flex gap-2"><dt class="w-24 shrink-0 text-slate-500">Kiedy</dt><dd>{{ longDay(e.starts_at) }}, {{ when(e) }}</dd></div>
              @if (e.location) { <div class="flex gap-2"><dt class="w-24 shrink-0 text-slate-500">Miejsce</dt><dd>{{ e.location }}</dd></div> }
              @if (e.plan_step_title) { <div class="flex gap-2"><dt class="w-24 shrink-0 text-slate-500">Etap</dt><dd>{{ e.plan_step_title }}</dd></div> }
              @if (e.description) { <div class="flex gap-2"><dt class="w-24 shrink-0 text-slate-500">Opis</dt><dd class="whitespace-pre-wrap">{{ e.description }}</dd></div> }
            </dl>
            <p class="text-xs text-slate-500">Wydarzenie dodane przez logopedę – zmiany ustal z logopedą.</p>
          }
        } @else {
          <fieldset>
            <legend class="label">Rodzaj</legend>
            <div class="flex flex-wrap gap-2">
              @for (t of allowedTypes(); track t) {
                <button type="button" class="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium ring-1 ring-inset transition" [class]="fType() === t ? style(t).chip + ' !ring-2' : 'text-slate-600 ring-slate-300 hover:bg-slate-50'" [attr.aria-pressed]="fType() === t" (click)="fType.set(t)">
                  <app-icon [name]="style(t).icon" [size]="13" /> {{ style(t).short }}
                </button>
              }
            </div>
          </fieldset>

          <div>
            <label class="label" for="ev-title">Tytuł</label>
            <input id="ev-title" class="field" maxlength="200" required autofocus [value]="fTitle()" (input)="fTitle.set($any($event.target).value)" [placeholder]="titlePlaceholder()" />
          </div>

          <div class="grid gap-3 sm:grid-cols-[1fr_auto_auto]">
            <div>
              <label class="label" for="ev-day">Data</label>
              <input id="ev-day" type="date" class="field" required [value]="fDay()" (input)="fDay.set($any($event.target).value)" />
            </div>
            @if (!fAllDay()) {
              <div>
                <label class="label" for="ev-start">Od</label>
                <input id="ev-start" type="time" class="field" [value]="fStart()" (input)="fStart.set($any($event.target).value)" />
              </div>
              <div>
                <label class="label" for="ev-end">Do</label>
                <input id="ev-end" type="time" class="field" [value]="fEnd()" (input)="fEnd.set($any($event.target).value)" />
              </div>
            }
          </div>
          <label class="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600" [checked]="fAllDay()" (change)="fAllDay.set($any($event.target).checked)" />
            Cały dzień
          </label>

          @if (planSteps().length > 0 && (fType() === 'stage_start' || fType() === 'stage_end')) {
            <div>
              <label class="label" for="ev-step">Etap z planu działania</label>
              <select id="ev-step" class="field" (change)="fStep.set($any($event.target).value ? +$any($event.target).value : null)">
                <option value="" [selected]="fStep() === null">— bez powiązania —</option>
                @for (s of planSteps(); track s.id; let i = $index) {
                  <option [value]="s.id" [selected]="fStep() === s.id">Krok {{ i + 1 }}: {{ s.title }}</option>
                }
              </select>
            </div>
          }

          <div>
            <label class="label" for="ev-location">Miejsce</label>
            <input id="ev-location" class="field" maxlength="300" [value]="fLocation()" (input)="fLocation.set($any($event.target).value)" placeholder="np. gabinet, poradnia, adres" />
          </div>
          <div>
            <label class="label" for="ev-desc">Opis</label>
            <textarea id="ev-desc" class="field" rows="3" maxlength="5000" [value]="fDescription()" (input)="fDescription.set($any($event.target).value)"></textarea>
          </div>

          @if (editing()?.created_by_role === 'patient' && patientId !== null) {
            <p class="flex items-center gap-1.5 text-xs text-violet-700"><app-icon name="person" [size]="12" /> Wydarzenie dodane przez pacjenta.</p>
          }
        }

        @if (dialogError(); as e) {
          <p class="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ e }}</p>
        }

        <div class="flex flex-wrap items-center gap-2 border-t border-slate-200 pt-4">
          @if (editing(); as e) {
            @if (e.editable) {
              <button type="button" class="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold text-red-600 hover:bg-red-50" [disabled]="busy()" (click)="remove(e)"><app-icon name="trash" [size]="14" /> Usuń</button>
            }
          }
          <span class="flex-1"></span>
          <button type="button" class="btn-secondary" (click)="close()">{{ readOnly() ? 'Zamknij' : 'Anuluj' }}</button>
          @if (!readOnly()) {
            <button type="submit" class="btn-primary" [disabled]="busy() || !fTitle().trim() || !fDay()"><app-icon name="check" /> Zapisz</button>
          }
        </div>
      </form>
    </dialog>
  `,
})
export class PatientCalendarComponent implements OnInit {
  /** Karta pacjenta (widok lekarza) albo null – panel pacjenta. */
  @Input() patientId: number | null = null;
  @Input() heading = 'Kalendarz pacjenta';
  @ViewChild('dialog') private dialog!: ElementRef<HTMLDialogElement>;

  private readonly api = inject(CalendarService);
  private readonly plans = inject(PlanService);

  protected readonly weekdays = WEEKDAYS;
  protected readonly allTypes = ALL_TYPES;
  protected readonly maxInCell = MAX_IN_CELL;
  protected readonly todayKey = dayKey(new Date());

  protected readonly month = signal(startOfMonth(new Date()));
  protected readonly selectedDay = signal(new Date());
  protected readonly events = signal<CalendarEvent[]>([]);
  protected readonly upcoming = signal<CalendarEvent[]>([]);
  protected readonly planSteps = signal<PlanStep[]>([]);
  protected readonly loading = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly days = computed(() => monthGrid(this.month()));
  protected readonly title = computed(() => monthTitle(this.month()));
  protected readonly selectedKey = computed(() => dayKey(this.selectedDay()));
  protected readonly selectedTitle = computed(() => {
    const text = longDate(this.selectedDay());
    return text.charAt(0).toUpperCase() + text.slice(1);
  });
  private readonly byDay = computed(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const e of this.events()) {
      const k = dayKey(new Date(e.starts_at));
      map.set(k, [...(map.get(k) ?? []), e]);
    }
    return map;
  });
  protected readonly selectedEvents = computed(() => this.byDay().get(this.selectedKey()) ?? []);

  // formularz okna
  protected readonly editing = signal<CalendarEvent | null>(null);
  protected readonly readOnly = computed(() => {
    const e = this.editing();
    return !!e && !e.editable;
  });
  protected readonly fType = signal<EventType>('visit');
  protected readonly fTitle = signal('');
  protected readonly fDay = signal('');
  protected readonly fAllDay = signal(false);
  protected readonly fStart = signal('09:00');
  protected readonly fEnd = signal('');
  protected readonly fLocation = signal('');
  protected readonly fDescription = signal('');
  protected readonly fStep = signal<number | null>(null);
  protected readonly dialogError = signal<string | null>(null);

  protected allowedTypes(): EventType[] {
    return this.patientId === null ? PATIENT_TYPES : ALL_TYPES;
  }

  ngOnInit(): void {
    this.reload();
    if (this.patientId !== null) {
      this.plans.get(this.patientId).subscribe({ next: (p) => this.planSteps.set(p.steps) });
    }
  }

  protected style(type: EventType): TypeStyle {
    return EVENT_TYPES[type] ?? EVENT_TYPES.other;
  }

  protected key(day: Date): string {
    return dayKey(day);
  }

  protected eventsOn(day: Date): CalendarEvent[] {
    return this.byDay().get(dayKey(day)) ?? [];
  }

  protected time(iso: string): string {
    return timeOf(new Date(iso));
  }

  protected when(e: CalendarEvent): string {
    if (e.all_day) {
      return 'cały dzień';
    }
    return e.ends_at ? `${this.time(e.starts_at)}–${this.time(e.ends_at)}` : this.time(e.starts_at);
  }

  protected shortDate(iso: string): string {
    return new Intl.DateTimeFormat('pl-PL', { weekday: 'short', day: 'numeric', month: 'short' }).format(new Date(iso));
  }

  protected longDay(iso: string): string {
    return longDate(new Date(iso));
  }

  protected dayLabel(day: Date): string {
    const count = this.eventsOn(day).length;
    return `${longDate(day)}${count ? `, wydarzenia: ${count}` : ''}`;
  }

  protected titlePlaceholder(): string {
    return { visit: 'np. Wizyta kontrolna', consultation: 'np. Laryngolog – konsultacja', stage_start: 'np. Start: pionizacja języka', stage_end: 'np. Koniec etapu: utrwalanie', other: 'np. Badanie słuchu' }[this.fType()];
  }

  protected shift(months: number): void {
    this.month.set(addMonths(this.month(), months));
    this.reload();
  }

  protected goToday(): void {
    this.month.set(startOfMonth(new Date()));
    this.selectedDay.set(new Date());
    this.reload();
  }

  protected selectDay(day: Date): void {
    this.selectedDay.set(day);
    if (day.getMonth() !== this.month().getMonth()) {
      this.month.set(startOfMonth(day));
      this.reload();
    }
  }

  protected openNew(day: Date): void {
    this.editing.set(null);
    this.fType.set(this.allowedTypes()[0]);
    this.fTitle.set('');
    this.fDay.set(dayKey(day));
    this.fAllDay.set(false);
    this.fStart.set('09:00');
    this.fEnd.set('');
    this.fLocation.set('');
    this.fDescription.set('');
    this.fStep.set(null);
    this.show();
  }

  protected openEvent(e: CalendarEvent): void {
    const start = new Date(e.starts_at);
    this.editing.set(e);
    this.fType.set(e.type);
    this.fTitle.set(e.title);
    this.fDay.set(dayKey(start));
    this.fAllDay.set(e.all_day);
    this.fStart.set(timeOf(start));
    this.fEnd.set(e.ends_at ? timeOf(new Date(e.ends_at)) : '');
    this.fLocation.set(e.location);
    this.fDescription.set(e.description);
    this.fStep.set(e.plan_step_id);
    this.show();
  }

  protected close(): void {
    this.dialog.nativeElement.close();
  }

  protected save(): void {
    const allDay = this.fAllDay();
    const stage = this.fType() === 'stage_start' || this.fType() === 'stage_end';
    const input: CalendarEventInput = {
      type: this.fType(),
      title: this.fTitle().trim(),
      starts_at: toIso(this.fDay(), allDay ? '00:00' : this.fStart()),
      ends_at: !allDay && this.fEnd() ? toIso(this.fDay(), this.fEnd()) : null,
      all_day: allDay,
      location: this.fLocation().trim(),
      description: this.fDescription().trim(),
      plan_step_id: stage ? this.fStep() : null,
    };
    const editing = this.editing();
    const request = editing
      ? this.api.update(this.patientId, editing.id, input)
      : this.api.create(this.patientId, input);
    this.busy.set(true);
    this.dialogError.set(null);
    request.subscribe({
      next: (saved) => {
        this.busy.set(false);
        this.selectedDay.set(new Date(saved.starts_at));
        this.month.set(startOfMonth(new Date(saved.starts_at)));
        this.close();
        this.reload();
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.dialogError.set(apiError(err, 'Nie udało się zapisać wydarzenia.'));
      },
    });
  }

  protected remove(e: CalendarEvent): void {
    if (!confirm(`Usunąć wydarzenie „${e.title}”?`)) {
      return;
    }
    this.busy.set(true);
    this.api.remove(this.patientId, e.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.close();
        this.reload();
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.dialogError.set(apiError(err, 'Nie udało się usunąć wydarzenia.'));
      },
    });
  }

  private show(): void {
    this.dialogError.set(null);
    const dialog = this.dialog.nativeElement;
    if (!dialog.open) {
      dialog.showModal();
    }
  }

  private reload(): void {
    const grid = this.days();
    const start = grid[0];
    const last = grid[grid.length - 1];
    const end = new Date(last.getFullYear(), last.getMonth(), last.getDate() + 1);
    this.loading.set(true);
    this.api.list(this.patientId, start, end).subscribe({
      next: (events) => {
        this.events.set(events);
        this.loading.set(false);
        this.error.set(null);
      },
      error: (err: unknown) => {
        this.loading.set(false);
        this.error.set(apiError(err, 'Nie udało się wczytać kalendarza.'));
      },
    });
    const today = new Date();
    this.api.list(this.patientId, new Date(today.getFullYear(), today.getMonth(), today.getDate())).subscribe({
      next: (events) => this.upcoming.set(events.slice(0, 5)),
    });
  }
}
