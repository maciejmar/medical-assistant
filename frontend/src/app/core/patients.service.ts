import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { NoteSource, Patient, PatientInput, PatientNote, RecentNote } from '../shared/models';

@Injectable({ providedIn: 'root' })
export class PatientsService {
  private readonly http = inject(HttpClient);

  list(): Observable<Patient[]> {
    return this.http.get<Patient[]>('/api/patients');
  }

  get(id: number): Observable<Patient> {
    return this.http.get<Patient>(`/api/patients/${id}`);
  }

  create(input: PatientInput): Observable<Patient> {
    return this.http.post<Patient>('/api/patients', input);
  }

  update(id: number, input: PatientInput): Observable<Patient> {
    return this.http.put<Patient>(`/api/patients/${id}`, input);
  }

  remove(id: number): Observable<void> {
    return this.http.delete<void>(`/api/patients/${id}`);
  }

  notes(id: number): Observable<PatientNote[]> {
    return this.http.get<PatientNote[]>(`/api/patients/${id}/notes`);
  }

  addNote(id: number, content: string, source: NoteSource): Observable<PatientNote> {
    return this.http.post<PatientNote>(`/api/patients/${id}/notes`, { content, source });
  }

  removeNote(patientId: number, noteId: number): Observable<void> {
    return this.http.delete<void>(`/api/patients/${patientId}/notes/${noteId}`);
  }

  recentNotes(limit = 8): Observable<RecentNote[]> {
    return this.http.get<RecentNote[]>('/api/patients/notes/recent', { params: { limit } });
  }
}
