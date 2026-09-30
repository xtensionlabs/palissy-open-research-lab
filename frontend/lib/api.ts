import type {
  Costs,
  Decision,
  Health,
  GateAction,
  Notebook,
  Project,
  ProvRecord,
  Routing,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(0, "Can't reach the Palissy server.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  projects: () => request<Project[]>("/projects"),
  project: (id: string) => request<Project>(`/projects/${id}`),
  records: (id: string) => request<ProvRecord[]>(`/projects/${id}/records`),
  decisions: (id: string) => request<Decision[]>(`/projects/${id}/decisions`),
  notebook: (id: string) => request<Notebook>(`/projects/${id}/notebook`),
  costs: () => request<Costs>("/costs"),
  health: () => request<Health>("/health"),
  routing: () => request<Routing>("/routing"),
  strategy: () => request<{ lessons: string[] }>("/strategy"),
  create: (question: string) => request<Project>("/projects", json({ question })),
  decide: (projectId: string, gateId: string, action: GateAction, payload?: string) =>
    request<{ ok: boolean }>(
      `/projects/${projectId}/gates/${gateId}/decision`,
      json({ action, payload: payload ?? null }),
    ),
  eventsUrl: (id: string) => `${API_URL}/projects/${id}/events`,
};
