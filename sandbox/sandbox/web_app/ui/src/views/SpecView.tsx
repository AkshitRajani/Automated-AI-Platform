import { useEffect, useState } from "react";
import Editor from "@monaco-editor/react";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, Hammer, Loader2, Save, XCircle } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { rebuildSandbox, saveSpec, useCoverage, useSpec } from "@/api/spec";
import { useUI } from "@/store/ui";
import { cn } from "@/lib/util";

type Toast = { kind: "ok" | "err"; msg: string } | null;

export function SpecView() {
  const profile = useUI((s) => s.profile);
  const spec = useSpec(profile);
  const coverage = useCoverage(profile);
  const qc = useQueryClient();

  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [toast, setToast] = useState<Toast>(null);

  useEffect(() => {
    if (spec.data && draft === null) setDraft(spec.data);
  }, [spec.data, draft]);

  useEffect(() => { setDraft(null); }, [profile]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(t);
  }, [toast]);

  const dirty = draft !== null && spec.data !== undefined && draft !== spec.data;

  async function onSave() {
    if (draft === null) return;
    setSaving(true);
    try {
      await saveSpec(profile, draft);
      await qc.invalidateQueries({ queryKey: ["spec", profile] });
      setToast({ kind: "ok", msg: "spec saved" });
    } catch (e) {
      setToast({ kind: "err", msg: (e as Error).message });
    } finally {
      setSaving(false);
    }
  }

  async function onRebuild() {
    setRebuilding(true);
    try {
      const r = await rebuildSandbox(profile);
      if (!r.ok) {
        setToast({ kind: "err", msg: r.stderr.split("\n").slice(-2).join(" ").slice(0, 160) || `rc=${r.returncode}` });
      } else {
        setToast({ kind: "ok", msg: "sandbox rebuilt — topology refreshed" });
        await qc.invalidateQueries({ queryKey: ["topology", profile] });
        await qc.invalidateQueries({ queryKey: ["coverage", profile] });
      }
    } catch (e) {
      setToast({ kind: "err", msg: (e as Error).message });
    } finally {
      setRebuilding(false);
    }
  }

  return (
    <div className="grid h-full grid-cols-[1fr_360px]">
      <section className="flex min-h-0 flex-col">
        <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <div className="flex items-center gap-2">
            <div className="text-[11px] uppercase tracking-wider text-fg-mute">spec.yaml</div>
            <span className="font-mono text-[10px] text-fg-mute">profiles/{profile}/spec.yaml</span>
            {dirty && (
              <span className="rounded border border-warn/50 bg-warn/10 px-1.5 py-0.5 font-mono text-[9px] text-warn">
                modified
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              disabled={!dirty || saving}
              onClick={onSave}
              className={cn(
                "flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] transition",
                dirty && !saving
                  ? "border-accent/60 text-accent hover:bg-accent/10"
                  : "border-line text-fg-mute opacity-60",
              )}
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
              <span>{saving ? "Saving" : "Save"}</span>
            </button>
            <button
              disabled={rebuilding}
              onClick={onRebuild}
              className={cn(
                "flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] transition",
                rebuilding
                  ? "border-accent/60 text-accent"
                  : "border-line text-fg hover:border-accent/60 hover:text-accent",
              )}
            >
              {rebuilding ? <Loader2 size={12} className="animate-spin" /> : <Hammer size={12} />}
              <span>{rebuilding ? "Rebuilding" : "Rebuild sandbox"}</span>
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1">
          {spec.isLoading || draft === null ? (
            <div className="flex h-full items-center justify-center text-[12px] text-fg-soft">
              Loading spec…
            </div>
          ) : spec.error ? (
            <div className="flex h-full items-center justify-center text-[12px] text-error">
              {(spec.error as Error).message}
            </div>
          ) : (
            <Editor
              height="100%"
              defaultLanguage="yaml"
              value={draft}
              onChange={(v) => setDraft(v ?? "")}
              theme="vs-dark"
              options={{
                fontFamily: "'JetBrains Mono', 'SF Mono', Menlo, monospace",
                fontSize: 12,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                renderLineHighlight: "gutter",
                tabSize: 2,
                wordWrap: "off",
              }}
            />
          )}
        </div>
      </section>

      <aside className="flex min-h-0 flex-col border-l border-line">
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="text-[11px] uppercase tracking-wider text-fg-mute">Coverage</div>
          <span className="rounded border border-line bg-bg-soft px-1.5 py-0.5 font-mono text-[10px] text-fg-soft">
            {coverage.data?.source === "COVERAGE.md" ? "md" : "derived"}
          </span>
        </div>
        <div className="flex-1 overflow-auto px-3 py-3">
          {coverage.isLoading ? (
            <div className="text-[12px] text-fg-soft">Loading…</div>
          ) : coverage.error ? (
            <div className="text-[12px] text-error">{(coverage.error as Error).message}</div>
          ) : (
            <ul className="space-y-1.5">
              {coverage.data?.rows.map((r) => (
                <li
                  key={r.section}
                  className="rounded-md border border-line bg-bg-soft px-2.5 py-2"
                >
                  <div className="flex items-center justify-between">
                    <span className="truncate text-[12px] text-fg">{r.section}</span>
                    <VerdictPill verdict={r.verdict} />
                  </div>
                  {(r.real || r.stub || r.gap) && (
                    <div className="mt-1 grid grid-cols-3 gap-1 font-mono text-[9.5px]">
                      <Cell tone="text-ok" label="REAL" v={r.real} />
                      <Cell tone="text-warn" label="STUB" v={r.stub} />
                      <Cell tone="text-error" label="GAP" v={r.gap} />
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>

      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ y: 12, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 12, opacity: 0 }}
            className={cn(
              "absolute bottom-4 left-1/2 z-20 flex -translate-x-1/2 items-center gap-2 rounded-lg border px-3 py-2 text-[12px] backdrop-blur",
              toast.kind === "ok"
                ? "border-ok/60 bg-ok/10 text-ok"
                : "border-error/60 bg-error/10 text-error",
            )}
          >
            {toast.kind === "ok" ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
            <span className="font-mono">{toast.msg}</span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function VerdictPill({ verdict }: { verdict: string }) {
  const v = verdict.toLowerCase();
  const tone =
    v.includes("strong") || v.includes("present") || v.includes("shippable")
      ? "border-ok/50 text-ok bg-ok/10"
    : v.includes("weak") || v.includes("missing") || v.includes("partial")
      ? "border-warn/50 text-warn bg-warn/10"
    : "border-line text-fg-mute bg-bg";
  return (
    <span className={cn("ml-2 shrink-0 rounded border px-1.5 py-0.5 text-[9.5px]", tone)}>
      {verdict.length > 26 ? verdict.slice(0, 24) + "…" : verdict}
    </span>
  );
}

function Cell({ tone, label, v }: { tone: string; label: string; v: string }) {
  return (
    <div className="rounded border border-line bg-bg px-1.5 py-1">
      <div className={cn("text-[8.5px] uppercase tracking-wider", tone)}>{label}</div>
      <div className="truncate text-fg-soft">{v || "—"}</div>
    </div>
  );
}
