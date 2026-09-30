"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Brand } from "@/components/Brand";
import { Question } from "@/components/Inline";
import { api } from "@/lib/api";
import { usd } from "@/lib/format";
import type { Project } from "@/lib/types";

const MIN = 8;

function when(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function Home() {
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.projects().then(setProjects).catch((e: Error) => { setProjects([]); setError(e.message); });
  }, []);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    if (question.trim().length < MIN) {
      setError("Ask a full question, at least a few words.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const p = await api.create(question.trim());
      router.push(`/p/${p.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't start the project.");
      setBusy(false);
    }
  }

  return (
    <main className="home">
      <Brand />
      <h1>What do you want to find out?</h1>
      <form className="ask" onSubmit={start}>
        <label className="sr" htmlFor="q">Research question</label>
        <textarea
          id="q"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Does codon usage bias correlate with gene expression in E. coli?"
          maxLength={500}
        />
        <div className="row">
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "Starting…" : "Start project"}
          </button>
          <span className="hint">You decide at every step that matters.</span>
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
      </form>

      {projects && projects.length > 0 && (
        <section aria-labelledby="past">
          <h2 id="past" className="sc" style={{ marginBottom: 12 }}>Earlier projects</h2>
          <ul className="past-list">
            {projects.map((p) => (
              <li key={p.id}>
                <Link href={`/p/${p.id}`}>
                  <span className="q"><Question text={p.question} /></span>
                  <span className="cost">{usd(p.cost_usd)}</span>
                  <span className="meta-line">
                    <span className={`status ${p.status}`}><i aria-hidden="true" />{p.status}</span>
                    <span>{when(p.created_at)}</span>
                    {p.pending_gate && <span>waiting for you</span>}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
