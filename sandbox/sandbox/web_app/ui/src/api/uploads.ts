export interface UploadInfo {
  id: string;
  dir: string;
  feature: string;
  steps: string;
  feature_bytes: number;
  steps_bytes: number;
  uploaded_at: number;
}

export async function uploadFiles(featureFile: File, stepsFile: File): Promise<UploadInfo> {
  const fd = new FormData();
  fd.append("feature_file", featureFile);
  fd.append("steps_file", stepsFile);
  const r = await fetch("/api/uploads", { method: "POST", body: fd });
  if (!r.ok) throw new Error(`upload failed (${r.status})`);
  return r.json();
}

export async function startUploadRun(uploadId: string): Promise<{ run_id: string; state: string }> {
  const r = await fetch(`/api/uploads/${uploadId}/run`, { method: "POST" });
  if (!r.ok) throw new Error(`run start failed (${r.status})`);
  return r.json();
}

export function subscribeUploadRun(runId: string, onLine: (line: string) => void, onDone: () => void): () => void {
  const es = new EventSource(`/api/uploads/runs/${runId}/events`);
  es.onmessage = (ev) => onLine(ev.data);
  es.onerror = () => { es.close(); onDone(); };
  return () => es.close();
}
