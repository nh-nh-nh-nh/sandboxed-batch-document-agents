import { useEffect, useState } from "react";
import { getFileReport } from "../api/client";
import type { FileRow, Report, Severity } from "../api/types";

interface ReportDrawerProps {
  tenantId: string;
  file: FileRow | null;
  onClose: () => void;
}

const SEVERITY_CLASSES: Record<Severity, string> = {
  info: "border-l-4 border-ink-muted",
  warning: "border-l-4 border-warn",
  critical: "border-l-4 border-err",
};

export function ReportDrawer({ tenantId, file, onClose }: ReportDrawerProps) {
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    setReport(null);
    setLoadError(null);
    if (!file || file.status !== "SUCCEEDED" || !file.has_report) return;

    const controller = new AbortController();
    setLoading(true);
    getFileReport(tenantId, file.id, controller.signal)
      .then((r) => setReport(r))
      .catch((err) => {
        if ((err as { name?: string }).name !== "AbortError") {
          setLoadError("Could not load the report.");
        }
      })
      .finally(() => setLoading(false));

    return () => controller.abort();
  }, [tenantId, file]);

  if (!file) return null;

  return (
    <div
      role="dialog"
      aria-label={`Report for ${file.original_filename}`}
      className="fixed inset-y-0 right-0 z-20 w-full max-w-md overflow-y-auto border-l border-border bg-surface p-6 shadow-subtle"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ink">
          {file.original_filename}
        </h2>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="text-ink-muted hover:text-ink"
        >
          ×
        </button>
      </div>

      {file.status === "FAILED" ? (
        <div className="mt-4">
          <p className="text-xs font-medium uppercase text-err">
            {file.error_category ?? "Failed"}
          </p>
          <p className="mt-2 text-sm text-ink">{file.error_message}</p>
        </div>
      ) : (
        <div className="mt-4">
          {loading && <p className="text-sm text-ink-muted">Loading…</p>}
          {loadError && <p className="text-sm text-err">{loadError}</p>}
          {report && (
            <>
              <p className="text-sm leading-relaxed text-ink">
                {report.summary}
              </p>
              <ul className="mt-4 space-y-2">
                {report.findings.map((finding, i) => (
                  <li
                    key={i}
                    className={`rounded-lg bg-canvas p-3 ${SEVERITY_CLASSES[finding.severity]}`}
                  >
                    <p className="text-sm font-medium text-ink">
                      {finding.title}
                    </p>
                    <p className="mt-1 text-xs text-ink-muted">
                      {finding.detail}
                    </p>
                  </li>
                ))}
              </ul>
              {report.findings.length === 0 && (
                <p className="mt-4 text-xs text-ink-muted">No findings.</p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
