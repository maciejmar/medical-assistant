import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export type EventType = 'visit' | 'consultation' | 'stage_start' | 'stage_end' | 'other';

export interface CalendarEvent {
  id: number;
  type: EventType;
  title: string;
  starts_at: string;
  ends_at: string | null;
  all_day: boolean;
  location: string;
  description: string;
  plan_step_id: number | null;
  plan_step_title: string | null;
  created_by_role: 'doctor' | 'patient';
  /** Czy bieżący użytkownik może zmienić wpis (pacjent – tylko własne). */
  editable: boolean;
  updated_at: string;
}

/** Wydarzenie w zbiorczym kalendarzu lekarza (wszyscy pacjenci). */
export interface DoctorCalendarEvent extends CalendarEvent {
  patient_id: number;
  patient_name: string;
}

export interface CalendarEventInput {
  type: EventType;
  title: string;
  starts_at: string;
  ends_at: string | null;
  all_day: boolean;
  location: string;
  description: string;
  plan_step_id: number | null;
}

/**
 * Kalendarz pacjenta. `patientId` = widok lekarza (/patients/{id}/events),
 * `null` = widok pacjenta (/portal/events) – te same wydarzenia, inne uprawnienia.
 */
@Injectable({ providedIn: 'root' })
export class CalendarService {
  private readonly http = inject(HttpClient);

  list(patientId: number | null, start?: Date, end?: Date): Observable<CalendarEvent[]> {
    const params: Record<string, string> = {};
    if (start) {
      params['start'] = start.toISOString();
    }
    if (end) {
      params['end'] = end.toISOString();
    }
    return this.http.get<CalendarEvent[]>(this.base(patientId), { params });
  }

  /** Wszystkie wydarzenia pacjentów zalogowanego lekarza w zakresie dat. */
  doctorEvents(start: Date, end: Date): Observable<DoctorCalendarEvent[]> {
    return this.http.get<DoctorCalendarEvent[]>('/api/calendar/events', {
      params: { start: start.toISOString(), end: end.toISOString() },
    });
  }

  create(patientId: number | null, input: CalendarEventInput): Observable<CalendarEvent> {
    return this.http.post<CalendarEvent>(this.base(patientId), input);
  }

  update(patientId: number | null, id: number, input: CalendarEventInput): Observable<CalendarEvent> {
    return this.http.put<CalendarEvent>(`${this.base(patientId)}/${id}`, input);
  }

  remove(patientId: number | null, id: number): Observable<void> {
    return this.http.delete<void>(`${this.base(patientId)}/${id}`);
  }

  private base(patientId: number | null): string {
    return patientId === null ? '/api/portal/events' : `/api/patients/${patientId}/events`;
  }
}
