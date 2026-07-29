import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTopology } from "@/api/topology";
import { useUI } from "@/store/ui";

export function InspectDrawer() {
  const selectedNodeId = useUI((s) => s.selectedNodeId);
  const selectNode = useUI((s) => s.selectNode);
  const profile = useUI((s) => s.profile);
  const { data } = useTopology(profile);
  const node = data?.nodes.find((n) => n.id === selectedNodeId);

  const contractName = node?.kind === "microcks" ? node.label : null;
  const contract = useQuery({
    queryKey: ["contract", contractName, profile],
    queryFn: async () => {
      const r = await fetch(`/api/contract?name=${encodeURIComponent(contractName!)}&profile=${profile}`);
      if (!r.ok) throw new Error(`${r.status}`);
      return r.json();
    },
    enabled: !!contractName,
  });

  return (
    <AnimatePresence>
      {node && (
        <motion.aside
          key={node.id}
          initial={{ x: 360, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 360, opacity: 0 }}
          transition={{ type: "spring", stiffness: 360, damping: 32 }}
          className="absolute right-0 top-0 z-10 flex h-full w-[360px] flex-col border-l border-line bg-bg-elev/95 backdrop-blur"
        >
          <header className="flex items-center justify-between border-b border-line px-4 py-3">
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-wider text-fg-mute">
                {node.kind.replace("_", " ")}
              </div>
              <div className="truncate text-[13px] font-medium">{node.label}</div>
            </div>
            <button
              onClick={() => selectNode(null)}
              className="rounded-md p-1 text-fg-mute hover:bg-bg-soft hover:text-fg"
            >
              <X size={16} />
            </button>
          </header>

          <div className="flex-1 overflow-auto px-4 py-3">
            {node.kind === "lambda" && node.fidelity_tier && (
              <Section title="Fidelity">
                <KV label="tier" value={node.fidelity_tier} />
                {node.tier_kind && <KV label="kind" value={node.tier_kind} />}
                {node.source_suite && <KV label="source suite" value={node.source_suite} />}
                {node.fidelity_source && (
                  <KV label="source" value={node.fidelity_source} mono />
                )}
              </Section>
            )}

            <Section title="Overview">
              <KV label="confidence" value={node.confidence} />
              {node.family && <KV label="family" value={node.family} />}
              {node.role && <KV label="role" value={node.role} />}
              {node.runtime && <KV label="runtime" value={node.runtime} />}
              {node.invocation_pattern && (
                <KV label="invocation" value={node.invocation_pattern} />
              )}
              {node.hash_key && <KV label="hash_key" value={node.hash_key} />}
              {node.purpose && <KV label="purpose" value={node.purpose} />}
              {node.input && <KV label="input" value={node.input} mono />}
              {node.output && <KV label="output" value={node.output} mono />}
              {node.interaction_type && (
                <KV label="interaction" value={node.interaction_type} />
              )}
              {node.consumer && <KV label="consumer" value={node.consumer} />}
            </Section>

            {node.integrations && node.integrations.length > 0 && (
              <Section title="Integrations">
                <ul className="space-y-1 font-mono text-[11px] text-fg-soft">
                  {node.integrations.map((i) => (
                    <li key={i} className="truncate">{i}</li>
                  ))}
                </ul>
              </Section>
            )}

            <Section title="Contract">
              {!contractName ? (
                <div className="rounded-md border border-line bg-bg p-3 font-mono text-[11px] text-fg-mute">
                  No contract bound to this node kind.
                </div>
              ) : contract.isLoading ? (
                <div className="rounded-md border border-line bg-bg p-3 font-mono text-[11px] text-fg-mute">
                  Loading contract…
                </div>
              ) : contract.error ? (
                <div className="rounded-md border border-line bg-bg p-3 font-mono text-[11px] text-error">
                  {(contract.error as Error).message}
                </div>
              ) : (
                <pre className="overflow-auto rounded-md border border-line bg-bg p-3 font-mono text-[11px] leading-relaxed text-fg-soft whitespace-pre-wrap break-words">
                  {formatContract(contract.data)}
                </pre>
              )}
            </Section>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5">
      <div className="mb-2 text-[10px] uppercase tracking-wider text-fg-mute">{title}</div>
      {children}
    </section>
  );
}

function KV({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="mb-1.5 grid grid-cols-[88px_1fr] items-start gap-2 text-[12px]">
      <div className="text-fg-mute">{label}</div>
      <div className={mono ? "break-all font-mono text-[11px]" : ""}>{value}</div>
    </div>
  );
}

function formatContract(c: unknown): string {
  if (!c || typeof c !== "object") return "";
  const obj = c as Record<string, unknown>;
  const lines: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v === null || v === undefined) continue;
    if (Array.isArray(v)) {
      lines.push(`${k}:`);
      for (const item of v) {
        if (typeof item === "object") {
          lines.push(`  - ${JSON.stringify(item)}`);
        } else {
          lines.push(`  - ${String(item)}`);
        }
      }
    } else if (typeof v === "object") {
      lines.push(`${k}:`);
      for (const [k2, v2] of Object.entries(v as Record<string, unknown>)) {
        lines.push(`  ${k2}: ${typeof v2 === "object" ? JSON.stringify(v2) : String(v2)}`);
      }
    } else {
      lines.push(`${k}: ${String(v)}`);
    }
  }
  return lines.join("\n");
}
