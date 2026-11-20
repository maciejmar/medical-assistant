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

/** Formularze: uniwersalny wywiad i badanie (domyślny) oraz karta badania – diagnoza ankyloglosji. */
export type InterviewForm = 'interview' | 'ankyloglossia';

export interface QuestionHint {
  label: string;
  text: string;
}

export interface ParsedQuestion {
  title: string;
  hints: QuestionHint[];
  /** Odpowiedź w trzech polach: nagłos / śródgłos / wygłos (artykulacja). */
  positions: boolean;
}

const HINT_SEPARATOR = ' | ';
const POSITIONS_FLAG = '@pozycje';

/** Rozbiór pytania szablonu: „Tytuł | Etykieta: podpowiedź | … | @pozycje”. */
export function parseQuestion(question: string): ParsedQuestion {
  const [title, ...rest] = question.split(HINT_SEPARATOR);
  const hints: QuestionHint[] = [];
  let positions = false;
  for (const raw of rest) {
    const part = raw.trim();
    if (!part) continue;
    if (part.toLowerCase() === POSITIONS_FLAG) {
      positions = true;
      continue;
    }
    const colon = part.indexOf(':');
    hints.push(colon > 0 && colon < 40 ? { label: part.slice(0, colon).trim(), text: part.slice(colon + 1).trim() } : { label: '', text: part });
  }
  return { title: title.trim(), hints, positions };
}

export const POSITION_LABELS = ['Nagłos', 'Śródgłos', 'Wygłos'] as const;
export type Positions = [string, string, string];

/** Odpowiedź „Nagłos: …\nŚródgłos: …\nWygłos: …” → trzy pola (tekst bez etykiet trafia do nagłosu). */
export function parsePositions(answer: string): Positions {
  const result: Positions = ['', '', ''];
  const loose: string[] = [];
  for (const line of answer.split('\n')) {
    const match = /^\s*(Nagłos|Śródgłos|Wygłos)\s*:\s*(.*)$/i.exec(line);
    if (match) {
      const index = POSITION_LABELS.findIndex((l) => l.toLowerCase() === match[1].toLowerCase());
      result[index] = match[2].trim();
    } else if (line.trim()) {
      loose.push(line.trim());
    }
  }
  if (loose.length) {
    result[0] = [result[0], ...loose].filter(Boolean).join(' ');
  }
  return result;
}

export function formatPositions(values: Positions): string {
  return values
    .map((v, i) => (v.trim() ? `${POSITION_LABELS[i]}: ${v.trim()}` : ''))
    .filter(Boolean)
    .join('\n');
}

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

  get(patientId: number, form: InterviewForm = 'interview'): Observable<Interview> {
    return this.http.get<Interview>(`/api/patients/${patientId}/interview`, { params: { form } });
  }

  save(patientId: number, items: InterviewEntry[], form: InterviewForm = 'interview'): Observable<Interview> {
    return this.http.put<Interview>(`/api/patients/${patientId}/interview`, { items }, { params: { form } });
  }

  /** Zastępuje pytania formularza aktualnym szablonem (odpowiedzi i nagrania są usuwane). */
  reset(patientId: number, form: InterviewForm = 'interview'): Observable<Interview> {
    return this.http.post<Interview>(`/api/patients/${patientId}/interview/reset`, {}, { params: { form } });
  }

  approve(patientId: number, items: InterviewEntry[], form: InterviewForm = 'interview'): Observable<Interview> {
    return this.http.post<Interview>(`/api/patients/${patientId}/interview/approve`, { items }, { params: { form } });
  }

  addQuestion(patientId: number, question: string, form: InterviewForm = 'interview'): Observable<InterviewItem> {
    return this.http.post<InterviewItem>(`/api/patients/${patientId}/interview/items`, { question }, { params: { form } });
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

  template(form: InterviewForm = 'interview'): Observable<InterviewTemplate> {
    return this.http.get<InterviewTemplate>('/api/admin/interview-template', { params: { form } });
  }

  saveTemplate(questions: string[], form: InterviewForm = 'interview'): Observable<InterviewTemplate> {
    return this.http.put<InterviewTemplate>('/api/admin/interview-template', { questions }, { params: { form } });
  }

  resetTemplate(form: InterviewForm = 'interview'): Observable<InterviewTemplate> {
    return this.http.delete<InterviewTemplate>('/api/admin/interview-template', { params: { form } });
  }

  private audioUrl(patientId: number, itemId: number): string {
    return `/api/patients/${patientId}/interview/items/${itemId}/audio`;
  }
}
