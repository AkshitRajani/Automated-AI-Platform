import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight, BookOpen, Boxes, FileCode2, Map as MapIcon, Search, UploadCloud, User,
} from "lucide-react";
import { useReactFlow } from "@xyflow/react";
import { useProfiles, useTopology } from "@/api/topology";
import { useUI, type ViewName } from "@/store/ui";
import { cn } from "@/lib/util";

interface Cmd {
  id: string;
  label: string;
  hint?: string;
  group: "view" | "profile" | "node";
  icon: typeof MapIcon;
  run: () => void;
}

const GROUP_LABEL: Record<Cmd["group"], string> = {
  view: "Views",
  profile: "Profiles",
  node: "Nodes",
};

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const setView = useUI((s) => s.setView);
  const setProfile = useUI((s) => s.setProfile);
  const profile = useUI((s) => s.profile);
  const selectNode = useUI((s) => s.selectNode);

  const profiles = useProfiles();
  const topology = useTopology(profile);
  const rf = useReactFlow();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const isK = e.key.toLowerCase() === "k";
      if (isK && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape" && open) {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (open) {
      setQ("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  const cmds = useMemo<Cmd[]>(() => {
    const out: Cmd[] = [];
    const views: { id: ViewName; label: string; icon: Cmd["icon"] }[] = [
      { id: "arch",   label: "Go to Architecture", icon: BookOpen },
      { id: "map",    label: "Go to Map",          icon: MapIcon },
      { id: "spec",   label: "Go to Spec",         icon: FileCode2 },
      { id: "upload", label: "Go to Upload & run", icon: UploadCloud },
    ];
    for (const v of views) {
      out.push({
        id: `view:${v.id}`,
        label: v.label,
        group: "view",
        icon: v.icon,
        run: () => setView(v.id),
      });
    }
    for (const p of profiles.data?.profiles ?? []) {
      out.push({
        id: `profile:${p}`,
        label: `Switch profile → ${p}`,
        hint: p === profile ? "current" : undefined,
        group: "profile",
        icon: User,
        run: () => setProfile(p),
      });
    }
    for (const n of topology.data?.nodes ?? []) {
      out.push({
        id: `node:${n.id}`,
        label: `Show node → ${n.label}`,
        hint: n.kind,
        group: "node",
        icon: Boxes,
        run: () => {
          setView("map");
          selectNode(n.id);
          requestAnimationFrame(() => {
            try { rf.fitView({ nodes: [{ id: n.id }], duration: 400, padding: 0.5 }); }
            catch { /* not mounted */ }
          });
        },
      });
    }
    return out;
  }, [profiles.data, topology.data, profile, setView, setProfile, selectNode, rf]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return cmds;
    return cmds.filter((c) =>
      c.label.toLowerCase().includes(needle)
      || (c.hint ?? "").toLowerCase().includes(needle),
    );
  }, [cmds, q]);

  useEffect(() => { setActive(0); }, [q]);

  function commit(idx: number) {
    const cmd = filtered[idx];
    if (!cmd) return;
    setOpen(false);
    cmd.run();
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(filtered.length - 1, a + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      commit(active);
    }
  }

  // Group filtered for rendering.
  const grouped = useMemo(() => {
    const m = new Map<Cmd["group"], { cmd: Cmd; gIdx: number }[]>();
    filtered.forEach((cmd, gIdx) => {
      const arr = m.get(cmd.group) ?? [];
      arr.push({ cmd, gIdx });
      m.set(cmd.group, arr);
    });
    return Array.from(m.entries());
  }, [filtered]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          key="palette-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.12 }}
          className="absolute inset-0 z-30 flex items-start justify-center bg-bg/70 pt-[12vh] backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <motion.div
            key="palette"
            initial={{ y: -8, opacity: 0, scale: 0.98 }}
            animate={{ y: 0, opacity: 1, scale: 1 }}
            exit={{ y: -8, opacity: 0, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 380, damping: 30 }}
            className="flex w-[560px] max-w-[92vw] flex-col overflow-hidden rounded-2xl border border-line bg-bg-elev shadow-[0_24px_60px_-20px_rgba(0,0,0,0.7)]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2.5 border-b border-line px-4 py-3">
              <Search size={14} className="text-fg-mute" />
              <input
                ref={inputRef}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Type a command or search…"
                className="flex-1 bg-transparent text-[13px] text-fg placeholder:text-fg-mute focus:outline-none"
              />
              <kbd className="rounded border border-line bg-bg px-1.5 py-0.5 font-mono text-[10px] text-fg-mute">
                esc
              </kbd>
            </div>

            <div className="max-h-[48vh] overflow-auto py-1">
              {filtered.length === 0 ? (
                <div className="px-4 py-6 text-center text-[12px] text-fg-mute">
                  No matches.
                </div>
              ) : (
                grouped.map(([group, items]) => (
                  <div key={group} className="py-1">
                    <div className="px-4 py-1 text-[10px] uppercase tracking-wider text-fg-mute">
                      {GROUP_LABEL[group]}
                    </div>
                    {items.map(({ cmd, gIdx }) => {
                      const Icon = cmd.icon;
                      const isActive = gIdx === active;
                      return (
                        <button
                          key={cmd.id}
                          onMouseEnter={() => setActive(gIdx)}
                          onClick={() => commit(gIdx)}
                          className={cn(
                            "flex w-full items-center gap-2.5 px-4 py-2 text-left text-[12px] transition",
                            isActive ? "bg-accent/10 text-fg" : "text-fg-soft",
                          )}
                        >
                          <Icon size={14} className={isActive ? "text-accent" : "text-fg-mute"} />
                          <span className="min-w-0 flex-1 truncate">{cmd.label}</span>
                          {cmd.hint && (
                            <span className="font-mono text-[10px] text-fg-mute">{cmd.hint}</span>
                          )}
                          {isActive && <ArrowRight size={12} className="text-accent" />}
                        </button>
                      );
                    })}
                  </div>
                ))
              )}
            </div>

            <div className="flex items-center justify-between border-t border-line px-4 py-2 text-[10px] text-fg-mute">
              <div className="flex items-center gap-3">
                <Hint k="↑↓" v="navigate" />
                <Hint k="↵" v="run" />
                <Hint k="esc" v="close" />
              </div>
              <Hint k="⌘K" v="toggle" />
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function Hint({ k, v }: { k: string; v: string }) {
  return (
    <span className="flex items-center gap-1">
      <kbd className="rounded border border-line bg-bg px-1 py-0.5 font-mono">{k}</kbd>
      <span>{v}</span>
    </span>
  );
}
