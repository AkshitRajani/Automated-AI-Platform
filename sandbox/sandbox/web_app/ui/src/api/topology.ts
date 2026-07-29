import { useQuery } from "@tanstack/react-query";

export type NodeKind =
  | "lambda"
  | "step_function"
  | "s3"
  | "dynamodb"
  | "glue_job"
  | "microcks"
  | "postgres";

export type Confidence = "high" | "medium" | "low";
export type FidelityTier = "L1" | "L2" | "L3";
export type TierKind = "core" | "reference";

export interface TopologyNode {
  id: string;
  kind: NodeKind;
  label: string;
  confidence: Confidence;
  family?: string;
  role?: string;
  runtime?: string;
  invocation_pattern?: string;
  hash_key?: string;
  purpose?: string;
  input?: string;
  output?: string;
  interaction_type?: string;
  consumer?: string;
  integrations?: string[];
  fidelity_tier?: FidelityTier;
  fidelity_source?: string;
  tier_kind?: TierKind;
  source_suite?: string;
}

export interface TopologyEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  flow?: string;
}

export interface Topology {
  profile: string;
  sandbox_id: string;
  tenant: string;
  snapshot_date: string;
  endpoints: Record<string, string>;
  counts: Record<string, number>;
  fidelity_summary?: { L1?: number; L2?: number; L3?: number };
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}

async function fetchJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json();
}

export function useTopology(profile = "F") {
  return useQuery<Topology>({
    queryKey: ["topology", profile],
    queryFn: () => fetchJSON<Topology>(`/api/topology?profile=${profile}`),
  });
}

export function useProfiles() {
  return useQuery<{ profiles: string[] }>({
    queryKey: ["profiles"],
    queryFn: () => fetchJSON("/api/profiles"),
  });
}

export function useHealth() {
  return useQuery<{ ok: boolean; core_dir: string; default_profile: string }>({
    queryKey: ["health"],
    queryFn: () => fetchJSON("/api/health"),
    refetchInterval: 5_000,
  });
}
