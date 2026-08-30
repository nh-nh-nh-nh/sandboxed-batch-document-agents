import { useMemo, useState } from "react";
import { createSubmission } from "../api/client";
import type { FileRow, Tenant } from "../api/types";
import { useSubmissionPolling } from "../hooks/useSubmissionPolling";
import { DropZone } from "./DropZone";
import { StagedFileList, type StagedFile } from "./StagedFileList";
import { BatchTable } from "./BatchTable";
import { SubmissionHistory } from "./SubmissionHistory";
import { ReportDrawer } from "./ReportDrawer";

interface TenantPanelProps {
  tenant: Tenant;
}

let stagedKeySeq = 0;

export function TenantPanel({ tenant }: TenantPanelProps) {
  const [staged, setStaged] = useState<StagedFile[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [activeSubmissionId, setActiveSubmissionId] = useState<string | null>(
    null,
  );
  const [selectedFile, setSelectedFile] = useState<FileRow | null>(null);
  const [historyRefreshToken, setHistoryRefreshToken] = useState(0);

  // Idempotency key: generated once per submit attempt and retained across
  // retries of that same click so a double-submit can't create two batches.
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);

  const { submission } = useSubmissionPolling(tenant.id, activeSubmissionId);

  const stagedBytes = useMemo(
    () => staged.reduce((sum, s) => sum + s.file.size, 0),
    [staged],
  );

  function handleFilesAdded(files: File[]) {
    setStaged((prev) => [
      ...prev,
      ...files.map((file) => ({ key: String(stagedKeySeq++), file })),
    ]);
  }

  function handleRemove(key: string) {
    setStaged((prev) => prev.filter((s) => s.key !== key));
  }

  function handleClear() {
    setStaged([]);
  }

  async function handleSubmit() {
    if (staged.length === 0 || submitting) return;

    const key = idempotencyKey ?? crypto.randomUUID();
    setIdempotencyKey(key);
    setSubmitting(true);
    setSubmitError(null);

    try {
      const result = await createSubmission(
        tenant.id,
        staged.map((s) => s.file),
        key,
      );
      setActiveSubmissionId(result.id);
      setStaged([]);
      setIdempotencyKey(null);
      setHistoryRefreshToken((t) => t + 1);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Submission failed.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="flex flex-col gap-4 border-border bg-canvas p-4 md:border-r md:last:border-r-0">
      <header className="sticky top-0 z-10 -mx-4 border-b border-border bg-canvas/95 px-4 py-2 backdrop-blur">
        <h2 className="text-base font-semibold text-ink">
          {tenant.display_name}
        </h2>
      </header>

      <DropZone
        stagedCount={staged.length}
        stagedBytes={stagedBytes}
        onFilesAdded={handleFilesAdded}
      />

      <StagedFileList
        files={staged}
        onRemove={handleRemove}
        onClear={handleClear}
      />

      <button
        type="button"
        onClick={handleSubmit}
        disabled={staged.length === 0 || submitting}
        className="rounded-lg bg-clay px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-clay-hover disabled:cursor-not-allowed disabled:opacity-50"
      >
        {submitting
          ? "Uploading…"
          : `Submit${staged.length > 0 ? ` ${staged.length} file${staged.length === 1 ? "" : "s"}` : ""}`}
      </button>
      {submitError && <p className="text-xs text-err">{submitError}</p>}

      <div className="border-t border-border pt-4">
        <h3 className="mb-2 text-sm font-medium text-ink-muted">
          Current batch
        </h3>
        {submission ? (
          <BatchTable submission={submission} onSelectFile={setSelectedFile} />
        ) : (
          <p className="text-sm text-ink-muted">—</p>
        )}
      </div>

      <div className="border-t border-border pt-4">
        <SubmissionHistory
          tenantId={tenant.id}
          onSelectFile={setSelectedFile}
          refreshToken={historyRefreshToken}
        />
      </div>

      {selectedFile && (
        <ReportDrawer
          tenantId={tenant.id}
          file={selectedFile}
          onClose={() => setSelectedFile(null)}
        />
      )}
    </section>
  );
}
