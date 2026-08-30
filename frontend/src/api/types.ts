export type SubmissionStatus =
  | "PENDING"
  | "RUNNING"
  | "SUCCEEDED"
  | "PARTIALLY_SUCCEEDED"
  | "FAILED";

export type FileStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";

export type ErrorCategory =
  | "VALIDATION"
  | "SANDBOX"
  | "LLM"
  | "TOOL"
  | "TIMEOUT"
  | "INTERNAL";

export interface Tenant {
  id: string;
  slug: string;
  display_name: string;
}

export interface FileRow {
  id: string;
  submission_id: string;
  original_filename: string;
  size_bytes: number;
  status: FileStatus;
  has_report: boolean;
  error_category: ErrorCategory | null;
  error_message: string | null;
  attempt_count: number;
  turn_count: number;
  started_at: string | null;
  finished_at: string | null;
}

export interface SubmissionDetail {
  id: string;
  tenant_id: string;
  status: SubmissionStatus;
  file_count: number;
  succeeded_count: number;
  failed_count: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  files: FileRow[];
}

export interface SubmissionSummary {
  id: string;
  tenant_id: string;
  status: SubmissionStatus;
  file_count: number;
  succeeded_count: number;
  failed_count: number;
  created_at: string;
  updated_at: string;
}

export type Severity = "info" | "warning" | "critical";

export interface Finding {
  title: string;
  detail: string;
  severity: Severity;
}

export interface Report {
  summary: string;
  findings: Finding[];
}
