import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, FileCode2, FileText, Loader2, Play, UploadCloud, XCircle } from "lucide-react";
import { startUploadRun, subscribeUploadRun, uploadFiles, type UploadInfo } from "@/api/uploads";
import { cn } from "@/lib/util";

type RunState = "idle" | "uploading" | "running" | "succeeded" | "failed";

export function UploadView() {
  const [featureFile, setFeatureFile] = useState<File | null>(null);
  const [stepsFile, setStepsFile] = useState<File | null>(null);
  const [upload, setUpload] = useState<UploadInfo | null>(null);
  const [state, setState] = useState<RunState>("idle");
  const [lines, setLines] = useState<string[]>([]);
  const unsubRef = useRef<(() => void) | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => () => { unsubRef.current?.(); }, []);
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [lines]);

  const canRun = featureFile && stepsFile && state !== "uploading" && state !== "running";

  async function fire() {
    if (!featureFile || !stepsFile) return;
    setLines([]);
    setUpload(null);
    setState("uploading");
    try {
      const info = await uploadFiles(featureFile, stepsFile);
      setUpload(info);
      setState("running");
      const { run_id } = await startUploadRun(info.id);
      unsubRef.current?.();
      unsubRef.current = subscribeUploadRun(
        run_id,
        (line) => setLines((prev) => [...prev, line]),
        () => {
          setLines((prev) => {
            const last = prev[prev.length - 1] ?? "";
            const exitMatch = /__exit__ rc=(-?\d+)/.exec(last);
            if (exitMatch) {
              setState(exitMatch[1] === "0" ? "succeeded" : "failed");
              return prev.slice(0, -1);
            }
            setState((s) => (s === "running" ? "succeeded" : s));
            return prev;
          });
        },
      );
    } catch (e) {
      setLines([(e as Error).message]);
      setState("failed");
    }
  }

  return (
    <div className="grid h-full grid-cols-[420px_1fr]">
      <aside className="flex min-h-0 flex-col gap-3 border-r border-line p-5">
        <div>
          <div className="text-[11px] uppercase tracking-wider text-fg-mute">Run a custom test bundle</div>
          <div className="mt-1 text-[13px] text-fg-soft">
            Drop a Behave <span className="text-fg">.feature</span> and its
            paired <span className="text-fg">_steps.py</span>. The sandbox
            shells <span className="font-mono text-accent">behave</span> on them
            and streams output below.
          </div>
        </div>

        <Picker
          label="Feature file"
          accept=".feature"
          file={featureFile}
          icon={FileText}
          onPick={setFeatureFile}
        />
        <Picker
          label="Steps Python file"
          accept=".py"
          file={stepsFile}
          icon={FileCode2}
          onPick={setStepsFile}
        />

        <FireButton state={state} disabled={!canRun} onClick={fire} />

        {upload && (
          <div className="mt-2 rounded-md border border-line bg-bg-soft px-3 py-2 font-mono text-[10px] text-fg-mute">
            <div>upload_id: <span className="text-fg-soft">{upload.id}</span></div>
            <div>feature: {upload.feature_bytes} B</div>
            <div>steps: {upload.steps_bytes} B</div>
          </div>
        )}

        <div className="mt-auto rounded-md border border-line/60 bg-bg-soft px-3 py-2 text-[10.5px] leading-relaxed text-fg-mute">
          <div className="mb-1 text-fg-soft">Honest about scope</div>
          Behave validates parse + step resolution + AmbiguousStep + assertions
          inside step defs. LocalStack/Microcks aren't booted yet, so any boto3
          call that goes off-process will fail loudly. That's the point — same
          recurring class of mistakes as 2025, caught at the door.
        </div>
      </aside>

      <section className="flex min-h-0 flex-col">
        <div className="flex items-center justify-between border-b border-line px-5 py-2.5">
          <div className="text-[11px] uppercase tracking-wider text-fg-mute">Behave output</div>
          <span className="font-mono text-[10px] text-fg-mute">{lines.length} lines</span>
        </div>
        <div
          ref={logRef}
          className="flex-1 overflow-auto bg-bg p-5 font-mono text-[11.5px] leading-relaxed"
        >
          {lines.length === 0 ? (
            <div className="text-fg-mute">No output yet. Pick two files, hit Run.</div>
          ) : (
            <AnimatePresence initial={false}>
              {lines.map((l, i) => (
                <motion.div
                  key={`${i}-${l.slice(0, 24)}`}
                  initial={{ opacity: 0, x: 4 }}
                  animate={{ opacity: 1, x: 0 }}
                  className={cn(
                    "whitespace-pre-wrap break-all",
                    classifyLine(l),
                  )}
                >
                  {l}
                </motion.div>
              ))}
            </AnimatePresence>
          )}
        </div>
      </section>
    </div>
  );
}

function Picker({
  label, accept, file, icon: Icon, onPick,
}: {
  label: string;
  accept: string;
  file: File | null;
  icon: typeof FileText;
  onPick: (f: File | null) => void;
}) {
  return (
    <label
      className={cn(
        "group flex cursor-pointer items-center gap-3 rounded-lg border border-dashed px-3 py-3 transition",
        file ? "border-accent/60 bg-accent/5" : "border-line hover:border-fg-mute hover:bg-bg-soft",
      )}
    >
      <Icon size={16} className={file ? "text-accent" : "text-fg-mute group-hover:text-fg-soft"} />
      <div className="min-w-0 flex-1">
        <div className="text-[10px] uppercase tracking-wider text-fg-mute">{label}</div>
        {file ? (
          <div className="truncate font-mono text-[11.5px] text-fg">{file.name}</div>
        ) : (
          <div className="text-[11.5px] text-fg-soft">drop or click to pick ({accept})</div>
        )}
      </div>
      <input
        type="file"
        accept={accept}
        onChange={(e) => onPick(e.target.files?.[0] ?? null)}
        className="hidden"
      />
    </label>
  );
}

function FireButton({
  state, disabled, onClick,
}: {
  state: RunState;
  disabled: boolean;
  onClick: () => void;
}) {
  const tone =
    state === "succeeded" ? "border-ok/60 text-ok bg-ok/10"
    : state === "failed"    ? "border-error/60 text-error bg-error/10"
    : state === "uploading" || state === "running"
                            ? "border-accent/60 text-accent bg-accent/10"
                            : "border-line text-fg hover:border-accent/60 hover:text-accent";
  const label =
    state === "uploading" ? "Uploading…"
    : state === "running"  ? "Running behave…"
    : state === "succeeded" ? "Succeeded"
    : state === "failed"    ? "Failed"
    : "Run in sandbox";
  const Icon =
    state === "uploading" || state === "running" ? Loader2
    : state === "succeeded" ? CheckCircle2
    : state === "failed"    ? XCircle
    : state === "idle" && !disabled ? Play
    : UploadCloud;
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "mt-2 flex items-center justify-center gap-2 rounded-lg border px-3.5 py-2 text-[12px] font-medium transition",
        tone,
        disabled && "opacity-40",
      )}
    >
      <Icon size={14} className={state === "uploading" || state === "running" ? "animate-spin" : ""} />
      <span>{label}</span>
    </button>
  );
}

function classifyLine(l: string): string {
  if (/^\s*Failure|Error|Traceback/.test(l)) return "text-error";
  if (/passed|^\s*✓|OK$/i.test(l)) return "text-ok";
  if (/^\s*Scenario:|Feature:/.test(l)) return "text-accent";
  if (/^\s*Given|When|Then|And/.test(l)) return "text-fg";
  return "text-fg-soft";
}
