import { InjectionToken, Injectable, inject, signal } from '@angular/core';

/** Syntezator mowy przeglądarki (w testach podstawiany atrapą); null, gdy brak obsługi. */
export const SPEECH_SYNTHESIS = new InjectionToken<SpeechSynthesis | null>('SPEECH_SYNTHESIS', {
  providedIn: 'root',
  factory: () =>
    typeof window !== 'undefined' && 'speechSynthesis' in window ? window.speechSynthesis : null,
});

const MAX_CHUNK = 200;
/** Pauza po cancel() przed nowym speak() – Chrome gubi wypowiedzi dodane zaraz po cancel(). */
const RESTART_DELAY_MS = 150;
/** Ile czekać na listę głosów (w Chrome ładuje się asynchronicznie przy pierwszym użyciu). */
const VOICES_TIMEOUT_MS = 1500;

/**
 * Dzieli tekst na krótkie fragmenty (po zdaniach, a zbyt długie zdania – po słowach).
 * Chrome przerywa pojedynczą wypowiedź syntezatora po ok. 15 s, więc długą notatkę
 * odtwarzamy jako serię krótszych fragmentów.
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
 *
 * Odporność na błędy Chrome: fragmenty odtwarzane po kolei (następny po zakończeniu poprzedniego),
 * bieżąca wypowiedź trzymana w polu (inaczej Chrome potrafi ją usunąć z pamięci w trakcie odczytu
 * i dźwięk się urywa), a po cancel() nowy odczyt startuje z krótkim opóźnieniem.
 */
@Injectable({ providedIn: 'root' })
export class SpeechService {
  /** Identyfikator aktualnie odczytywanego elementu (np. notatki) albo null. */
  readonly speakingId = signal<string | null>(null);
  private readonly synth = inject(SPEECH_SYNTHESIS);
  readonly isSupported = this.synth !== null;

  private session = 0;
  private current: SpeechSynthesisUtterance | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;

  toggle(id: string, text: string): void {
    if (this.speakingId() === id) {
      this.stop();
    } else {
      void this.speak(id, text);
    }
  }

  async speak(id: string, text: string): Promise<void> {
    const synth = this.synth;
    const chunks = splitForSpeech(text);
    if (!synth || chunks.length === 0) {
      return;
    }
    const busy = synth.speaking || synth.pending;
    this.stop();
    const session = this.session;
    this.speakingId.set(id);
    const voice = await this.polishVoice(synth);
    if (busy) {
      await new Promise<void>((resolve) => {
        this.timer = setTimeout(resolve, RESTART_DELAY_MS);
      });
    }
    if (session !== this.session) {
      return; // w międzyczasie kliknięto „stop” albo inną notatkę
    }
    synth.resume(); // Chrome potrafi utknąć w stanie „paused” po wcześniejszym przerwaniu
    this.playChunk(synth, chunks, 0, voice, session);
  }

  stop(): void {
    this.session++;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.current = null;
    if (this.synth && (this.synth.speaking || this.synth.pending)) {
      this.synth.cancel();
    }
    this.speakingId.set(null);
  }

  private playChunk(
    synth: SpeechSynthesis,
    chunks: string[],
    index: number,
    voice: SpeechSynthesisVoice | null,
    session: number,
  ): void {
    if (session !== this.session) {
      return;
    }
    if (index >= chunks.length) {
      this.current = null;
      this.speakingId.set(null);
      return;
    }
    const utterance = new SpeechSynthesisUtterance(chunks[index]);
    utterance.lang = 'pl-PL';
    if (voice) {
      utterance.voice = voice;
    }
    utterance.onend = () => this.playChunk(synth, chunks, index + 1, voice, session);
    utterance.onerror = (event) => {
      // „interrupted”/„canceled” to skutek naszego stop() – nic nie robimy; inne błędy kończą odczyt.
      if (session === this.session && !['interrupted', 'canceled'].includes(event.error)) {
        this.current = null;
        this.speakingId.set(null);
      }
    };
    this.current = utterance;
    synth.speak(utterance);
  }

  /** Polski głos – lokalny w pierwszej kolejności; czeka na listę głosów przy pierwszym użyciu. */
  private async polishVoice(synth: SpeechSynthesis): Promise<SpeechSynthesisVoice | null> {
    let voices = synth.getVoices();
    if (voices.length === 0) {
      voices = await new Promise<SpeechSynthesisVoice[]>((resolve) => {
        let timeout: ReturnType<typeof setTimeout> | undefined;
        const done = () => {
          clearTimeout(timeout);
          synth.removeEventListener('voiceschanged', done);
          resolve(synth.getVoices());
        };
        timeout = setTimeout(done, VOICES_TIMEOUT_MS);
        synth.addEventListener('voiceschanged', done, { once: true });
      });
    }
    const polish = voices.filter((voice) => voice.lang.toLowerCase().startsWith('pl'));
    return polish.find((voice) => voice.localService) ?? polish[0] ?? null;
  }
}
