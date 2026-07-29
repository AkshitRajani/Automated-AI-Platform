import { useQuery } from "@tanstack/react-query";

export interface CoverageRow {
  section: string;
  real: string;
  stub: string;
  gap: string;
  verdict: string;
}

export interface CoverageResponse {
  profile: string;
  source: "COVERAGE.md" | "derived";
  rows: CoverageRow[];
}

export function useSpec(profile: string) {
  return useQuery<string>({
    queryKey: ["spec", profile],
    queryFn: async () => {
      const r = await fetch(`/api/spec?profile=${profile}`);
      if (!r.ok) throw new Error(`${r.status}`);
      return r.text();
    },
  });
}

export function useCoverage(profile: string) {
  return useQuery<CoverageResponse>({
    queryKey: ["coverage", profile],
    queryFn: async () => {
      const r = await fetch(`/api/coverage?profile=${profile}`);
      if (!r.ok) throw new Error(`${r.status}`);
      return r.json();
    },
  });
}

export async function saveSpec(profile: string, text: string) {
  const r = await fetch("/api/spec", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile, text }),
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(body || `${r.status}`);
  }
  return r.json() as Promise<{ ok: true; bytes: number }>;
}

export async function rebuildSandbox(profile: string) {
  const r = await fetch("/api/rebuild", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile }),
  });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json() as Promise<{
    ok: boolean;
    returncode: number;
    stdout: string;
    stderr: string;
  }>;
}
