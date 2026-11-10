import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, OnInit, ViewChild, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { CalendarEventInput, CalendarService, DoctorCalendarEvent, EventType } from '../../core/calendar.service';
import { PatientsService } from '../../core/patients.service';
import { WEEKDAYS, addMonths, dayKey, longDate, monthGrid, monthTitle, startOfMonth, timeOf, toIso } from '../../shared/calendar-utils';
import {
  BLOCKING_TYPES,
  DEFAULT_DURATION_MIN,
  FreeSlot,
  addDays,
  freeSlots,
  initials,
  layoutLanes,
  patientColor,
  startOfWeek,
  textOn,
} from '../../shared/doctor-calendar-utils';
import { IconComponent } from '../../shared/icon.component';
import { EVENT_TYPES } from '../../shared/patient-calendar.component';
import { Patient } from '../../shared/models';

const DAY_START_H = 7;
const DAY_END_H = 20;
const PX_PER_MIN = 1.2;
const FREE_SLOT_DAYS = 14;
const ALL_TYPES: EventType[] = ['visit', 'consultation', 'stage_start', 'stage_end', 'other'];

interface WeekBlock {
  event: DoctorCalendarEvent;
  start: number;
  end: number;
  lane: number;
  lanes: number;
}

function apiError(err: unknown, fallback: string): string {
  if (err instanceof HttpErrorResponse && typeof err.error?.detail === 'string') {
    return err.error.detail;
  }
  return fallback;
}

/**
 * Kalendarz lekarza: wydarzenia wszystkich jego pacjentów w jednym miejscu (tydzień z siatką godzin
 * – widać wolne okna; miesiąc), lista najbliższych wolnych terminów i dodawanie wydarzenia
 * kliknięciem w wolne miejsce. Ikona = typ wydarzenia, kółko z inicjałami w kolorze = pacjent.
 */
@Component({
  selector: 'app-doctor-calendar',
  standalone: true,
  imports: [IconComponent, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="space-y-4">
      <div class="flex flex-wrap items-center gap-3">
        <div class="mr-auto">
          <h1 class="text-2xl font-bold">Kalendarz</h1>
          <p class="text-sm text-slate-500">Wizyty i wydarzenia wszystkich Twoich pacjentów. Kliknij wolne miejsce w widoku tygodnia, aby zaplanować wizytę.</p>
        </div>
        <div class="inline-flex rounded-lg border border-slate-300 bg-white p-0.5 text-sm" role="tablist">
          <button type="button" role="tab" class="rounded-md px-3 py-1.5 font-medium" [class]="view() === 'week' ? 'bg-brand-600 text-white' : 'text-slate-600 hover:bg-slate-100'" [attr.aria-selected]="view() === 'week'" (click)="setView('week')">Tydzień</button>
          <button type="button" role="tab" class="rounded-md px-3 py-1.5 font-medium" [class]="view() === 'month' ? 'bg-brand-600 text-white' : 'text-slate-600 hover:bg-slate-100'" [attr.aria-selected]="view() === 'month'" (click)="setView('month')">Miesiąc</button>
        </div>
        <div class="flex items-center gap-1">
          <button type="button" class="grid h-9 w-9 place-items-center rounded-lg border border-slate-300 bg-white text-slate-600 hover:bg-slate-100" (click)="shift(-1)" aria-label="Poprzedni okres"><app-icon name="chevron-left" /></button>
          <span class="min-w-[12rem] text-center text-sm font-semibold text-slate-800" aria-live="polite">{{ rangeTitle() }}</span>
          <button type="button" class="grid h-9 w-9 place-items-center rounded-lg border border-slate-300 bg-white text-slate-600 hover:bg-slate-100" (click)="shift(1)" aria-label="Następny okres"><app-icon name="chevron-right" /></button>
        </div>
        <button type="button" class="btn-secondary !px-3 !py-1.5" (click)="goToday()">Dziś</button>
        <button type="button" class="btn-primary !px-3 !py-1.5" (click)="openNew(nextHour())"><app-icon name="plus" /> Nowe wydarzenie</button>
      </div>

      @if (error(); as e) {
        <p class="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ e }}</p>
      }

      <div class="grid gap-4 xl:grid-cols-[1fr_18rem]">
        <section class="card !p-0 overflow-hidden" [class.opacity-60]="loading()">
          @if (view() === 'week') {
            <div class="overflow-x-auto">
              <div class="min-w-[44rem]">
                <!-- nagłówki dni + wydarzenia całodniowe -->
                <div class="grid border-b border-slate-200 bg-slate-50" [style.grid-template-columns]="'3.5rem repeat(7, 1fr)'">
                  <div></div>
                  @for (day of weekDays(); track day.getTime(); let i = $index) {
                    <div class="border-l border-slate-200 px-1.5 py-1.5 text-center">
                      <div class="text-[11px] font-semibold uppercase text-slate-500">{{ weekdays[i] }}</div>
                      <div class="mx-auto grid h-7 w-7 place-items-center rounded-full text-sm font-semibold" [class]="key(day) === todayKey ? 'bg-brand-600 text-white' : 'text-slate-800'">{{ day.getDate() }}</div>
                      @for (e of allDay(day); track e.id) {
                        <button type="button" class="mt-1 flex w-full items-center gap-1 rounded px-1 py-0.5 text-left text-[11px] ring-1 ring-inset" [class]="typeStyle(e.type).chip" (click)="openEvent(e)" [attr.aria-label]="eventLabel(e)">
                          <span class="grid h-4 w-4 shrink-0 place-items-center rounded-full text-[8px] font-bold" [style.background]="color(e.patient_id)" [style.color]="onColor(e.patient_id)">{{ ini(e.patient_name) }}</span>
                          <app-icon [name]="typeStyle(e.type).icon" [size]="10" />
                          <span class="truncate">{{ e.title }}</span>
                        </button>
                      }
                    </div>
                  }
                </div>
                <!-- siatka godzin -->
                <div class="grid" [style.grid-template-columns]="'3.5rem repeat(7, 1fr)'">
                  <div class="relative" [style.height.px]="gridHeight">
                    @for (h of hours; track h) {
                      <span class="absolute right-1.5 -translate-y-1/2 text-[10px] text-slate-400" [style.top.px]="(h - dayStart) * 60 * pxPerMin">{{ h }}:00</span>
                    }
                  </div>
                  @for (day of weekDays(); track day.getTime()) {
                    <div
                      class="relative cursor-copy border-l border-slate-200"
                      [style.height.px]="gridHeight"
                      [style.background-image]="gridLines"
                      (click)="clickGrid($event, day)"
                      [attr.aria-label]="'Siatka godzin – ' + longDay(day) + '. Kliknij, aby dodać wydarzenie.'"
                    >
                      @if (!isWorkday(day)) { <div class="pointer-events-none absolute inset-0 bg-slate-100/60"></div> }
                      @else {
                        <div class="pointer-events-none absolute inset-x-0 top-0 bg-slate-100/70" [style.height.px]="(workStart() - dayStart) * 60 * pxPerMin"></div>
                        <div class="pointer-events-none absolute inset-x-0 bottom-0 bg-slate-100/70" [style.height.px]="(dayEnd - workEnd()) * 60 * pxPerMin"></div>
                      }
                      @if (key(day) === todayKey && nowOffset() !== null) {
                        <div class="pointer-events-none absolute inset-x-0 z-10 border-t-2 border-red-500" [style.top.px]="nowOffset()"><span class="absolute -left-1 -top-1.5 h-3 w-3 rounded-full bg-red-500"></span></div>
                      }
                      @for (b of blocks(day); track b.event.id) {
                        <button
                          type="button"
                          class="absolute z-[5] overflow-hidden rounded-md border-l-4 bg-white px-1.5 py-1 text-left text-[11px] leading-tight shadow-sm ring-1 ring-slate-200 transition hover:z-20 hover:shadow-md"
                          [style.top.px]="(b.start - dayStart * 60) * pxPerMin"
                          [style.height.px]="max((b.end - b.start) * pxPerMin - 2, 22)"
                          [style.left]="'calc(' + (100 * b.lane) / b.lanes + '% + 2px)'"
                          [style.width]="'calc(' + 100 / b.lanes + '% - 4px)'"
                          [style.border-left-color]="color(b.event.patient_id)"
                          (click)="$event.stopPropagation(); openEvent(b.event)"
                          [attr.aria-label]="eventLabel(b.event)"
                        >
                          <span class="flex items-center gap-1">
                            <span class="grid h-4 w-4 shrink-0 place-items-center rounded-full text-[8px] font-bold" [style.background]="color(b.event.patient_id)" [style.color]="onColor(b.event.patient_id)">{{ ini(b.event.patient_name) }}</span>
                            <app-icon [name]="typeStyle(b.event.type).icon" [size]="10" class="text-slate-500" />
                            <span class="font-semibold tabular-nums">{{ time(b.event.starts_at) }}</span>
                          </span>
                          <span class="block truncate font-medium text-slate-800">{{ b.event.title }}</span>
                          <span class="block truncate text-slate-500">{{ b.event.patient_name }}</span>
                        </button>
                      }
                    </div>
                  }
                </div>
              </div>
            </div>
          } @else {
            <div class="grid grid-cols-7 bg-slate-50 text-center text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              @for (d of weekdays; track d) { <div class="py-2">{{ d }}</div> }
            </div>
            <div class="grid grid-cols-7">
              @for (day of monthDays(); track day.getTime()) {
                <div
                  role="button"
                  tabindex="0"
                  class="min-h-[6rem] cursor-pointer border-t border-slate-200 p-1 transition hover:bg-brand-50/40 [&:not(:nth-child(7n+1))]:border-l"
                  [class.cal-outside]="day.getMonth() !== anchor().getMonth()"
                  (click)="openWeekOf(day)"
                  (keydown.enter)="openWeekOf(day)"
                  [attr.aria-label]="longDay(day) + ', wydarzenia: ' + onDay(day).length + '. Otwórz tydzień.'"
                >
                  <span class="mb-1 grid h-6 w-6 place-items-center rounded-full text-xs" [class]="key(day) === todayKey ? 'bg-brand-600 font-bold text-white' : day.getMonth() === anchor().getMonth() ? 'font-medium text-slate-700' : 'cal-outside-number'">{{ day.getDate() }}</span>
                  @for (e of onDay(day).slice(0, 3); track e.id) {
                    <button type="button" class="mb-0.5 flex w-full items-center gap-1 rounded px-1 py-0.5 text-left text-[11px] ring-1 ring-inset" [class]="typeStyle(e.type).chip" (click)="$event.stopPropagation(); openEvent(e)" [attr.aria-label]="eventLabel(e)">
                      <span class="grid h-4 w-4 shrink-0 place-items-center rounded-full text-[8px] font-bold" [style.background]="color(e.patient_id)" [style.color]="onColor(e.patient_id)">{{ ini(e.patient_name) }}</span>
                      <span class="hidden truncate sm:inline">@if (!e.all_day) {<span class="mr-1 font-semibold">{{ time(e.starts_at) }}</span>}{{ e.title }}</span>
                    </button>
                  }
                  @if (onDay(day).length > 3) { <span class="px-1 text-[11px] text-slate-500">+{{ onDay(day).length - 3 }} więcej</span> }
                </div>
              }
            </div>
          }
        </section>

        <aside class="space-y-4">
          <section class="card space-y-3">
            <h2 class="font-semibold">Najbliższe wolne terminy</h2>
            <div class="grid grid-cols-3 gap-2 text-xs">
              <label>
                <span class="label">Od</span>
                <select class="field !py-1 !text-xs" (change)="workStart.set(+$any($event.target).value)">
                  @for (h of workHours; track h) { <option [value]="h" [selected]="h === workStart()">{{ h }}:00</option> }
                </select>
              </label>
              <label>
                <span class="label">Do</span>
                <select class="field !py-1 !text-xs" (change)="workEnd.set(+$any($event.target).value)">
                  @for (h of workHours; track h) { <option [value]="h" [selected]="h === workEnd()">{{ h }}:00</option> }
                </select>
              </label>
              <label>
                <span class="label">Wizyta</span>
                <select class="field !py-1 !text-xs" (change)="slotMinutes.set(+$any($event.target).value)">
                  @for (m of durations; track m) { <option [value]="m" [selected]="m === slotMinutes()">{{ m }} min</option> }
                </select>
              </label>
            </div>
            @if (slots().length === 0) {
              <p class="text-xs text-slate-500">Brak wolnych terminów w ciągu {{ freeDays }} dni w godzinach pracy.</p>
            }
            <ul class="space-y-1">
              @for (s of slots(); track s.start.getTime()) {
                <li>
                  <button type="button" class="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-sm ring-1 ring-inset ring-emerald-200 transition hover:bg-emerald-50" (click)="openSlot(s)">
                    <span class="capitalize text-slate-700">{{ shortDay(s.start) }}</span>
                    <span class="font-semibold tabular-nums text-emerald-800">{{ time(s.start.toISOString()) }}–{{ time(s.end.toISOString()) }}</span>
                  </button>
                </li>
              }
            </ul>
            <p class="text-[11px] text-slate-500">Liczone z wizyt i wpisów „Inne” (pon–pt). Konsultacje u innych specjalistów i etapy terapii nie zajmują Twojego czasu.</p>
          </section>

          <section class="card space-y-2">
            <h2 class="font-semibold">Pacjenci</h2>
            @if (legend().length === 0) {
              <p class="text-xs text-slate-500">W tym okresie brak wydarzeń.</p>
            }
            <ul class="space-y-1">
              @for (p of legend(); track p.id) {
                <li>
                  <label class="flex cursor-pointer items-center gap-2 rounded-lg px-1 py-1 text-sm hover:bg-slate-50">
                    <input type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600" [checked]="!hidden().has(p.id)" (change)="togglePatient(p.id)" />
                    <span class="grid h-6 w-6 place-items-center rounded-full text-[10px] font-bold" [style.background]="color(p.id)" [style.color]="onColor(p.id)">{{ ini(p.name) }}</span>
                    <span class="min-w-0 flex-1 truncate" [class.text-slate-400]="hidden().has(p.id)">{{ p.name }}</span>
                    <span class="text-xs tabular-nums text-slate-400">{{ p.count }}</span>
                  </label>
                </li>
              }
            </ul>
            <div class="border-t border-slate-200 pt-2">
              <h3 class="mb-1 text-xs font-semibold uppercase text-slate-500">Typy wydarzeń</h3>
              <ul class="grid grid-cols-1 gap-1 text-xs text-slate-600">
                @for (t of allTypes; track t) {
                  <li class="flex items-center gap-1.5"><span class="grid h-5 w-5 place-items-center rounded-full" [class]="typeStyle(t).badge"><app-icon [name]="typeStyle(t).icon" [size]="11" /></span>{{ typeStyle(t).label }}</li>
                }
              </ul>
            </div>
          </section>
        </aside>
      </div>
    </div>

    <dialog #dialog class="w-[min(34rem,calc(100vw-2rem))] rounded-2xl p-0 shadow-2xl backdrop:bg-slate-900/50" aria-labelledby="dc-title" (close)="editing.set(null)">
      <form class="space-y-4 p-5" (submit)="$event.preventDefault(); save()">
        <div class="flex items-start justify-between gap-3">
          <h3 id="dc-title" class="flex items-center gap-2 text-lg font-semibold">
            <span class="grid h-8 w-8 place-items-center rounded-full" [class]="typeStyle(fType()).badge"><app-icon [name]="typeStyle(fType()).icon" /></span>
            {{ editing() ? 'Edycja wydarzenia' : 'Nowe wydarzenie' }}
          </h3>
          <button type="button" class="grid h-8 w-8 place-items-center rounded-full text-slate-500 hover:bg-slate-100" (click)="close()" aria-label="Zamknij okno"><app-icon name="close" /></button>
        </div>

        <div>
          <label class="label" for="dc-patient">Pacjent</label>
          @if (editing(); as e) {
            <p class="flex items-center gap-2 text-sm">
              <span class="grid h-6 w-6 place-items-center rounded-full text-[10px] font-bold" [style.background]="color(e.patient_id)" [style.color]="onColor(e.patient_id)">{{ ini(e.patient_name) }}</span>
              <a [routerLink]="['/patients', e.patient_id]" class="font-medium text-brand-700 hover:underline" (click)="close()">{{ e.patient_name }}</a>
              @if (e.created_by_role === 'patient') { <span class="badge bg-violet-100 text-violet-700">dodane przez pacjenta</span> }
            </p>
          } @else {
            <select id="dc-patient" class="field" required (change)="fPatient.set($any($event.target).value ? +$any($event.target).value : null)">
              <option value="" [selected]="fPatient() === null">— wybierz pacjenta —</option>
              @for (p of patients(); track p.id) {
                <option [value]="p.id" [selected]="fPatient() === p.id">{{ p.last_name }} {{ p.first_name }}</option>
              }
            </select>
          }
        </div>

        <fieldset>
          <legend class="label">Rodzaj</legend>
          <div class="flex flex-wrap gap-2">
            @for (t of allTypes; track t) {
              <button type="button" class="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium ring-1 ring-inset transition" [class]="fType() === t ? typeStyle(t).chip + ' !ring-2' : 'text-slate-600 ring-slate-300 hover:bg-slate-50'" [attr.aria-pressed]="fType() === t" (click)="fType.set(t)">
                <app-icon [name]="typeStyle(t).icon" [size]="13" /> {{ typeStyle(t).short }}
              </button>
            }
          </div>
        </fieldset>

        <div>
          <label class="label" for="dc-ttl">Tytuł</label>
          <input id="dc-ttl" class="field" maxlength="200" required [value]="fTitle()" (input)="fTitle.set($any($event.target).value)" placeholder="np. Wizyta kontrolna" />
        </div>
        <div class="grid gap-3 sm:grid-cols-[1fr_auto_auto]">
          <div>
            <label class="label" for="dc-day">Data</label>
            <input id="dc-day" type="date" class="field" required [value]="fDay()" (input)="fDay.set($any($event.target).value)" />
          </div>
          @if (!fAllDay()) {
            <div><label class="label" for="dc-start">Od</label><input id="dc-start" type="time" class="field" [value]="fStart()" (input)="fStart.set($any($event.target).value)" /></div>
            <div><label class="label" for="dc-end">Do</label><input id="dc-end" type="time" class="field" [value]="fEnd()" (input)="fEnd.set($any($event.target).value)" /></div>
          }
        </div>
        <label class="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600" [checked]="fAllDay()" (change)="fAllDay.set($any($event.target).checked)" /> Cały dzień
        </label>
        <div>
          <label class="label" for="dc-loc">Miejsce</label>
          <input id="dc-loc" class="field" maxlength="300" [value]="fLocation()" (input)="fLocation.set($any($event.target).value)" />
        </div>
        <div>
          <label class="label" for="dc-desc">Opis</label>
          <textarea id="dc-desc" class="field" rows="3" maxlength="5000" [value]="fDescription()" (input)="fDescription.set($any($event.target).value)"></textarea>
        </div>
        @if (conflict(); as c) {
          <p class="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900" role="status">Uwaga: w tym czasie masz już „{{ c.title }}” ({{ c.patient_name }}, {{ time(c.starts_at) }}).</p>
        }
        @if (dialogError(); as e) {
          <p class="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{{ e }}</p>
        }
        <div class="flex flex-wrap items-center gap-2 border-t border-slate-200 pt-4">
          @if (editing(); as e) {
            <button type="button" class="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold text-red-600 hover:bg-red-50" [disabled]="busy()" (click)="remove(e)"><app-icon name="trash" [size]="14" /> Usuń</button>
          }
          <span class="flex-1"></span>
          <button type="button" class="btn-secondary" (click)="close()">Anuluj</button>
          <button type="submit" class="btn-primary" [disabled]="busy() || !fTitle().trim() || !fDay() || (!editing() && fPatient() === null)"><app-icon name="check" /> Zapisz</button>
        </div>
      </form>
    </dialog>
  `,
})
export class DoctorCalendarComponent implements OnInit {
  @ViewChild('dialog') private dialog!: ElementRef<HTMLDialogElement>;
  private readonly api = inject(CalendarService);
  private readonly patientsApi = inject(PatientsService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly weekdays = WEEKDAYS;
  protected readonly allTypes = ALL_TYPES;
  protected readonly dayStart = DAY_START_H;
  protected readonly dayEnd = DAY_END_H;
  protected readonly pxPerMin = PX_PER_MIN;
  protected readonly gridHeight = (DAY_END_H - DAY_START_H) * 60 * PX_PER_MIN;
  protected readonly hours = Array.from({ length: DAY_END_H - DAY_START_H }, (_, i) => DAY_START_H + i);
  protected readonly gridLines = `repeating-linear-gradient(to bottom, #e2e8f0 0, #e2e8f0 1px, transparent 1px, transparent ${60 * PX_PER_MIN}px)`;
  protected readonly workHours = Array.from({ length: 15 }, (_, i) => 6 + i);
  protected readonly durations = [30, 45, 60, 90];
  protected readonly freeDays = FREE_SLOT_DAYS;
  protected readonly todayKey = dayKey(new Date());

  protected readonly view = signal<'week' | 'month'>('week');
  protected readonly anchor = signal(new Date());
  protected readonly events = signal<DoctorCalendarEvent[]>([]);
  protected readonly upcoming = signal<DoctorCalendarEvent[]>([]);
  protected readonly patients = signal<Patient[]>([]);
  protected readonly hidden = signal<Set<number>>(new Set());
  protected readonly loading = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly workStart = signal(8);
  protected readonly workEnd = signal(18);
  protected readonly slotMinutes = signal(DEFAULT_DURATION_MIN);
  protected readonly nowOffset = signal<number | null>(this.computeNowOffset());

  protected readonly weekDays = computed(() => {
    const start = startOfWeek(this.anchor());
    return Array.from({ length: 7 }, (_, i) => addDays(start, i));
  });
  protected readonly monthDays = computed(() => monthGrid(startOfMonth(this.anchor())));
  protected readonly visible = computed(() => this.events().filter((e) => !this.hidden().has(e.patient_id)));
  private readonly byDay = computed(() => {
    const map = new Map<string, DoctorCalendarEvent[]>();
    for (const e of this.visible()) {
      const k = dayKey(new Date(e.starts_at));
      map.set(k, [...(map.get(k) ?? []), e]);
    }
    return map;
  });
  protected readonly legend = computed(() => {
    const map = new Map<number, { id: number; name: string; count: number }>();
    for (const e of this.events()) {
      const entry = map.get(e.patient_id) ?? { id: e.patient_id, name: e.patient_name, count: 0 };
      entry.count++;
      map.set(e.patient_id, entry);
    }
    return [...map.values()].sort((a, b) => a.name.localeCompare(b.name, 'pl'));
  });
  protected readonly rangeTitle = computed(() => {
    if (this.view() === 'month') {
      return monthTitle(startOfMonth(this.anchor()));
    }
    const [first, last] = [this.weekDays()[0], this.weekDays()[6]];
    const fmt = new Intl.DateTimeFormat('pl-PL', { day: 'numeric', month: 'short' });
    return `${fmt.format(first)} – ${fmt.format(last)} ${last.getFullYear()}`;
  });
  protected readonly slots = computed<FreeSlot[]>(() => {
    const busy = this.upcoming()
      .filter((e) => BLOCKING_TYPES.has(e.type) && !e.all_day)
      .map((e) => ({ start: new Date(e.starts_at), end: this.endOf(e) }));
    const today = new Date();
    return freeSlots(busy, new Date(today.getFullYear(), today.getMonth(), today.getDate()), FREE_SLOT_DAYS, this.workStart(), this.workEnd(), this.slotMinutes());
  });

  // formularz okna
  protected readonly editing = signal<DoctorCalendarEvent | null>(null);
  protected readonly fPatient = signal<number | null>(null);
  protected readonly fType = signal<EventType>('visit');
  protected readonly fTitle = signal('');
  protected readonly fDay = signal('');
  protected readonly fAllDay = signal(false);
  protected readonly fStart = signal('09:00');
  protected readonly fEnd = signal('');
  protected readonly fLocation = signal('');
  protected readonly fDescription = signal('');
  protected readonly dialogError = signal<string | null>(null);
  /** Ostrzeżenie o nakładaniu się z innym zajmującym czas wydarzeniem (nie blokuje zapisu). */
  protected readonly conflict = computed(() => {
    if (this.fAllDay() || !this.fDay() || !BLOCKING_TYPES.has(this.fType())) {
      return null;
    }
    const start = new Date(toIso(this.fDay(), this.fStart()));
    const end = this.fEnd() ? new Date(toIso(this.fDay(), this.fEnd())) : new Date(start.getTime() + DEFAULT_DURATION_MIN * 60000);
    const editingId = this.editing()?.id;
    return (
      [...this.events(), ...this.upcoming()].find(
        (e) => e.id !== editingId && BLOCKING_TYPES.has(e.type) && !e.all_day && new Date(e.starts_at) < end && this.endOf(e) > start,
      ) ?? null
    );
  });

  ngOnInit(): void {
    this.patientsApi.list().subscribe({ next: (p) => this.patients.set(p) });
    this.reload();
    const timer = setInterval(() => this.nowOffset.set(this.computeNowOffset()), 60000);
    this.destroyRef.onDestroy(() => clearInterval(timer));
  }

  protected key(day: Date): string {
    return dayKey(day);
  }

  protected typeStyle(type: EventType) {
    return EVENT_TYPES[type] ?? EVENT_TYPES.other;
  }

  protected color(patientId: number): string {
    return patientColor(patientId);
  }

  protected onColor(patientId: number): string {
    return textOn(patientColor(patientId));
  }

  protected ini(name: string): string {
    return initials(name);
  }

  protected time(iso: string): string {
    return timeOf(new Date(iso));
  }

  protected max(a: number, b: number): number {
    return Math.max(a, b);
  }

  protected longDay(day: Date): string {
    return longDate(day);
  }

  protected shortDay(day: Date): string {
    return new Intl.DateTimeFormat('pl-PL', { weekday: 'short', day: 'numeric', month: 'short' }).format(day);
  }

  protected isWorkday(day: Date): boolean {
    return day.getDay() !== 0 && day.getDay() !== 6;
  }

  protected eventLabel(e: DoctorCalendarEvent): string {
    return `${this.typeStyle(e.type).label}: ${e.title}, pacjent ${e.patient_name}${e.all_day ? ', cały dzień' : ', ' + this.time(e.starts_at)}`;
  }

  protected onDay(day: Date): DoctorCalendarEvent[] {
    return this.byDay().get(dayKey(day)) ?? [];
  }

  protected allDay(day: Date): DoctorCalendarEvent[] {
    return this.onDay(day).filter((e) => e.all_day);
  }

  protected blocks(day: Date): WeekBlock[] {
    const timed = this.onDay(day)
      .filter((e) => !e.all_day)
      .map((event) => {
        const s = new Date(event.starts_at);
        const start = Math.max(s.getHours() * 60 + s.getMinutes(), DAY_START_H * 60);
        const endDate = this.endOf(event);
        const sameDay = dayKey(endDate) === dayKey(s);
        const end = Math.min(sameDay ? endDate.getHours() * 60 + endDate.getMinutes() : DAY_END_H * 60, DAY_END_H * 60);
        return { event, start: Math.min(start, DAY_END_H * 60 - 15), end: Math.max(end, start + 15) };
      });
    return layoutLanes(timed);
  }

  protected setView(view: 'week' | 'month'): void {
    this.view.set(view);
    this.reload();
  }

  protected shift(step: number): void {
    const a = this.anchor();
    this.anchor.set(this.view() === 'week' ? addDays(a, 7 * step) : addMonths(a, step));
    this.reload();
  }

  protected goToday(): void {
    this.anchor.set(new Date());
    this.reload();
  }

  protected openWeekOf(day: Date): void {
    this.anchor.set(day);
    this.setView('week');
  }

  protected togglePatient(id: number): void {
    const next = new Set(this.hidden());
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    this.hidden.set(next);
  }

  protected nextHour(): Date {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours() + 1, 0);
  }

  /** Kliknięcie w siatkę tygodnia → nowe wydarzenie o tej godzinie (zaokrąglenie do 15 min). */
  protected clickGrid(event: MouseEvent, day: Date): void {
    const target = event.currentTarget as HTMLElement;
    const y = event.clientY - target.getBoundingClientRect().top;
    const minutes = Math.floor(y / PX_PER_MIN / 15) * 15 + DAY_START_H * 60;
    this.openNew(new Date(day.getFullYear(), day.getMonth(), day.getDate(), Math.floor(minutes / 60), minutes % 60));
  }

  protected openSlot(slot: FreeSlot): void {
    this.openNew(slot.start, slot.end);
  }

  protected openNew(start: Date, end?: Date): void {
    const finish = end ?? new Date(start.getTime() + this.slotMinutes() * 60000);
    this.editing.set(null);
    this.fPatient.set(null);
    this.fType.set('visit');
    this.fTitle.set('Wizyta');
    this.fDay.set(dayKey(start));
    this.fAllDay.set(false);
    this.fStart.set(timeOf(start));
    this.fEnd.set(timeOf(finish));
    this.fLocation.set('');
    this.fDescription.set('');
    this.show();
  }

  protected openEvent(e: DoctorCalendarEvent): void {
    const start = new Date(e.starts_at);
    this.editing.set(e);
    this.fPatient.set(e.patient_id);
    this.fType.set(e.type);
    this.fTitle.set(e.title);
    this.fDay.set(dayKey(start));
    this.fAllDay.set(e.all_day);
    this.fStart.set(timeOf(start));
    this.fEnd.set(e.ends_at ? timeOf(new Date(e.ends_at)) : '');
    this.fLocation.set(e.location);
    this.fDescription.set(e.description);
    this.show();
  }

  protected close(): void {
    this.dialog.nativeElement.close();
  }

  protected save(): void {
    const editing = this.editing();
    const patientId = editing?.patient_id ?? this.fPatient();
    if (patientId === null) {
      return;
    }
    const allDay = this.fAllDay();
    const input: CalendarEventInput = {
      type: this.fType(),
      title: this.fTitle().trim(),
      starts_at: toIso(this.fDay(), allDay ? '00:00' : this.fStart()),
      ends_at: !allDay && this.fEnd() ? toIso(this.fDay(), this.fEnd()) : null,
      all_day: allDay,
      location: this.fLocation().trim(),
      description: this.fDescription().trim(),
      plan_step_id: editing?.plan_step_id ?? null,
    };
    const request = editing ? this.api.update(patientId, editing.id, input) : this.api.create(patientId, input);
    this.busy.set(true);
    this.dialogError.set(null);
    request.subscribe({
      next: () => {
        this.busy.set(false);
        this.close();
        this.reload();
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.dialogError.set(apiError(err, 'Nie udało się zapisać wydarzenia.'));
      },
    });
  }

  protected remove(e: DoctorCalendarEvent): void {
    if (!confirm(`Usunąć wydarzenie „${e.title}” (${e.patient_name})?`)) {
      return;
    }
    this.busy.set(true);
    this.api.remove(e.patient_id, e.id).subscribe({
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

  private endOf(e: DoctorCalendarEvent): Date {
    return e.ends_at ? new Date(e.ends_at) : new Date(new Date(e.starts_at).getTime() + DEFAULT_DURATION_MIN * 60000);
  }

  private computeNowOffset(): number | null {
    const now = new Date();
    const minutes = now.getHours() * 60 + now.getMinutes();
    if (minutes < DAY_START_H * 60 || minutes > DAY_END_H * 60) {
      return null;
    }
    return (minutes - DAY_START_H * 60) * PX_PER_MIN;
  }

  private show(): void {
    this.dialogError.set(null);
    if (!this.dialog.nativeElement.open) {
      this.dialog.nativeElement.showModal();
    }
  }

  private reload(): void {
    const [start, end] =
      this.view() === 'week'
        ? [this.weekDays()[0], addDays(this.weekDays()[0], 7)]
        : (() => {
            const grid = this.monthDays();
            return [grid[0], addDays(grid[grid.length - 1], 1)];
          })();
    this.loading.set(true);
    this.api.doctorEvents(start, end).subscribe({
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
    const from = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    this.api.doctorEvents(from, addDays(from, FREE_SLOT_DAYS)).subscribe({ next: (e) => this.upcoming.set(e) });
  }
}
