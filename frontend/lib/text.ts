// Small pure text helpers. Kept free of React so they can be tested directly.

// A full stop after these does not end a sentence: "E. coli", "et al.", "e.g.", "Fig. 2".
const ABBREVIATIONS = new Set([
  "e.g", "i.e", "et al", "vs", "cf", "fig", "figs", "eq", "ca", "approx", "sp", "spp", "subsp",
  "var", "dr", "no", "vol", "ref", "refs",
]);

function endsAbbreviation(before: string): boolean {
  // a single initial such as the "E" in "E. coli" or "S. cerevisiae"
  if (/(^|[\s*_("'])[A-Za-z]$/.test(before)) return true;
  const word = before.match(/([A-Za-z.]+(?: al)?)$/)?.[1]?.toLowerCase() ?? "";
  return ABBREVIATIONS.has(word.replace(/^\./, ""));
}

/** First sentence of a block of text, not fooled by abbreviations like "E. coli" or "et al.". */
export function firstSentence(text: string): string {
  const clean = text.replace(/\s+/g, " ").trim();
  const boundary = /[.!?]+(?=\s|$)/g;
  let m: RegExpExecArray | null;
  while ((m = boundary.exec(clean)) !== null) {
    const end = m.index + m[0].length;
    if (end >= clean.length) break;
    if (m[0] === "." && endsAbbreviation(clean.slice(0, m.index))) continue;
    return clean.slice(0, end).replace(/\*\*/g, "");
  }
  return clean.replace(/\*\*/g, "");
}
