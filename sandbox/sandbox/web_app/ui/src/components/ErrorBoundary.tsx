import React from "react";
import { AlertTriangle } from "lucide-react";

interface State {
  err: Error | null;
}

export class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  State
> {
  state: State = { err: null };

  static getDerivedStateFromError(err: Error): State {
    return { err };
  }

  componentDidCatch(err: Error, info: React.ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("UI crashed:", err, info.componentStack);
  }

  reset = () => this.setState({ err: null });

  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div className="flex h-full w-full items-center justify-center bg-bg p-8 text-fg">
        <div className="max-w-lg rounded-xl border border-error/40 bg-bg-elev p-5">
          <div className="mb-3 flex items-center gap-2 text-error">
            <AlertTriangle size={16} />
            <span className="text-[12px] uppercase tracking-wider">UI crashed</span>
          </div>
          <pre className="mb-4 max-h-64 overflow-auto rounded-md border border-line bg-bg p-3 font-mono text-[11px] text-fg-soft whitespace-pre-wrap break-words">
            {this.state.err.message}
            {this.state.err.stack ? "\n\n" + this.state.err.stack : ""}
          </pre>
          <button
            onClick={this.reset}
            className="rounded-md border border-accent/60 px-3 py-1 text-[12px] text-accent hover:bg-accent/10"
          >
            Reset
          </button>
        </div>
      </div>
    );
  }
}
