export function ArchitectureView() {
  return (
    <div className="flex h-full w-full items-center justify-center bg-bg p-6">
      <svg
        viewBox="0 0 1280 770"
        className="h-full w-full max-w-[1280px]"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--color-fg-mute)" />
          </marker>
          <marker id="arrA" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--color-accent)" />
          </marker>
          <marker id="arrW" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--color-warn)" />
          </marker>
        </defs>

        {/* Tool input */}
        <Box x={500} y={20}  w={280} h={60}
             label="Test bundle (tool input)"
             sub=".feature + _steps.py"
             tone="accent" solid />
        <Edge from={[640, 80]} to={[640, 120]} accent />

        {/* SANDBOX container */}
        <Group x={60} y={120} w={1160} h={540} label="Sandbox · mirror of tenant topology" />

        {/* === STUBS column (left) — Microcks + Aurora === */}
        <Box x={130} y={290} w={200} h={44} label="DBM (stub)"        sub="Microcks · contract only" tone="warn" />
        <Box x={130} y={410} w={200} h={44} label="CAL (stub)"        sub="Microcks · contract only" tone="warn" />
        <Box x={130} y={356} w={200} h={32} label="Aurora Postgres"   sub="backs DBM (HLX.app_backbone_manager)" tone="warn" />
        {/* DBM ↓ Aurora link */}
        <path d="M 230 334 L 230 356"
              stroke="var(--color-warn)" strokeWidth={1} fill="none"
              strokeDasharray="3 3" opacity={0.7} />

        <text x={230} y={262} textAnchor="middle" className="fill-warn font-mono" fontSize={10}>
          unimplemented · contracts only
        </text>

        {/* === PIPELINE column (center) — left to right per DATA_FLOW.md sequence === */}
        <Box x={580} y={170} w={240} h={44} label="Step Function · Controller λ" sub="api-submission-workflow"  tone="fg" />
        <Box x={580} y={230} w={240} h={44} label="Acquire slot · Lock-handler λ" sub="put_item → DDB"           tone="fg" />
        <Box x={580} y={290} w={240} h={44} label="Service-backbone-manager λ"   sub="DBM lookup (input meta)"  tone="fg" />
        <Box x={580} y={350} w={240} h={44} label="KLC payload-generator λ"      sub="builds CAL request"        tone="fg" />
        <Box x={580} y={410} w={240} h={44} label="KLC status-handler λ"         sub="polls CAL · update_item"   tone="fg" />
        <Box x={580} y={470} w={240} h={44} label="KLC response-handler λ"       sub="reads result S3"           tone="fg" />
        <Box x={580} y={530} w={240} h={44} label="Postprocessing-status-handler λ" sub=""                       tone="fg" />
        <Box x={580} y={590} w={240} h={44} label="Release-slot λ"               sub="DDB unlock"                tone="fg" />

        {/* Pipeline vertical chain */}
        <VEdge x={700} y1={214} y2={230} />
        <VEdge x={700} y1={274} y2={290} />
        <VEdge x={700} y1={334} y2={350} />
        <VEdge x={700} y1={394} y2={410} />
        <VEdge x={700} y1={454} y2={470} />
        <VEdge x={700} y1={514} y2={530} />
        <VEdge x={700} y1={574} y2={590} />

        {/* === STORAGE column (right) === */}
        <Box x={1020} y={230} w={180} h={44} label="DynamoDB"         sub="api-submission-status-table" tone="fg" />
        <Box x={1020} y={350} w={180} h={44} label="Glue / EMR"       sub="mb4.yml runner"              tone="warn" />
        <Box x={1020} y={410} w={180} h={44} label="S3 (staging)"     sub="parquet output / read"       tone="fg" />

        {/* === REAL EDGES from spec.yaml.data_flows[*].edges === */}
        {/* e2: lock-handler → DDB (put_item) */}
        <Edge from={[820, 252]} to={[1020, 252]} label="put_item" />
        {/* e3: payload-gen → Glue (glue_run) */}
        <Edge from={[820, 372]} to={[1020, 372]} label="glue_run" />
        {/* e4: Glue → S3 staging (put_object) */}
        <path d="M 1110 394 C 1110 402, 1110 402, 1110 410"
              stroke="var(--color-fg-mute)" strokeWidth={1.1} fill="none"
              markerEnd="url(#arr)" opacity={0.75} />
        {/* e5: status-handler → DDB (update_item) — diagonal up */}
        <Edge from={[820, 432]} to={[1020, 264]} label="update_item" />

        {/* response-handler reads from S3 — diagonal down */}
        <Edge from={[820, 492]} to={[1020, 432]} label="read" />

        {/* release-slot → DDB unlock — diagonal up */}
        <Edge from={[820, 612]} to={[1020, 270]} />

        {/* e11: service-backbone-manager → DBM */}
        <Edge from={[580, 312]} to={[330, 312]} warn label="lookup" />
        {/* e8: payload-gen → DBM */}
        <Edge from={[580, 360]} to={[330, 322]} warn />
        {/* e9: payload-gen → CAL (submit) */}
        <Edge from={[580, 380]} to={[330, 422]} warn label="submit" />
        {/* e10: status-handler → CAL (poll) */}
        <Edge from={[580, 432]} to={[330, 432]} warn label="poll" />

        {/* === Sandbox → smoke verdict === */}
        <Edge from={[700, 634]} to={[700, 690]} accent />
        <Box x={480} y={690} w={440} h={56}
             label="Smoke verdict"
             sub="parse · step resolution · AmbiguousStep · boto3 actually leaves the test"
             tone="ok" solid />

        {/* Top-right legend */}
        <text x={1210} y={50}  textAnchor="end" className="fill-fg-soft" fontSize={11} fontWeight={600}>
          Coding Agent invokes Sandbox as a tool
        </text>
        <text x={1210} y={68}  textAnchor="end" className="fill-fg-mute font-mono" fontSize={10}>
          input: feature + steps  ·  output: did it run?
        </text>
      </svg>
    </div>
  );
}

interface BoxProps { x: number; y: number; w: number; h: number; label: string; sub?: string; tone: "fg" | "accent" | "warn" | "ok"; solid?: boolean }

function Box({ x, y, w, h, label, sub, tone, solid }: BoxProps) {
  const stroke =
    tone === "accent" ? "var(--color-accent)"
    : tone === "warn" ? "var(--color-warn)"
    : tone === "ok"   ? "var(--color-ok)"
                      : "var(--color-line)";
  const labelClass =
    tone === "accent" ? "fill-accent"
    : tone === "warn" ? "fill-warn"
    : tone === "ok"   ? "fill-ok"
                      : "fill-fg";
  const compact = h <= 36;
  return (
    <g>
      <rect
        x={x} y={y} width={w} height={h}
        rx={9} ry={9}
        fill={solid ? "var(--color-bg-elev)" : "var(--color-bg-soft)"}
        stroke={stroke}
        strokeWidth={1.4}
        opacity={0.95}
      />
      <text x={x + w / 2}
            y={compact ? y + h / 2 + 4 : y + h / 2 - (sub ? 3 : 0) + 4}
            textAnchor="middle"
            className={labelClass}
            fontSize={compact ? 11 : 12.5}
            fontWeight={600}>
        {label}
      </text>
      {sub && !compact && (
        <text x={x + w / 2} y={y + h / 2 + 14} textAnchor="middle" className="fill-fg-mute font-mono" fontSize={9.5}>
          {sub}
        </text>
      )}
      {sub && compact && (
        <text x={x + w / 2} y={y + h + 11} textAnchor="middle" className="fill-fg-mute font-mono" fontSize={9}>
          {sub}
        </text>
      )}
    </g>
  );
}

function Group({ x, y, w, h, label }: { x: number; y: number; w: number; h: number; label: string }) {
  return (
    <g>
      <rect
        x={x} y={y} width={w} height={h}
        rx={18} ry={18}
        fill="none"
        stroke="var(--color-accent)"
        strokeWidth={1}
        strokeDasharray="6 4"
        opacity={0.55}
      />
      <text x={x + 18} y={y + 18} className="fill-accent" fontSize={11} fontWeight={700} letterSpacing={1.2}>
        {label.toUpperCase()}
      </text>
    </g>
  );
}

function Edge({ from, to, accent, warn, label }: { from: [number, number]; to: [number, number]; accent?: boolean; warn?: boolean; label?: string }) {
  const [x1, y1] = from;
  const [x2, y2] = to;
  const horizontal = Math.abs(y2 - y1) < 6;
  const d = horizontal
    ? `M ${x1} ${y1} L ${x2} ${y2}`
    : `M ${x1} ${y1} C ${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}`;
  const stroke = accent ? "var(--color-accent)" : warn ? "var(--color-warn)" : "var(--color-fg-mute)";
  const marker = accent ? "url(#arrA)" : warn ? "url(#arrW)" : "url(#arr)";
  return (
    <g>
      <path
        d={d}
        stroke={stroke}
        strokeWidth={accent ? 1.5 : 1.1}
        fill="none"
        markerEnd={marker}
        opacity={accent ? 0.95 : 0.78}
      />
      {label && (
        <text
          x={(x1 + x2) / 2}
          y={(y1 + y2) / 2 - 4}
          textAnchor="middle"
          className={warn ? "fill-warn" : "fill-fg-mute"}
          fontSize={9}
          fontFamily="var(--font-mono)"
        >
          {label}
        </text>
      )}
    </g>
  );
}

function VEdge({ x, y1, y2 }: { x: number; y1: number; y2: number }) {
  return (
    <path
      d={`M ${x} ${y1} L ${x} ${y2}`}
      stroke="var(--color-fg-mute)"
      strokeWidth={1.1}
      fill="none"
      markerEnd="url(#arr)"
      opacity={0.85}
    />
  );
}
