import { ReactFlowProvider } from "@xyflow/react";
import { Shell } from "@/components/Shell";
import { InspectDrawer } from "@/components/InspectDrawer";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { CommandPalette } from "@/components/CommandPalette";
import { MapView } from "@/views/MapView";
import { SpecView } from "@/views/SpecView";
import { ArchitectureView } from "@/views/ArchitectureView";
import { UploadView } from "@/views/UploadView";
import { Landing } from "@/views/Landing";
import { useUI } from "@/store/ui";

export default function App() {
  const view = useUI((s) => s.view);

  return (
    <ErrorBoundary>
      <ReactFlowProvider>
        {view === null ? (
          <Landing />
        ) : (
          <Shell>
            {view === "arch" && <ArchitectureView />}
            {view === "map" && <MapView />}
            {view === "spec" && <SpecView />}
            {view === "upload" && <UploadView />}
            <InspectDrawer />
            <CommandPalette />
          </Shell>
        )}
      </ReactFlowProvider>
    </ErrorBoundary>
  );
}
