import { Injectable, signal } from '@angular/core';

const MAX_CHUNK = 200;

/**
 * Dzieli tekst na krótkie fragmenty (po zdaniach, a zbyt długie zdania – po słowach).
 * Chrome przerywa pojedynczą wypowiedź syntezatora po ok. 15 s, więc długą notatkę
 * odtwarzamy jako kolejkę krótszych fragmentów.
 */
export function splitForSpeech(text: string, maxLength = MAX_CHUNK): string[] {
  const sentences = text
    .replace(/\s+/g, ' ')
    .trim()
    .split(/(?<=[.!?…;:])\s+/)
    .filter(Boolean);
  const chunks: string[] = [];
  for (const sentence of sentences) {
    if (sentence.length <= maxLength) {
      chunks.push(sentence);
      continue;
    }
    let current = '';
    for (const word of sentence.split(' ')) {
      if (current && current.length + 1 + word.length > maxLength) {
        chunks.push(current);
        current = word;
      } else {
        current = current ? `${current} ${word}` : word;
      }
    }
    if (current) {
      chunks.push(current);
    }
  }
  return chunks;
}

/**
 * Odczyt tekstu na głos syntezatorem wbudowanym w przeglądarkę (Web Speech API) – bez wysyłania
 * treści na serwer aplikacji. Notatki zawierają dane pacjentów, dlatego preferowany jest polski
 * głos LOKALNY systemu (np. „Paulina” w Windows); głosy sieciowe przeglądarki przesyłają tekst
 * do usługi zewnętrznej i są używane tylko wtedy, gdy lokalnego polskiego głosu brak.
 */
@Injectable({ providedIn: 'root' })
export class SpeechService {
  /** Identyfikator aktualnie odczytywanego elementu (np. notatki) albo null. */
  readonly speakingId = signal<string | null>(null);
  readonly isSupported = typeof window !== 'undefined' && 'speechSynthesis' in window;

  private session = 0;

  speak(id: string, text: string): void {
    if (!this.isSupported || !text.trim()) {
      return;
    }
    this.stop();
    const session = ++this.session;
    const chunks = splitForSpeech(text);
    const voice = this.polishVoice();
    this.speakingId.set(id);
    chunks.forEach((chunk, index) => {
      const utterance = new SpeechSynthesisUtterance(chunk);
      utterance.lang = 'pl-PL';
      if (voice) {
        utterance.voice = voice;
      }
      const finish = () => {
        if (session === this.session && index === chunks.length - 1) {
          this.speakingId.set(null);
        }
      };
      utterance.onend = finish;
      utterance.onerror = finish;
      window.speechSynthesis.speak(utterance);
    });
  }

  stop(): void {
    if (!this.isSupported) {
      return;
    }
    this.session++;
    window.speechSynthesis.cancel();
    this.speakingId.set(null);
  }

  toggle(id: string, text: string): void {
    if (this.speakingId() === id) {
      this.stop();
    } else {
      this.speak(id, text);
    }
  }

  private polishVoice(): SpeechSynthesisVoice | null {
    const polish = window.speechSynthesis
      .getVoices()
      .filter((voice) => voice.lang.toLowerCase().startsWith('pl'));
    return polish.find((voice) => voice.localService) ?? polish[0] ?? null;
  }
}
