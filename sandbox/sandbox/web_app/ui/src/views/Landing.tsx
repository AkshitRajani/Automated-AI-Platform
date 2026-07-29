import { motion } from "framer-motion";
import { ArrowRight, Plus, Server } from "lucide-react";
import { useHealth, useProfiles, useTopology } from "@/api/topology";
import { useUI } from "@/store/ui";
import { cn } from "@/lib/util";

export function Landing() {
  const profiles = useProfiles();
  const setView = useUI((s) => s.setView);
  const setProfile = useUI((s) => s.setProfile);
  const health = useHealth();

  function open(profile: string) {
    setProfile(profile);
    setView("arch");
  }

  return (
    <div className="flex h-full w-full flex-col items-center bg-bg px-8 py-16 text-fg">
      <header className="mb-12 flex w-full max-w-5xl items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-2 w-2 rounded-full bg-accent shadow-[0_0_12px_rgba(45,212,191,0.7)]" />
          <span className="font-mono text-[14px] font-medium tracking-tight">sandbox</span>
        </div>
        <div className="flex items-center gap-1.5 text-[11px]">
          <span className={health.data?.ok ? "text-ok" : "text-error"}>●</span>
          <span className="text-fg-soft">{health.data?.ok ? "backend live" : "backend offline"}</span>
        </div>
      </header>

      <div className="w-full max-w-5xl">
        <h1 className="text-[28px] font-semibold tracking-tight text-fg">
          Choose a sandbox
        </h1>
        <p className="mt-2 text-[13px] text-fg-soft">
          Each sandbox is a local clone of a tenant's AWS shape — same lambdas,
          same DDB, same S3, same external service contracts. Pick one to open
          its architecture and run test bundles against it.
        </p>

        <div className="mt-10 grid grid-cols-2 gap-5">
          {(profiles.data?.profiles ?? []).map((p) => (
            <ExistingCard key={p} profile={p} onOpen={() => open(p)} />
          ))}
          <CreateCard />
        </div>
      </div>
    </div>
  );
}

function ExistingCard({ profile, onOpen }: { profile: string; onOpen: () => void }) {
  const topology = useTopology(profile);
  const counts = topology.data?.counts;
  const tenant = topology.data?.tenant;

  return (
    <motion.button
      onClick={onOpen}
      whileHover={{ y: -2 }}
      transition={{ type: "spring", stiffness: 320, damping: 26 }}
      className={cn(
        "group flex flex-col items-start rounded-2xl border border-line bg-bg-elev p-6 text-left",
        "hover:border-accent/60 hover:shadow-[0_0_0_1px_rgba(45,212,191,0.18)]",
      )}
    >
      <div className="flex w-full items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-accent/10 p-2 text-accent ring-1 ring-accent/30">
            <Server size={18} strokeWidth={1.75} />
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-fg-mute">existing</div>
            <div className="text-[16px] font-semibold">{tenant ?? profile}</div>
          </div>
        </div>
        <ArrowRight size={16} className="text-fg-mute transition group-hover:translate-x-0.5 group-hover:text-accent" />
      </div>

      <div className="mt-5 grid w-full grid-cols-5 gap-1.5">
        <Stat label="λ"     value={counts?.lambdas} />
        <Stat label="step"  value={counts?.step_functions} />
        <Stat label="ddb"   value={counts?.dynamodb_tables} />
        <Stat label="s3"    value={counts?.s3_buckets} />
        <Stat label="rules" value={counts?.business_rules} />
      </div>

      <div className="mt-5 text-[11px] text-fg-soft">
        {topology.data?.snapshot_date ? (
          <>snapshot {topology.data.snapshot_date} · profile <span className="font-mono text-fg-mute">{profile}</span></>
        ) : (
          <>profile <span className="font-mono text-fg-mute">{profile}</span></>
        )}
      </div>
    </motion.button>
  );
}

function CreateCard() {
  return (
    <div
      className="flex flex-col items-start rounded-2xl border border-dashed border-line bg-bg-soft/40 p-6 opacity-70"
      title="Coming later — needs a new tenant profile + spec.yaml"
    >
      <div className="flex w-full items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-bg-soft p-2 text-fg-mute ring-1 ring-line">
            <Plus size={18} strokeWidth={1.75} />
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-fg-mute">create</div>
            <div className="text-[16px] font-semibold text-fg-soft">New sandbox</div>
          </div>
        </div>
      </div>
      <div className="mt-5 text-[11px] text-fg-mute">
        Stand up a sandbox for a new tenant by dropping a <span className="font-mono">spec.yaml</span> + attachments. Available in a later phase — tenant is the only tenant today.
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="rounded-md border border-line bg-bg-soft px-2 py-1.5">
      <div className="text-[9px] uppercase tracking-wider text-fg-mute">{label}</div>
      <div className="mt-0.5 font-mono text-[12px] text-fg">{value ?? "—"}</div>
    </div>
  );
}
