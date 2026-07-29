import { useEffect, useMemo } from "react";
import {
  Background, BackgroundVariant, Controls, MiniMap, ReactFlow, type Edge, type Node,
} from "@xyflow/react";
import { useTopology } from "@/api/topology";
import { layoutGraph } from "@/lib/layout";
import { SandboxNode } from "@/nodes/SandboxNode";
import { useUI } from "@/store/ui";

const nodeTypes = { sandbox: SandboxNode };

const MINIMAP_COLORS: Record<string, string> = {
  lambda: "#fcd34d",
  step_function: "#c4b5fd",
  s3: "#86efac",
  dynamodb: "#7dd3fc",
  glue_job: "#f9a8d4",
  microcks: "#5eead4",
  postgres: "#93c5fd",
};

export function MapView() {
  const profile = useUI((s) => s.profile);
  const { data, isLoading, error } = useTopology(profile);
  const selectNode = useUI((s) => s.selectNode);

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [] as Node[], edges: [] as Edge[] };
    const KIND_RANK: Record<string, number> = {
      postgres: 0,
      s3: 1,
      dynamodb: 1,
      microcks: 2,
      glue_job: 3,
      step_function: 3,
      lambda: 4,
    };
    const rawNodes: Node[] = data.nodes.map((n, i) => ({
      id: n.id,
      type: "sandbox",
      position: { x: 0, y: 0 },
      data: {
        kind: n.kind,
        label: n.label,
        confidence: n.confidence,
        sub: n.family ?? n.purpose ?? n.interaction_type,
        bootDelay: (KIND_RANK[n.kind] ?? 5) * 0.18 + (i % 6) * 0.04,
        fidelity_tier: n.fidelity_tier,
        tier_kind: n.tier_kind,
        meta: n,
      },
    }));
    const rawEdges: Edge[] = data.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.label,
      animated: e.flow === "ccfa_main_flow",
      style: { strokeWidth: 1.25 },
      labelStyle: { fontSize: 10, fill: "var(--color-fg-soft)" },
      labelBgStyle: { fill: "var(--color-bg-elev)", fillOpacity: 0.92 },
      labelBgPadding: [6, 3] as [number, number],
      labelBgBorderRadius: 4,
    }));
    return layoutGraph(rawNodes, rawEdges, "LR");
  }, [data]);

  useEffect(() => () => selectNode(null), [selectNode]);

  if (isLoading) return <Centered>Loading topology…</Centered>;
  if (error) return <Centered tone="error">{(error as Error).message}</Centered>;
  if (!data) return null;

  const showFidelity = useUI((s) => s.showFidelity);
  const toggleFidelity = useUI((s) => s.toggleFidelity);
  const fidSummary = data.fidelity_summary ?? {};

  return (
    <div className="relative h-full w-full">
      {/* Fidelity legend (top-right). Shows tier counts; click to toggle outline. */}
      <button
        onClick={toggleFidelity}
        className="absolute right-4 top-4 z-10 flex items-center gap-2 rounded-md border border-line bg-bg-elev px-2.5 py-1.5 text-[10px] uppercase tracking-wider text-fg-soft hover:text-fg"
        title={showFidelity ? "Hide fidelity outlines" : "Show fidelity outlines"}
      >
        <span className="font-mono text-fg-mute">fidelity</span>
        <Legend color="ok" label="L3" count={fidSummary.L3 ?? 0} />
        <Legend color="warn" label="L2" count={fidSummary.L2 ?? 0} />
        <Legend color="error" label="L1" count={fidSummary.L1 ?? 0} />
        <span className="ml-1 text-fg-mute">{showFidelity ? "ON" : "OFF"}</span>
      </button>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, n) => selectNode(n.id)}
        onPaneClick={() => selectNode(null)}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.3}
        maxZoom={1.6}
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} />
        <Controls className="!bg-bg-elev !border-line" showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          className="!bg-bg-elev !border !border-line"
          nodeColor={(n) => MINIMAP_COLORS[(n.data?.kind as string) ?? ""] ?? "#2dd4bf"}
          nodeStrokeColor={() => "transparent"}
          maskColor="rgba(11,13,16,0.7)"
        />
      </ReactFlow>
    </div>
  );
}

function Centered({ children, tone }: { children: React.ReactNode; tone?: "error" }) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className={tone === "error" ? "text-error" : "text-fg-soft"}>{children}</div>
    </div>
  );
}

function Legend({ color, label, count }: { color: "ok" | "warn" | "error"; label: string; count: number }) {
  const dotClass =
    color === "ok" ? "bg-ok" : color === "warn" ? "bg-warn" : "bg-error";
  return (
    <span className="flex items-center gap-1">
      <span className={`h-1.5 w-1.5 rounded-full ${dotClass}`} />
      <span className="font-mono text-fg">{label}</span>
      <span className="font-mono text-fg-mute">{count}</span>
    </span>
  );
}
