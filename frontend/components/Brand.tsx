import Link from "next/link";

export function Leaf({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" fill="none">
      <path d="M5 19C5 10 10 5 20 4c0 10-5 15-14 15" fill="#026370" />
      <path d="M5 19c3-5 6-8 10-10" stroke="#fcfcf8" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

export function Brand() {
  return (
    <Link href="/" className="brand" aria-label="Palissy, home">
      <Leaf />
      Palissy
    </Link>
  );
}
