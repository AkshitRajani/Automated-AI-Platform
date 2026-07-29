import { create } from "zustand";

export type ViewName = "arch" | "map" | "spec" | "upload";

interface UIState {
  // null = on the chooser landing; non-null = inside a sandbox showing this tab
  view: ViewName | null;
  setView: (v: ViewName | null) => void;
  profile: string;
  setProfile: (p: string) => void;
  selectedNodeId: string | null;
  selectNode: (id: string | null) => void;
  showConfidence: boolean;
  toggleConfidence: () => void;
  showFidelity: boolean;
  toggleFidelity: () => void;
}

export const useUI = create<UIState>((set) => ({
  view: null,
  setView: (view) => set({ view }),
  profile: "F",
  setProfile: (profile) => set({ profile }),
  selectedNodeId: null,
  selectNode: (selectedNodeId) => set({ selectedNodeId }),
  showConfidence: false,
  toggleConfidence: () => set((s) => ({ showConfidence: !s.showConfidence })),
  showFidelity: true,
  toggleFidelity: () => set((s) => ({ showFidelity: !s.showFidelity })),
}));
