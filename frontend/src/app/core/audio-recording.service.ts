import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

export type RecorderState = 'idle' | 'recording' | 'processing';

interface TranscriptionResponse {
  text: string;
}

const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/mp4',
];

const EXTENSIONS: Record<string, string> = {
  'audio/webm': 'webm',
  'audio/ogg': 'ogg',
  'audio/mp4': 'mp4',
  'audio/wav': 'wav',
  'audio/mpeg': 'mp3',
};

@Injectable({ providedIn: 'root' })
export class AudioRecordingService {
  private readonly http = inject(HttpClient);

  readonly state = signal<RecorderState>('idle');
  readonly elapsedSeconds = signal(0);
  readonly error = signal<string | null>(null);

  private recorder: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private chunks: Blob[] = [];
  private timerId: ReturnType<typeof setInterval> | null = null;

  get isSupported(): boolean {
    return (
      typeof navigator !== 'undefined' &&
      !!navigator.mediaDevices?.getUserMedia &&
      typeof MediaRecorder !== 'undefined'
    );
  }

  /** Prosi o dostęp do mikrofonu i rozpoczyna nagrywanie (MediaRecorder). */
  async start(): Promise<void> {
    if (this.state() !== 'idle') {
      return;
    }
    this.error.set(null);
    if (!this.isSupported) {
      this.error.set('Ta przeglądarka nie obsługuje nagrywania dźwięku.');
      return;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
    } catch (err) {
      this.error.set(this.describeMicrophoneError(err));
      return;
    }

    const mimeType = MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type));
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream, mimeType ? { mimeType } : undefined);
    this.recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data.size > 0) {
        this.chunks.push(event.data);
      }
    };
    this.recorder.start(1000);
    this.elapsedSeconds.set(0);
    this.timerId = setInterval(() => this.elapsedSeconds.update((s) => s + 1), 1000);
    this.state.set('recording');
  }

  /** Zatrzymuje nagrywanie i zwraca nagranie jako Blob. */
  stop(): Promise<Blob> {
    const recorder = this.recorder;
    if (!recorder || recorder.state === 'inactive') {
      return Promise.reject(new Error('Nagrywanie nie jest aktywne'));
    }
    return new Promise<Blob>((resolve) => {
      recorder.onstop = () => {
        const type = recorder.mimeType || this.chunks[0]?.type || 'audio/webm';
        const blob = new Blob(this.chunks, { type });
        this.releaseResources();
        resolve(blob);
      };
      recorder.stop();
    });
  }

  /** Przerywa nagrywanie bez wysyłki. */
  cancel(): void {
    if (this.recorder && this.recorder.state !== 'inactive') {
      this.recorder.onstop = null;
      this.recorder.stop();
    }
    this.chunks = [];
    this.releaseResources();
  }

  /** Wysyła nagranie asynchronicznie do backendu (/api/audio/transcribe) i zwraca tekst. */
  async transcribe(blob: Blob, language = 'pl'): Promise<string> {
    const baseType = (blob.type || 'audio/webm').split(';')[0];
    const form = new FormData();
    form.append('audio', blob, `nagranie.${EXTENSIONS[baseType] ?? 'webm'}`);
    form.append('language', language);
    const response = await firstValueFrom(
      this.http.post<TranscriptionResponse>('/api/audio/transcribe', form),
    );
    return response.text;
  }

  /** Zatrzymuje nagrywanie i od razu transkrybuje; zwraca tekst lub null przy błędzie. */
  async stopAndTranscribe(language = 'pl'): Promise<string | null> {
    try {
      const blob = await this.stop();
      this.state.set('processing');
      const text = await this.transcribe(blob, language);
      return text;
    } catch {
      this.error.set('Nie udało się przetworzyć nagrania. Spróbuj ponownie.');
      return null;
    } finally {
      this.state.set('idle');
    }
  }

  private releaseResources(): void {
    if (this.timerId !== null) {
      clearInterval(this.timerId);
      this.timerId = null;
    }
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.recorder = null;
    this.state.set('idle');
  }

  private describeMicrophoneError(err: unknown): string {
    const name = err instanceof DOMException ? err.name : '';
    if (name === 'NotAllowedError' || name === 'SecurityError') {
      return 'Brak zgody na użycie mikrofonu. Zezwól na dostęp w ustawieniach przeglądarki.';
    }
    if (name === 'NotFoundError') {
      return 'Nie znaleziono mikrofonu.';
    }
    return 'Nie udało się uruchomić mikrofonu.';
  }
}
