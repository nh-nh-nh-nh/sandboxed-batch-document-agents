#!/usr/bin/env node
// Zero-dependency mock of the backend API (SPEC.md §5) so the SPA has
// something to render against — backend/ doesn't exist yet in this repo.
// Serves two tenants with a mix of succeeded/failed/running files so
// screenshots and recordings show real content, not an empty state.
import { createServer } from "node:http";

const PORT = Number(process.env.MOCK_API_PORT ?? 8000);

const tenants = [
  { id: "tenant-a", slug: "company-a", display_name: "Company A" },
  { id: "tenant-b", slug: "company-b", display_name: "Company B" },
];

function file(overrides) {
  return {
    id: "file-1",
    submission_id: "sub-1",
    original_filename: "clean_sales.csv",
    size_bytes: 2048,
    status: "SUCCEEDED",
    has_report: true,
    error_category: null,
    error_message: null,
    attempt_count: 1,
    turn_count: 4,
    started_at: "2026-08-28T09:00:00Z",
    finished_at: "2026-08-28T09:00:05Z",
    ...overrides,
  };
}

const filesByTenant = {
  "tenant-a": [
    file({ id: "f-a1", submission_id: "sub-a1", original_filename: "q3_expenses.csv" }),
    file({
      id: "f-a2",
      submission_id: "sub-a1",
      original_filename: "vendor_invoices.xlsx",
      status: "FAILED",
      has_report: false,
      error_category: "VALIDATION",
      error_message: "Column 'invoice_total' contains non-numeric values on 3 rows.",
      finished_at: "2026-08-28T09:00:03Z",
    }),
    file({
      id: "f-a3",
      submission_id: "sub-a1",
      original_filename: "payroll_aug.csv",
      status: "RUNNING",
      has_report: false,
      finished_at: null,
      turn_count: 2,
    }),
  ],
  "tenant-b": [
    file({ id: "f-b1", submission_id: "sub-b1", original_filename: "onboarding_docs.csv", size_bytes: 5120 }),
  ],
};

function submissionFor(tenantId) {
  const files = filesByTenant[tenantId];
  const succeeded = files.filter((f) => f.status === "SUCCEEDED").length;
  const failed = files.filter((f) => f.status === "FAILED").length;
  return {
    id: files[0].submission_id,
    tenant_id: tenantId,
    status: failed > 0 ? "PARTIALLY_SUCCEEDED" : "SUCCEEDED",
    file_count: files.length,
    succeeded_count: succeeded,
    failed_count: failed,
    error_message: null,
    created_at: "2026-08-28T09:00:00Z",
    updated_at: "2026-08-28T09:00:05Z",
    files,
  };
}

const reports = {
  "f-a1": {
    summary: "3 anomalies found across 214 line items. No blocking issues.",
    findings: [
      { title: "Duplicate line item", detail: "Row 42 and row 108 share the same invoice_id.", severity: "warning" },
      { title: "Currency mismatch", detail: "Row 77 is denominated in EUR; rest of file is USD.", severity: "critical" },
      { title: "Missing vendor tax ID", detail: "12 rows have a blank vendor_tax_id column.", severity: "info" },
    ],
  },
  "f-b1": {
    summary: "No anomalies found across 48 line items.",
    findings: [],
  },
};

function json(res, status, body) {
  res.writeHead(status, {
    "content-type": "application/json",
    "access-control-allow-origin": "*",
  });
  res.end(JSON.stringify(body));
}

const server = createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const parts = url.pathname.split("/").filter(Boolean);

  if (parts[0] === "api" && parts[1] === "tenants" && parts.length === 2) {
    return json(res, 200, tenants);
  }

  const tenantId = parts[2];
  if (parts[0] === "api" && parts[1] === "tenants" && parts[3] === "submissions" && parts.length === 4) {
    const s = submissionFor(tenantId);
    return json(res, 200, [
      {
        id: s.id,
        tenant_id: s.tenant_id,
        status: s.status,
        file_count: s.file_count,
        succeeded_count: s.succeeded_count,
        failed_count: s.failed_count,
        created_at: s.created_at,
        updated_at: s.updated_at,
      },
    ]);
  }

  if (parts[0] === "api" && parts[1] === "tenants" && parts[3] === "submissions" && parts.length === 5) {
    return json(res, 200, submissionFor(tenantId));
  }

  if (parts[0] === "api" && parts[1] === "tenants" && parts[3] === "files" && parts[5] === "report") {
    const fileId = parts[4];
    const report = reports[fileId];
    if (!report) return json(res, 404, { detail: "not found" });
    return json(res, 200, report);
  }

  json(res, 404, { detail: "not found" });
});

server.listen(PORT, () => {
  console.log(`mock API listening on http://localhost:${PORT}`);
});
