// A deliberately small Python highlighter: enough for short experiment scripts, no dependency.

export type Tok = { text: string; cls?: "k" | "f" | "s" | "n" | "c" };

const KEYWORDS = new Set(
  "and as assert break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield".split(
    " ",
  ),
);

const TOKEN =
  /(#.*$)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(\b\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|(\s+|.)/g;

export function highlightLine(line: string): Tok[] {
  const out: Tok[] = [];
  TOKEN.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN.exec(line)) !== null) {
    const [text, comment, str, num, ident] = m;
    if (comment) out.push({ text, cls: "c" });
    else if (str) out.push({ text, cls: "s" });
    else if (num) out.push({ text, cls: "n" });
    else if (ident) {
      const next = line.slice(TOKEN.lastIndex).trimStart()[0];
      if (KEYWORDS.has(ident)) out.push({ text, cls: "k" });
      else if (next === "(") out.push({ text, cls: "f" });
      else out.push({ text });
    } else out.push({ text });
  }
  return out;
}
