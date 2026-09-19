import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ChatEvent, ConversationSummary, StoredChatMessage } from '../shared/models';
import { AuthService } from './auth.service';

/** Parsuje ramkę SSE ("event: x\ndata: {...}") na obiekt zdarzenia. */
export function parseSseFrame(frame: string): ChatEvent | null {
  const dataLines = frame
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart());
  if (dataLines.length === 0) {
    return null;
  }
  try {
    return JSON.parse(dataLines.join('\n')) as ChatEvent;
  } catch {
    return null;
  }
}

@Injectable({ providedIn: 'root' })
export class ChatService {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);

  /**
   * Strumieniuje odpowiedź czatu (POST + Server-Sent Events). EventSource nie wspiera POST
   * ani nagłówka Authorization, dlatego używamy fetch i ReadableStream.
   */
  async *stream(
    body: { message: string; conversation_id: string | null; patient_id: number | null },
    signal: AbortSignal,
  ): AsyncGenerator<ChatEvent> {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        Authorization: `Bearer ${this.auth.token() ?? ''}`,
      },
      body: JSON.stringify(body),
      signal,
    });

    if (response.status === 401) {
      this.auth.logout();
    }
    if (!response.ok || !response.body) {
      yield { type: 'error', message: await this.errorMessage(response) };
      return;
    }

    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = '';
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        buffer += value.replace(/\r\n/g, '\n');
        let boundary = buffer.indexOf('\n\n');
        while (boundary !== -1) {
          const event = parseSseFrame(buffer.slice(0, boundary));
          buffer = buffer.slice(boundary + 2);
          if (event) {
            yield event;
          }
          boundary = buffer.indexOf('\n\n');
        }
      }
      const rest = parseSseFrame(buffer);
      if (rest) {
        yield rest;
      }
    } finally {
      reader.releaseLock();
    }
  }

  conversations(): Observable<ConversationSummary[]> {
    return this.http.get<ConversationSummary[]>('/api/chat/conversations');
  }

  conversation(id: string): Observable<StoredChatMessage[]> {
    return this.http.get<StoredChatMessage[]>(`/api/chat/conversations/${id}`);
  }

  deleteConversation(id: string): Observable<void> {
    return this.http.delete<void>(`/api/chat/conversations/${id}`);
  }

  private async errorMessage(response: Response): Promise<string> {
    try {
      const data = (await response.json()) as { detail?: string };
      if (typeof data.detail === 'string') {
        return data.detail;
      }
    } catch {
      /* brak treści JSON */
    }
    return `Błąd serwera (${response.status})`;
  }
}
