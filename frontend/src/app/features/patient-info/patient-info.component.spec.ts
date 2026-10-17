import { PatientChatMessage } from '../../shared/models';
import { toExchanges } from './patient-info.component';

function msg(
  id: number,
  role: 'user' | 'assistant',
  conversation_id: string,
  content: string,
): PatientChatMessage {
  return {
    id,
    role,
    conversation_id,
    content,
    sources: null,
    total_tokens: 0,
    created_at: `2026-01-01T00:00:0${id}Z`,
  };
}

describe('toExchanges', () => {
  it('łączy pytania z odpowiedziami w obrębie rozmowy, najnowsze na górze', () => {
    const exchanges = toExchanges([
      msg(1, 'user', 'a', 'P1'),
      msg(2, 'user', 'b', 'P2'),
      msg(3, 'assistant', 'a', 'O1'),
      msg(4, 'assistant', 'b', 'O2'),
      msg(5, 'user', 'a', 'P3'),
    ]);
    expect(exchanges.map((e) => [e.question, e.answer])).toEqual([
      ['P3', null],
      ['P2', 'O2'],
      ['P1', 'O1'],
    ]);
  });
});
