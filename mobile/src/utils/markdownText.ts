import {Lexer, type Token, type Tokens} from 'marked';

/** What a reader sees of a markdown text, without its markup: lines, lists and code stay as they read. */
export function markdownText(markdown: string): string {
  let tokens: Token[];
  try {
    tokens = new Lexer({gfm: true}).lex(markdown);
  } catch {
    return markdown.trim();
  }
  return blocks(tokens, '\n\n').replace(/\n{3,}/g, '\n\n').trim();
}

const stripTags = (html: string) => html.replace(/<[^>]*>/g, '');

function inline(tokens: Token[] | undefined): string {
  return (tokens ?? []).map(inlineToken).join('');
}

function inlineToken(token: Token): string {
  switch (token.type) {
    case 'strong':
    case 'em':
    case 'del':
    case 'link':
      return inline((token as Tokens.Generic).tokens);
    case 'image':
      return (token as Tokens.Image).text;
    case 'br':
      return '\n';
    case 'html':
      return stripTags((token as Tokens.HTML).text);
    case 'checkbox':
      return (token as Tokens.Checkbox).checked ? '☑ ' : '☐ ';
    case 'text': {
      const text = token as Tokens.Text;
      return text.tokens ? inline(text.tokens) : text.text;
    }
    default:
      return 'text' in token && typeof token.text === 'string' ? token.text : token.raw;
  }
}

function blocks(tokens: Token[], gap: string): string {
  return tokens
    .map(block)
    .filter(part => part !== '')
    .join(gap);
}

function block(token: Token): string {
  switch (token.type) {
    case 'space':
    case 'hr':
      return '';
    case 'heading':
    case 'paragraph':
      return inline((token as Tokens.Generic).tokens);
    case 'text': {
      const text = token as Tokens.Text;
      return text.tokens ? inline(text.tokens) : text.text;
    }
    case 'code':
      return (token as Tokens.Code).text;
    case 'blockquote':
      return blocks((token as Tokens.Blockquote).tokens, '\n\n');
    case 'list':
      return list(token as Tokens.List);
    case 'table':
      return table(token as Tokens.Table);
    case 'html':
      return stripTags((token as Tokens.HTML).text).trim();
    default:
      return inlineToken(token);
  }
}

function list(token: Tokens.List): string {
  const start = typeof token.start === 'number' ? token.start : 1;
  return token.items
    .map((item, i) => {
      const marker = token.ordered ? `${start + i}. ` : '• ';
      const body = blocks(item.tokens, item.loose ? '\n\n' : '\n');
      // Lines after the first sit under the item's text, so a nested list reads as one.
      return marker + body.split('\n').join(`\n${' '.repeat(marker.length)}`);
    })
    .join(token.loose ? '\n\n' : '\n');
}

function table(token: Tokens.Table): string {
  const row = (cells: Tokens.TableCell[]) => cells.map(cell => inline(cell.tokens)).join('\t');
  return [row(token.header), ...token.rows.map(row)].join('\n');
}
