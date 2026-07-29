import { useQuery } from "@tanstack/react-query";

export interface DocItem {
  name: string;
  bytes: number;
  binary?: boolean;
}

export function useDocList() {
  return useQuery<{ docs: DocItem[] }>({
    queryKey: ["docs"],
    queryFn: async () => {
      const r = await fetch("/api/docs");
      if (!r.ok) throw new Error(`${r.status}`);
      return r.json();
    },
  });
}

export function useDoc(name: string | null) {
  return useQuery<string>({
    queryKey: ["doc", name],
    queryFn: async () => {
      const r = await fetch(`/api/docs/${encodeURIComponent(name!)}`);
      if (!r.ok) throw new Error(`${r.status}`);
      return r.text();
    },
    enabled: !!name,
  });
}
