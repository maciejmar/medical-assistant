import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface TemplateInput {
  name: string;
  description: string;
  body: string;
  requires_patient: boolean;
  long_answer: boolean;
  position: number;
  /** Tylko administrator: szablon wspólny dla wszystkich. */
  shared: boolean;
}

export interface PromptTemplate extends TemplateInput {
  id: number;
  editable: boolean;
  updated_at: string;
}

export interface TemplateCoverage {
  name: string;
  found: boolean;
  exercise_name: string;
  source: string;
}

/** Szablony promptów (pastylki w czacie): wspólne i własne. */
@Injectable({ providedIn: 'root' })
export class TemplatesService {
  private readonly http = inject(HttpClient);

  list(): Observable<PromptTemplate[]> {
    return this.http.get<PromptTemplate[]>('/api/templates');
  }

  create(body: TemplateInput): Observable<PromptTemplate> {
    return this.http.post<PromptTemplate>('/api/templates', body);
  }

  update(id: number, body: TemplateInput): Observable<PromptTemplate> {
    return this.http.put<PromptTemplate>(`/api/templates/${id}`, body);
  }

  remove(id: number): Observable<void> {
    return this.http.delete<void>(`/api/templates/${id}`);
  }

  copy(id: number): Observable<PromptTemplate> {
    return this.http.post<PromptTemplate>(`/api/templates/${id}/copy`, {});
  }

  coverage(body: string): Observable<TemplateCoverage[]> {
    return this.http.post<TemplateCoverage[]>('/api/templates/coverage', { body });
  }
}
