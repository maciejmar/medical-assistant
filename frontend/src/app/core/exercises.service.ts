import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface ExerciseInput {
  name: string;
  number: string;
  goal: string;
  tools: string;
  description: string;
  page: number | null;
  verified: boolean;
}

export interface Exercise extends ExerciseInput {
  id: number;
  document_id: number;
  document_title: string;
  complete: boolean;
  updated_at: string;
}

export interface ExerciseCandidate {
  document_id: number;
  title: string;
  markers: number;
  exercises: number;
}

export interface ExtractionStatus {
  status: 'running' | 'done' | 'failed' | 'cancelled';
  document_ids: number[];
  total_windows: number;
  done_windows: number;
  found: number;
  tokens: number;
  current: string;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface ExerciseMatch {
  name: string;
  score: number;
  exercise: Exercise | null;
}

/** Katalog ćwiczeń wyodrębnionych z bazy wiedzy (panel administratora). */
@Injectable({ providedIn: 'root' })
export class ExercisesService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/admin/exercises';

  candidates(): Observable<ExerciseCandidate[]> {
    return this.http.get<ExerciseCandidate[]>(`${this.base}/candidates`);
  }

  list(documentId?: number): Observable<Exercise[]> {
    const params: Record<string, string> = documentId ? { document_id: String(documentId) } : {};
    return this.http.get<Exercise[]>(this.base, { params });
  }

  status(): Observable<ExtractionStatus | null> {
    return this.http.get<ExtractionStatus | null>(`${this.base}/extract`);
  }

  extract(documentIds: number[]): Observable<ExtractionStatus> {
    return this.http.post<ExtractionStatus>(`${this.base}/extract`, { document_ids: documentIds });
  }

  cancel(): Observable<ExtractionStatus> {
    return this.http.post<ExtractionStatus>(`${this.base}/extract/cancel`, {});
  }

  update(id: number, body: ExerciseInput): Observable<Exercise> {
    return this.http.put<Exercise>(`${this.base}/${id}`, body);
  }

  remove(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  match(text: string): Observable<ExerciseMatch[]> {
    return this.http.post<ExerciseMatch[]>(`${this.base}/match`, { text });
  }
}
