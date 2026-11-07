import { Pipe, PipeTransform } from '@angular/core';
import { Marked } from 'marked';

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/**
 * Parser Markdownu dla odpowiedzi modelu: GFM (tabele, listy), pojedynczy enter = nowa linia.
 * Surowy HTML z odpowiedzi jest wyświetlany jako tekst (nie interpretowany), a wynik i tak przechodzi
 * przez sanitizer Angulara przy wiązaniu [innerHTML].
 */
const parser = new Marked({
  gfm: true,
  breaks: true,
  renderer: {
    html: (html: string) => escapeHtml(html),
    link: (href: string, title: string | null | undefined, text: string) =>
      `<a href="${escapeHtml(href)}"${title ? ` title="${escapeHtml(title)}"` : ''} target="_blank" rel="noopener noreferrer">${text}</a>`,
  },
});

/** Odnośniki do źródeł: [1], [1, 2], [1–3] → znaczniki `md-cite` (poza blokami kodu). */
const CITATION = /\[(\d+(?:\s*[,–-]\s*\d+)*)\]/g;

function styleCitations(html: string): string {
  return html
    .split(/(<pre[\s\S]*?<\/pre>|<code>[\s\S]*?<\/code>)/)
    .map((part, i) => (i % 2 === 1 ? part : part.replace(CITATION, '<sup class="md-cite">$1</sup>')))
    .join('');
}

export function renderMarkdown(text: string | null | undefined): string {
  if (!text) {
    return '';
  }
  return styleCitations(parser.parse(text, { async: false }) as string);
}

/** `{{ tekst | markdown }}` do wiązania `[innerHTML]` – elegancki widok odpowiedzi asystenta. */
@Pipe({ name: 'markdown', standalone: true })
export class MarkdownPipe implements PipeTransform {
  transform(text: string | null | undefined): string {
    return renderMarkdown(text);
  }
}
