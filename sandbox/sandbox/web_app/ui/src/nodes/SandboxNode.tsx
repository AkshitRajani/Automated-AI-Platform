import { Handle, Position, type NodeProps } from "@xyflow/react";
import { motion } from "framer-motion";
import {
  Boxes, Database, FileBox, FunctionSquare, GitBranch, PlugZap, Workflow,
} from "lucide-react";
import { cn } from "@/lib/util";
import type { NodeKind, Confidence, FidelityTier, TierKind } from "@/api/topology";
import { useUI } from "@/store/ui";

const KIND_META: Record<NodeKind, { icon: typeof Boxes; tag: string; tone: string }> = {
  lambda:        { icon: FunctionSquare, tag: "λ",     tone: "text-amber-300" },
  step_function: { icon: Workflow,       tag: "STEP",  tone: "text-violet-300" },
  s3:            { icon: FileBox,        tag: "S3",    tone: "text-emerald-300" },
  dynamodb:      { icon: Database,       tag: "DDB",   tone: "text-sky-300" },
  glue_job:      { icon: GitBranch,      tag: "GLUE",  tone: "text-pink-300" },
  microcks:      { icon: PlugZap,        tag: "API",   tone: "text-teal-300" },
  postgres:      { icon: Boxes,          tag: "PG",    tone: "text-blue-300" },
};

const CONFIDENCE_RING: Record<Confidence, string> = {
  high:   "ring-1 ring-line",
  medium: "outline-dashed outline-1 outline-offset-0 outline-line",
  low:    "outline-dashed outline-1 outline-offset-0 outline-warn/50",
};

const CONFIDENCE_TINT: Record<Confidence, string> = {
  high:   "bg-ok/[0.06] ring-ok/40",
  medium: "bg-warn/[0.05] ring-warn/40",
  low:    "bg-error/[0.05] ring-error/40",
};

// Fidelity tier ring (secondary outline). Off → green = matches tenant best;
// down → red = echo / no payload material yet.
const FIDELITY_OUTLINE: Record<FidelityTier, string> = {
  L3: "outline outline-1 outline-offset-1 outline-ok/60",
  L2: "outline outline-1 outline-offset-1 outline-warn/60",
  L1: "outline outline-1 outline-offset-1 outline-error/40",
};

export interface SandboxNodeData {
  kind: NodeKind;
  label: string;
  confidence: Confidence;
  sub?: string;
  fidelity_tier?: FidelityTier;
  tier_kind?: TierKind;
  [k: string]: unknown;
}

export function SandboxNode({ data, selected }: NodeProps) {
  const d = data as unknown as SandboxNodeData;
  const meta = KIND_META[d.kind];
  const Icon = meta.icon;
  const showConfidence = useUI((s) => s.showConfidence);
  const showFidelity = useUI((s) => s.showFidelity);
  const bootDelay = (d.bootDelay as number | undefined) ?? 0;
  // Only lambdas have a meaningful fidelity tier today.
  const fidelityTier = d.kind === "lambda" ? d.fidelity_tier : undefined;
  return (
    <motion.div
      initial={{ opacity: 0, y: 6, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 280, damping: 24, delay: bootDelay }}
      className={cn(
        "group relative w-[200px] rounded-xl bg-bg-elev backdrop-blur",
        "transition-colors duration-300",
        CONFIDENCE_RING[d.confidence],
        showConfidence && "ring-1 " + CONFIDENCE_TINT[d.confidence],
        showFidelity && fidelityTier && FIDELITY_OUTLINE[fidelityTier],
        selected && "ring-2 ring-accent shadow-[0_0_0_4px_rgba(45,212,191,0.12)]",
      )}
    >
      <Handle type="target" position={Position.Left} className="!bg-fg-mute !border-0 !w-1.5 !h-1.5" />
      <div className="flex items-center gap-2.5 px-3 py-2.5">
        <div className={cn("rounded-md bg-bg-soft p-1.5", meta.tone)}>
          <Icon size={14} strokeWidth={1.75} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12px] font-medium leading-tight text-fg">
            {d.label}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-fg-mute">
            <span>{meta.tag}</span>
            {d.sub && <span className="text-fg-mute/70">· {d.sub}</span>}
          </div>
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-fg-mute !border-0 !w-1.5 !h-1.5" />
    </motion.div>
  );
}
