import { splitForSpeech } from './speech.service';

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
