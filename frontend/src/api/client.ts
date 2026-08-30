import type {
  Report,
  SubmissionDetail,
  SubmissionSummary,
  Tenant,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `API request failed with status ${status}`);
    this.status = status;
    this.body = body;
  }
}

async function handleJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // ignore — body may not be JSON
    }
    throw new ApiError(res.status, body);
  }
  return (await res.json()) as T;
}

/** GET /api/tenants */
export async function getTenants(signal?: AbortSignal): Promise<Tenant[]> {
  const res = await fetch(`${API_BASE}/api/tenants`, { signal });
  return handleJson<Tenant[]>(res);
}

/** POST /api/tenants/{tenant_id}/submissions */
export async function createSubmission(
  tenantId: string,
  files: File[],
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<SubmissionDetail> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }

  const res = await fetch(
    `${API_BASE}/api/tenants/${tenantId}/submissions`,
    {
      method: "POST",
      headers: {
        "Idempotency-Key": idempotencyKey,
      },
      body: formData,
      signal,
    },
  );
  return handleJson<SubmissionDetail>(res);
}

/** GET /api/tenants/{tenant_id}/submissions/{submission_id} */
export async function getSubmission(
  tenantId: string,
  submissionId: string,
  signal?: AbortSignal,
): Promise<SubmissionDetail> {
  const res = await fetch(
    `${API_BASE}/api/tenants/${tenantId}/submissions/${submissionId}`,
    { signal },
  );
  return handleJson<SubmissionDetail>(res);
}

/** GET /api/tenants/{tenant_id}/submissions?limit=&offset= */
export async function listSubmissions(
  tenantId: string,
  limit = 20,
  offset = 0,
  signal?: AbortSignal,
): Promise<SubmissionSummary[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  const res = await fetch(
    `${API_BASE}/api/tenants/${tenantId}/submissions?${params.toString()}`,
    { signal },
  );
  return handleJson<SubmissionSummary[]>(res);
}

/** GET /api/tenants/{tenant_id}/files/{file_id}/report */
export async function getFileReport(
  tenantId: string,
  fileId: string,
  signal?: AbortSignal,
): Promise<Report> {
  const res = await fetch(
    `${API_BASE}/api/tenants/${tenantId}/files/${fileId}/report`,
    { signal },
  );
  return handleJson<Report>(res);
}
