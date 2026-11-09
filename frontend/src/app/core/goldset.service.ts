import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface GoldsetItemInput {
  title: string;
  question: string;
  reference_answer: string;
}

export interface GoldsetItem extends GoldsetItemInput {
  id: number;
  position: number;
  updated_at: string;
}

export interface GoldsetRun {
  id: number;
  status: 'running' | 'done' | 'failed' | 'cancelled';
  total: number;
  done: number;
  errors: number;
  note: string;
  settings: Record<string, string | number>;
  avg_score: number | null;
  avg_similarity: number | null;
  avg_latency_ms: number | null;
  total_tokens: number;
  started_at: string;
  finished_at: string | null;
}

export interface GoldsetVerdict {
  score?: number;
  covered?: string[];
  missing?: string[];
  errors?: string[];
  order_ok?: boolean;
  comment?: string;
}

export interface GoldsetResult {
  id: number;
  item_id: number | null;
  title: string;
  question: string;
  answer: string;
  sources: { index: number; title: string }[];
  verdict: GoldsetVerdict;
  score: number;
  similarity: number;
  latency_ms: number;
  tokens: number;
  judge_tokens: number;
  status: 'ok' | 'error';
  error: string | null;
}

export interface GoldsetRunDetail {
  run: GoldsetRun;
  results: GoldsetResult[];
}

/** Testy jakości asystenta (goldset) – panel administratora. */
@Injectable({ providedIn: 'root' })
export class GoldsetService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/admin/goldset';

  items(): Observable<GoldsetItem[]> {
    return this.http.get<GoldsetItem[]>(this.base);
  }

  parse(text: string): Observable<GoldsetItemInput[]> {
    return this.http.post<GoldsetItemInput[]>(`${this.base}/parse`, { text });
  }

  replace(items: GoldsetItemInput[]): Observable<GoldsetItem[]> {
    return this.http.put<GoldsetItem[]>(this.base, { items });
  }

  update(id: number, item: GoldsetItemInput): Observable<GoldsetItem> {
    return this.http.put<GoldsetItem>(`${this.base}/${id}`, item);
  }

  remove(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  runs(): Observable<GoldsetRun[]> {
    return this.http.get<GoldsetRun[]>(`${this.base}/runs`);
  }

  startRun(note: string): Observable<GoldsetRun> {
    return this.http.post<GoldsetRun>(`${this.base}/runs`, { note });
  }

  run(id: number): Observable<GoldsetRunDetail> {
    return this.http.get<GoldsetRunDetail>(`${this.base}/runs/${id}`);
  }

  cancelRun(id: number): Observable<GoldsetRun> {
    return this.http.post<GoldsetRun>(`${this.base}/runs/${id}/cancel`, {});
  }

  deleteRun(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/runs/${id}`);
  }
}
