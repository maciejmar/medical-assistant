import { renderMarkdown } from './markdown.pipe';

describe('renderMarkdown', () => {
  it('zamienia nagłówki, pogrubienia i listy na HTML', () => {
    const html = renderMarkdown('### Zalecenia\n**Ćwiczenia:**\n* pionizacja\n* wibracja');
    expect(html).toContain('<h3>Zalecenia</h3>');
    expect(html).toContain('<strong>Ćwiczenia:</strong>');
    expect(html).toContain('<li>pionizacja</li>');
    expect(html).not.toContain('###');
    expect(html).not.toContain('**');
  });

  it('oznacza odnośniki do źródeł, ale nie w kodzie', () => {
    const html = renderMarkdown('Terapia trwa kilka miesięcy [1, 2]. Kod: `tab[0]`');
    expect(html).toContain('<sup class="md-cite">1, 2</sup>');
    expect(html).toContain('<code>tab[0]</code>');
  });

  it('surowy HTML z odpowiedzi pokazuje jako tekst', () => {
    const html = renderMarkdown('<script>alert(1)</script>');
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('linki otwiera w nowej karcie', () => {
    expect(renderMarkdown('[PTL](https://example.org)')).toContain('target="_blank" rel="noopener noreferrer"');
  });
});
