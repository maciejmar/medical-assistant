import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import {
  NoteSource,
  Patient,
  PatientAccount,
  PatientChatMessage,
  PatientInput,
  PatientNote,
  PatientNotification,
  RecentNote,
  Recommendation,
} from '../shared/models';

export interface RecommendationInput {
  title: string;
  content: string;
  notify: boolean;
}

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

  chatHistory(id: number): Observable<PatientChatMessage[]> {
    return this.http.get<PatientChatMessage[]>(`/api/patients/${id}/chat-history`);
  }

  account(id: number): Observable<PatientAccount | null> {
    return this.http.get<PatientAccount | null>(`/api/patients/${id}/account`);
  }

  linkAccount(
    id: number,
    input: { email: string; full_name: string | null; password: string | null },
  ): Observable<PatientAccount> {
    return this.http.put<PatientAccount>(`/api/patients/${id}/account`, input);
  }

  unlinkAccount(id: number): Observable<void> {
    return this.http.delete<void>(`/api/patients/${id}/account`);
  }

  recommendations(id: number): Observable<Recommendation[]> {
    return this.http.get<Recommendation[]>(`/api/patients/${id}/recommendations`);
  }

  addRecommendation(id: number, input: RecommendationInput): Observable<Recommendation> {
    return this.http.post<Recommendation>(`/api/patients/${id}/recommendations`, input);
  }

  updateRecommendation(
    id: number,
    recommendationId: number,
    input: RecommendationInput,
  ): Observable<Recommendation> {
    return this.http.put<Recommendation>(
      `/api/patients/${id}/recommendations/${recommendationId}`,
      input,
    );
  }

  removeRecommendation(id: number, recommendationId: number): Observable<void> {
    return this.http.delete<void>(`/api/patients/${id}/recommendations/${recommendationId}`);
  }

  notifications(id: number): Observable<PatientNotification[]> {
    return this.http.get<PatientNotification[]>(`/api/patients/${id}/notifications`);
  }

  sendNotification(id: number, subject: string, body: string): Observable<PatientNotification> {
    return this.http.post<PatientNotification>(`/api/patients/${id}/notifications`, {
      subject,
      body,
    });
  }
}
