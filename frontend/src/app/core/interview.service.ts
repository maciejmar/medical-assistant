import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface InterviewItem {
  id: number;
  position: number;
  question: string;
  answer: string;
  has_audio: boolean;
  updated_at: string;
}

export interface Interview {
  /** 'approved' – treść zgodna z ostatnio zatwierdzoną wersją; 'draft' – są niezatwierdzone zmiany. */
  status: 'draft' | 'approved';
  approved_at: string | null;
  updated_at: string;
  items: InterviewItem[];
}

export interface InterviewRecording {
  item: InterviewItem;
  transcript: string | null;
  error: string | null;
}

export interface InterviewTemplate {
  questions: string[];
  is_default: boolean;
  updated_at: string | null;
}

export type InterviewEntry = Pick<InterviewItem, 'id' | 'question' | 'answer'>;

const EXTENSIONS: Record<string, string> = {
  'audio/webm': 'webm',
  'audio/ogg': 'ogg',
  'audio/mp4': 'mp4',
  'audio/wav': 'wav',
  'audio/mpeg': 'mp3',
};

@Injectable({ providedIn: 'root' })
export class InterviewService {
  private readonly http = inject(HttpClient);

  get(patientId: number): Observable<Interview> {
    return this.http.get<Interview>(`/api/patients/${patientId}/interview`);
  }

  save(patientId: number, items: InterviewEntry[]): Observable<Interview> {
    return this.http.put<Interview>(`/api/patients/${patientId}/interview`, { items });
  }

  /** Zastępuje pytania wywiadu aktualnym szablonem (odpowiedzi i nagrania są usuwane). */
  reset(patientId: number): Observable<Interview> {
    return this.http.post<Interview>(`/api/patients/${patientId}/interview/reset`, {});
  }

  approve(patientId: number, items: InterviewEntry[]): Observable<Interview> {
    return this.http.post<Interview>(`/api/patients/${patientId}/interview/approve`, { items });
  }

  addQuestion(patientId: number, question: string): Observable<InterviewItem> {
    return this.http.post<InterviewItem>(`/api/patients/${patientId}/interview/items`, { question });
  }

  deleteQuestion(patientId: number, itemId: number): Observable<void> {
    return this.http.delete<void>(`/api/patients/${patientId}/interview/items/${itemId}`);
  }

  /** Wysyła nagranie odpowiedzi; serwer je zapisuje i zwraca transkrypcję (bez zmiany odpowiedzi). */
  uploadRecording(patientId: number, itemId: number, blob: Blob): Observable<InterviewRecording> {
    const baseType = (blob.type || 'audio/webm').split(';')[0];
    const form = new FormData();
    form.append('audio', blob, `odpowiedz.${EXTENSIONS[baseType] ?? 'webm'}`);
    return this.http.put<InterviewRecording>(this.audioUrl(patientId, itemId), form);
  }

  recording(patientId: number, itemId: number): Observable<Blob> {
    return this.http.get(this.audioUrl(patientId, itemId), { responseType: 'blob' });
  }

  deleteRecording(patientId: number, itemId: number): Observable<void> {
    return this.http.delete<void>(this.audioUrl(patientId, itemId));
  }

  template(): Observable<InterviewTemplate> {
    return this.http.get<InterviewTemplate>('/api/admin/interview-template');
  }

  saveTemplate(questions: string[]): Observable<InterviewTemplate> {
    return this.http.put<InterviewTemplate>('/api/admin/interview-template', { questions });
  }

  resetTemplate(): Observable<InterviewTemplate> {
    return this.http.delete<InterviewTemplate>('/api/admin/interview-template');
  }

  private audioUrl(patientId: number, itemId: number): string {
    return `/api/patients/${patientId}/interview/items/${itemId}/audio`;
  }
}
