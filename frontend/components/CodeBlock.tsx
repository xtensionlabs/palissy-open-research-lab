import { highlightLine } from "@/lib/highlight";

export function CodeBlock({ code, label, expanded = false }: { code: string; label: string; expanded?: boolean }) {
  const lines = code.replace(/\n$/, "").split("\n");
  return (
    <pre className={`code${expanded ? " open" : ""}`} tabIndex={0} aria-label={label}>
      <code>
        {lines.map((line, i) => (
          <span className="l" key={i}>
            {highlightLine(line).map((t, j) =>
              t.cls ? (
                <span className={t.cls} key={j}>
                  {t.text}
                </span>
              ) : (
                t.text
              ),
            )}
            {line === "" ? " " : null}
          </span>
        ))}
      </code>
    </pre>
  );
}
