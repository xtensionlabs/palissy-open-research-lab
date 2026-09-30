"use client";

import type { Claim } from "@/lib/provenance";

/** A sentence or footnote a reader can click to see where it came from. */
export function ClaimText({
  claim,
  active,
  onSelect,
  children,
}: {
  claim: Claim | null;
  active: string | null;
  onSelect: (c: Claim) => void;
  children: React.ReactNode;
}) {
  if (!claim) return <>{children}</>;
  return (
    <button
      type="button"
      className="claim"
      aria-pressed={active === claim.key}
      title="Show where this came from"
      onClick={() => onSelect(claim)}
    >
      {children}
    </button>
  );
}

export function Footnote({
  claim,
  n,
  active,
  onSelect,
}: {
  claim: Claim | null;
  n: number;
  active: string | null;
  onSelect: (c: Claim) => void;
}) {
  if (!claim) return <sup>{n}</sup>;
  return (
    <button
      type="button"
      className="fn"
      aria-pressed={active === claim.key}
      aria-label={`Source ${n}: ${claim.text}`}
      onClick={() => onSelect(claim)}
    >
      {n}
    </button>
  );
}
