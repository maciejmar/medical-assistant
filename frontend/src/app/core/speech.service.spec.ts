import { TestBed, fakeAsync, flushMicrotasks, tick } from '@angular/core/testing';
import { SPEECH_SYNTHESIS, SpeechService, splitForSpeech } from './speech.service';

describe('splitForSpeech', () => {
  it('dzieli tekst na zdania i scala białe znaki', () => {
    expect(splitForSpeech('Pacjent ćwiczy  pionizację.\nPoprawa wyraźna! Czy kontynuować?')).toEqual([
      'Pacjent ćwiczy pionizację.',
      'Poprawa wyraźna!',
      'Czy kontynuować?',
    ]);
  });

  it('zbyt długie zdanie tnie po słowach, nie w środku wyrazu', () => {
    const sentence = Array.from({ length: 60 }, (_, i) => `słowo${i}`).join(' ');
    const chunks = splitForSpeech(sentence, 100);
    expect(chunks.length).toBeGreaterThan(1);
    expect(chunks.every((c) => c.length <= 100)).toBeTrue();
    expect(chunks.join(' ')).toBe(sentence);
  });

  it('pusty tekst daje pustą listę', () => {
    expect(splitForSpeech('   ')).toEqual([]);
  });
});

/** Atrapa syntezatora: zapamiętuje wypowiedzi, pozwala ręcznie „dokończyć” bieżącą. */
class FakeSynth {
  speaking = false;
  pending = false;
  spoken: SpeechSynthesisUtterance[] = [];
  cancels = 0;

  speak(utterance: SpeechSynthesisUtterance): void {
    this.spoken.push(utterance);
    this.speaking = true;
  }
  cancel(): void {
    this.cancels++;
    this.speaking = false;
    const last = this.spoken[this.spoken.length - 1];
    last?.onerror?.({ error: 'interrupted' } as SpeechSynthesisErrorEvent);
  }
  resume(): void {}
  getVoices(): SpeechSynthesisVoice[] {
    return [];
  }
  removeEventListener(): void {}
  addEventListener(_: string, callback: () => void): void {
    callback();
  }
  finishCurrent(): void {
    const last = this.spoken[this.spoken.length - 1];
    this.speaking = false;
    last.onend?.({} as SpeechSynthesisEvent);
  }
}

describe('SpeechService', () => {
  let synth: FakeSynth;
  let service: SpeechService;

  beforeEach(() => {
    synth = new FakeSynth();
    TestBed.configureTestingModule({ providers: [{ provide: SPEECH_SYNTHESIS, useValue: synth }] });
    service = TestBed.inject(SpeechService);
  });

  it('odtwarza fragmenty po kolei – następny dopiero po zakończeniu poprzedniego', fakeAsync(() => {
    service.toggle('note-1', 'Pierwsze zdanie. Drugie zdanie. Trzecie.');
    flushMicrotasks();
    expect(synth.spoken.map((u) => u.text)).toEqual(['Pierwsze zdanie.']);
    expect(service.speakingId()).toBe('note-1');

    synth.finishCurrent();
    synth.finishCurrent();
    expect(synth.spoken.map((u) => u.text)).toEqual(['Pierwsze zdanie.', 'Drugie zdanie.', 'Trzecie.']);
    synth.finishCurrent();
    expect(service.speakingId()).toBeNull();
  }));

  it('drugie kliknięcie zatrzymuje odczyt i nic nie gra dalej', fakeAsync(() => {
    service.toggle('note-1', 'Raz. Dwa.');
    flushMicrotasks();
    service.toggle('note-1', 'Raz. Dwa.');
    expect(service.speakingId()).toBeNull();
    expect(synth.cancels).toBe(1);

    synth.spoken[0].onend?.({} as SpeechSynthesisEvent); // spóźnione zdarzenie po stop()
    expect(synth.spoken.length).toBe(1);
  }));

  it('przy przerwaniu innego odczytu czeka chwilę po cancel() przed speak()', fakeAsync(() => {
    service.toggle('note-1', 'Długa notatka.');
    flushMicrotasks();
    service.toggle('note-2', 'Inna notatka.');
    flushMicrotasks();
    expect(service.speakingId()).toBe('note-2');
    expect(synth.spoken.length).toBe(1); // jeszcze nie – trwa pauza po cancel()

    tick(150);
    expect(synth.spoken.map((u) => u.text)).toEqual(['Długa notatka.', 'Inna notatka.']);
  }));
});
