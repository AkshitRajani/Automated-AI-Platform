import { motion } from "framer-motion";
import { Activity, ArrowLeft, Map as MapIcon, FileCode2, BookOpen, UploadCloud } from "lucide-react";
import { useHealth, useTopology } from "@/api/topology";
import { useUI, type ViewName } from "@/store/ui";
import { cn } from "@/lib/util";

const NAV: { id: ViewName; label: string; icon: typeof MapIcon }[] = [
  { id: "arch",   label: "Architecture", icon: BookOpen },
  { id: "map",    label: "Map",          icon: MapIcon },
  { id: "spec",   label: "Spec",         icon: FileCode2 },
  { id: "upload", label: "Upload & run", icon: UploadCloud },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const view = useUI((s) => s.view);
  const setView = useUI((s) => s.setView);
  const profile = useUI((s) => s.profile);
  const showConfidence = useUI((s) => s.showConfidence);
  const toggleConfidence = useUI((s) => s.toggleConfidence);
  const health = useHealth();
  const topology = useTopology(profile);

  const ok = health.data?.ok;
  const counts = topology.data?.counts;

  return (
    <div className="flex h-full w-full flex-col bg-bg text-fg">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-line px-4">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setView(null)}
            title="Back to chooser"
            className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-[11px] text-fg-soft hover:border-fg-mute hover:text-fg"
          >
            <ArrowLeft size={12} />
            <span>chooser</span>
          </button>
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-accent shadow-[0_0_12px_rgba(45,212,191,0.7)]" />
            <span className="font-mono text-[13px] font-medium tracking-tight">
              {topology.data?.tenant ?? "sandbox"} · {profile}
            </span>
          </div>
          {topology.data && (
            <span className="font-mono text-[10px] text-fg-mute">
              {topology.data.sandbox_id.slice(0, 12)}…
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {counts && (
            <div className="flex items-center gap-1.5 text-[11px] text-fg-soft">
              <Stat label="λ" value={counts.lambdas} />
              <Stat label="step" value={counts.step_functions} />
              <Stat label="ddb" value={counts.dynamodb_tables} />
              <Stat label="s3" value={counts.s3_buckets} />
              <Stat label="rules" value={counts.business_rules} />
            </div>
          )}
          <button
            onClick={toggleConfidence}
            className={cn(
              "rounded-md border px-2 py-1 text-[11px] transition",
              showConfidence
                ? "border-accent/60 bg-accent/10 text-accent"
                : "border-line text-fg-soft hover:text-fg",
            )}
          >
            confidence
          </button>
          <div className="flex items-center gap-1.5 text-[11px]">
            <Activity size={12} className={ok ? "text-ok" : "text-error"} />
            <span className="text-fg-soft">{ok ? "live" : "offline"}</span>
          </div>
          <kbd className="hidden rounded border border-line bg-bg-soft px-1.5 py-0.5 font-mono text-[10px] text-fg-mute md:inline-block">
            ⌘K
          </kbd>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <nav className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-line py-3">
          {NAV.map(({ id, label, icon: Icon }) => {
            const active = view === id;
            return (
              <button
                key={id}
                onClick={() => setView(id)}
                title={label}
                className={cn(
                  "group relative flex h-10 w-10 items-center justify-center rounded-lg transition",
                  active ? "text-accent" : "text-fg-mute hover:text-fg",
                )}
              >
                {active && (
                  <motion.div
                    layoutId="nav-active"
                    className="absolute inset-0 rounded-lg bg-accent/10 ring-1 ring-accent/40"
                    transition={{ type: "spring", stiffness: 400, damping: 30 }}
                  />
                )}
                <Icon size={18} strokeWidth={1.75} className="relative z-10" />
              </button>
            );
          })}
        </nav>

        <main className="relative min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <span className="rounded border border-line bg-bg-soft px-1.5 py-0.5 font-mono text-[10px]">
      <span className="text-fg-mute">{label}</span>{" "}
      <span className="text-fg">{value}</span>
    </span>
  );
}
