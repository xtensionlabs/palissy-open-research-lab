"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { Decision, Project, ProvRecord, Routing } from "./types";

export interface ProjectView {
  project: Project | null;
  records: ProvRecord[];
  decisions: Decision[];
  routing: Routing | null;
  error: string | null;
  notFound: boolean;
  live: boolean;
  refresh: () => Promise<void>;
}

const fetchAll = (id: string) =>
  Promise.all([api.project(id), api.records(id), api.decisions(id)]);

/** Loads a project and keeps it current: server-sent events while it runs, nothing once done. */
export function useProject(id: string): ProjectView {
  const [project, setProject] = useState<Project | null>(null);
  const [records, setRecords] = useState<ProvRecord[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [routing, setRouting] = useState<Routing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [connected, setConnected] = useState(false);
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fail = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.status === 404) setNotFound(true);
    else setError(e instanceof Error ? e.message : "Something went wrong.");
  }, []);

  const apply = useCallback(([p, r, d]: Awaited<ReturnType<typeof fetchAll>>) => {
    setProject(p);
    setRecords(r);
    setDecisions(d);
    setError(null);
  }, []);

  const refresh = useCallback(async () => {
    try {
      apply(await fetchAll(id));
    } catch (e) {
      fail(e);
    }
  }, [id, apply, fail]);

  // Coalesce bursts of events into one refresh.
  const refreshSoon = useCallback(() => {
    if (pending.current) return;
    pending.current = setTimeout(() => {
      pending.current = null;
      void refresh();
    }, 200);
  }, [refresh]);

  // Initial load. State is only set from the promise callbacks, and ignored after unmount.
  useEffect(() => {
    let cancelled = false;
    fetchAll(id)
      .then((all) => !cancelled && apply(all))
      .catch((e) => !cancelled && fail(e));
    api.routing().then((r) => !cancelled && setRouting(r)).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [id, apply, fail]);

  const running = project?.status === "running";
  useEffect(() => {
    if (!running) return;
    const source = new EventSource(api.eventsUrl(id));
    let closed = false;
    source.onopen = () => setConnected(true);
    ["record", "gate", "status"].forEach((name) => source.addEventListener(name, refreshSoon));
    source.addEventListener("end", () => {
      closed = true; // the server closes after "end"; don't let EventSource replay the stream
      source.close();
      setConnected(false);
      void refresh();
    });
    source.onerror = () => {
      if (!closed) setConnected(false); // EventSource retries on its own
    };
    return () => {
      closed = true;
      source.close();
    };
  }, [running, id, refresh, refreshSoon]);

  return {
    project, records, decisions, routing, error, notFound,
    live: running && connected,
    refresh,
  };
}
