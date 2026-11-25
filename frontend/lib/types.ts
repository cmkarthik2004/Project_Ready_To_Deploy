export type MetaField = { value: unknown; status: "detected" | "not_detected" | "uncertain" | "user_corrected"; method: string; confidence: number;
  evidence?: { location?: Record<string, unknown>; snippet?: string } | null; candidates?: string[]; previous_value?: unknown };

export type Doc = {
  id: string; filename: string; file_format: string; file_size: number; status: string; error_message: string | null;
  uploaded_at: string; processed_at: string | null; organisation: string | null; reporting_period: string | null;
  fiscal_year: string | null; category: string | null; currency: string | null; unit: string | null;
  page_count: number | null; sheet_names: string[] | null; row_count: number | null; chunk_count: number; metric_count: number;
  table_count: number; warnings: string[]; sha256: string;
  metadata?: Record<string, MetaField>; validation_checks?: Check[]; jobs?: Job[]; statements?: Statement[]; ocr_pages?: number[] | null;
};

export type Job = { id: string; status: string; stage: string | null; attempts: number; error: string | null;
  log: Record<string, unknown>[]; created_at: string; started_at: string | null; finished_at: string | null };
export type Check = { check: string; description: string; period: string | null; lhs: string; rhs: string; difference: string; result: string; basis?: string | null };
export type Statement = { id: string; statement_type: string; basis: string | null; title: string; unit: string | null; currency: string | null; periods: string[]; location_text: string };

export type Metric = {
  id: string; document_id: string; filename: string | null; metric_key: string; metric_name: string; raw_label: string; raw_value: string;
  value: string; unit: string | null; normalized_value: string | null; currency: string | null; period_label: string | null;
  period_end: string | null; period_sort: number | null; statement_type: string | null; basis: string | null; extraction_method: string;
  confidence: number; validation_status: string; validation_notes: { check: string; result: string; detail: string }[];
  is_duplicate: boolean; location: Record<string, unknown>; location_text: string | null; snippet: string | null;
};

export type Ratio = { calc_key: string; name: string; formula: string; result: string | null; result_unit: string; status: string;
  period_label: string | null; inputs: { key: string; value: string; metric_id: string | null; period_label: string | null; source: string | null; validation_status: string }[];
  warnings: string[]; missing: string[]; document_id: string | null; filename: string | null; organisation: string | null; basis: string | null; unit: string | null };

export type Citation = { sid: string; kind: string; document_id?: string; filename?: string; organisation?: string; location_text?: string; snippet: string };
export type ChatMsg = { id: string; role: "user" | "assistant"; content: string; status: string | null; citations: Citation[];
  evidence: (Citation & { text: string; score?: number })[]; verification: Record<string, unknown>; calculations: Ratio[];
  model: string | null; latency_ms: number | null; created_at: string };
