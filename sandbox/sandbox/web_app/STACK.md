# web_app — stack & layout

**Goal:** a beautiful local control surface for the V4 sandbox. Not a dashboard — a living map.

## Layout

```
web_app/
├── backend/              FastAPI bridge to ../core
│   ├── app/
│   │   ├── main.py       routes, CORS, SSE
│   │   ├── topology.py   manifest+spec → nodes/edges
│   │   └── settings.py   resolves CORE_DIR
│   ├── pyproject.toml
│   └── README.md
└── ui/                   Vite + React 19 + TS
    ├── src/
    │   ├── main.tsx
    │   ├── App.tsx
    │   ├── api/          TanStack Query hooks
    │   ├── components/   Shell, Drawer, primitives
    │   ├── views/        MapView, RunView, SpecView
    │   ├── nodes/        React Flow custom nodes (Lambda, S3, DDB, …)
    │   └── lib/          theme, layout (dagre), util
    ├── index.html
    ├── package.json
    └── tailwind.config.ts
```

## Stack (locked)

| Layer        | Pick                              |
|--------------|-----------------------------------|
| Frontend     | Vite + React 19 + TypeScript      |
| Styling      | Tailwind v4, dark default, muted teal accent |
| Components   | shadcn-style primitives, hand-rolled |
| Graph        | React Flow (xyflow v12) + dagre layout |
| Animation    | Framer Motion                     |
| State        | Zustand (UI) + TanStack Query (server) |
| Realtime     | Server-Sent Events                |
| Backend      | FastAPI + uvicorn (port 8765)     |
| Package mgmt | npm (frontend), uv (backend)      |

## Run

```bash
# backend
cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8765

# ui (in another shell)
cd ui && npm install && npm run dev
```

UI lives at `http://localhost:5173`, proxies `/api/*` to `8765`.

## Phasing

- **W1 (now):** Map view rendering F profile from `core/profiles/default/sandbox.manifest.json` + `spec.yaml`.
- **W2:** Inspect drawer (logs/contract/files), Run view, scenario trigger.
- **W3:** Live SSE edge pulses, Spec editor with rebuild.
- **W4:** Boot ballet, confidence overlay toggle, Cmd-K palette.
