"use client";

import { RefreshCw } from "lucide-react";
import { Badge, Card, ErrorBox, Loading, PageHeader, useApi } from "@/components/ui";

type S = Record<string, Record<string, unknown>>;
const Row = ({ k, v }: { k: string; v: unknown }) => (
  <div className="flex justify-between gap-4 border-b border-slate-100 py-1.5 text-sm last:border-0 dark:border-slate-800">
    <span className="text-slate-500">{k}</span><span className="text-right font-medium break-all">{v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v)}</span>
  </div>);
const ok = (b: unknown) => <Badge status={b ? "ok" : "error"} />;

export default function Status() {
  const { data, error, loading, reload } = useApi<S>("/status");
  return (
    <>
      <PageHeader title="AI Model & RAG Status" subtitle="Live checks performed now against each component. No benchmark or accuracy numbers are shown here; see Evaluation for measured results."
        actions={<button className="btn-ghost" onClick={reload}><RefreshCw className="h-4 w-4" /> Refresh</button>} />
      <ErrorBox error={error} />{loading && <Loading />}
      {data && (
        <div className="grid gap-6 md:grid-cols-2">
          <Card title={<span className="flex items-center gap-2">Language model {ok(data.llm.reachable)}</span>}>
            {["provider", "name", "base_url", "model", "model_available", "api_key_configured", "served_models", "error"].map((k) => k in data.llm ? <Row key={k} k={k} v={data.llm[k]} /> : null)}
          </Card>
          <Card title={<span className="flex items-center gap-2">Vector database (Qdrant) {ok(data.vector_store.reachable)}</span>}>
            {Object.entries(data.vector_store).map(([k, v]) => <Row key={k} k={k} v={v} />)}
          </Card>
          <Card title="Embedding model & reranker">
            {Object.entries(data.embedding_model).map(([k, v]) => <Row key={k} k={k} v={v} />)}
            <Row k="reranker" v={data.reranker.name} /><Row k="reranker loaded in API process" v={data.reranker.loaded} />
          </Card>
          <Card title={<span className="flex items-center gap-2">Database {ok(data.database.reachable)}</span>}>
            <Row k="PostgreSQL version" v={data.database.server_version} />
            <div className="label mt-3">Your processing jobs</div>
            {Object.keys(data.processing_jobs).length ? Object.entries(data.processing_jobs).map(([k, v]) => <Row key={k} k={k} v={v} />) : <p className="text-sm text-slate-500">No jobs yet.</p>}
            <div className="label mt-3">Document processing</div>
            <Row k="OCR enabled" v={data.ocr.enabled} /><Row k="Tesseract installed" v={data.ocr.tesseract} /><Row k="PDF table engine" v={data.pdf_table_engine} />
          </Card>
          <Card title={<span className="flex items-center gap-2">GPU / NVIDIA {data.gpu.cuda_available ? <Badge status="ok" /> : <Badge status="not_detected" />}</span>} className="md:col-span-2">
            {Object.entries(data.gpu).map(([k, v]) => <Row key={k} k={k} v={v} />)}
            {!data.gpu.cuda_available && <p className="mt-2 text-sm text-slate-500">No CUDA-capable GPU was detected on this server. Inference runs on CPU. GPU acceleration is only reported when torch.cuda or nvidia-smi actually detects a device.</p>}
            <Row k="platform" v={data.platform} />
          </Card>
        </div>
      )}
    </>
  );
}
