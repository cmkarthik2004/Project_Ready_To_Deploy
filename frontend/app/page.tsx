"use client";

import Link from "next/link";
import { Upload } from "lucide-react";
import { Badge, Card, EmptyState, ErrorBox, Loading, PageHeader, Stat, useApi } from "@/components/ui";
import { fmtDate } from "@/lib/api";

type Overview = {
  total_documents: number; processed_documents: number; failed_documents: number; failed_jobs: number; indexed_chunks: number;
  extracted_metrics: number; documents_by_format: Record<string, number>; documents_by_status: Record<string, number>;
  metrics_by_validation_status: Record<string, number>; organisations_detected: string[]; fiscal_years_detected: string[];
  recent_documents: { id: string; filename: string; file_format: string; status: string; uploaded_at: string; organisation: string | null }[];
};

export default function OverviewPage() {
  const { data, error, loading } = useApi<Overview>("/analytics/overview");
  return (
    <>
      <PageHeader title="Overview" subtitle="Live counts from your uploaded documents. Nothing on this page is estimated or sample data."
        actions={<Link href="/upload" className="btn-primary"><Upload className="h-4 w-4" /> Upload documents</Link>} />
      <ErrorBox error={error} />
      {loading && <Loading />}
      {data && data.total_documents === 0 && (
        <EmptyState title="No documents uploaded yet.">No financial data available. Upload a PDF, Word, Excel or CSV financial document to begin analysis.</EmptyState>
      )}
      {data && data.total_documents > 0 && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
            <Stat label="Uploaded files" value={data.total_documents} />
            <Stat label="Processed" value={data.processed_documents} />
            <Stat label="Failed jobs" value={data.failed_jobs} hint={`${data.failed_documents} document(s) currently failed`} />
            <Stat label="Indexed chunks" value={data.indexed_chunks.toLocaleString()} />
            <Stat label="Extracted metrics" value={data.extracted_metrics.toLocaleString()} />
            <Stat label="Formats" value={Object.keys(data.documents_by_format).length} hint={Object.entries(data.documents_by_format).map(([k, v]) => `${k.toUpperCase()} ${v}`).join(" · ")} />
          </div>
          <div className="grid gap-6 lg:grid-cols-3">
            <Card title="Recent uploads" className="lg:col-span-2">
              <div className="overflow-x-auto">
                <table className="table">
                  <thead><tr><th>File</th><th>Format</th><th>Organisation</th><th>Status</th><th>Uploaded</th></tr></thead>
                  <tbody>{data.recent_documents.map((d) => (
                    <tr key={d.id}><td><Link className="text-brand-600 hover:underline" href={`/analysis?doc=${d.id}`}>{d.filename}</Link></td>
                      <td>{d.file_format.toUpperCase()}</td><td>{d.organisation || <span className="italic text-slate-400">Not detected</span>}</td>
                      <td><Badge status={d.status} /></td><td className="whitespace-nowrap">{fmtDate(d.uploaded_at)}</td></tr>))}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card title="Extracted values by validation status">
              {Object.keys(data.metrics_by_validation_status).length === 0 ? <p className="text-sm text-slate-500">No financial metrics extracted yet.</p> : (
                <ul className="space-y-2 text-sm">{Object.entries(data.metrics_by_validation_status).map(([k, v]) => (
                  <li key={k} className="flex items-center justify-between"><Badge status={k} /><span className="num">{v.toLocaleString()}</span></li>))}</ul>
              )}
              <p className="mt-4 text-xs text-slate-500">“Validated” = passed an automated accounting check. Only a person can mark a value “verified”.</p>
              <div className="mt-4 text-sm"><div className="label">Organisations detected</div>
                {data.organisations_detected.length ? data.organisations_detected.join(", ") : <span className="italic text-slate-400">None detected</span>}</div>
              <div className="mt-3 text-sm"><div className="label">Fiscal years detected</div>
                {data.fiscal_years_detected.length ? data.fiscal_years_detected.join(", ") : <span className="italic text-slate-400">None detected</span>}</div>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
