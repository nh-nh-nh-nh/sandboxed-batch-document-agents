import type { FileStatus, SubmissionStatus } from "../api/types";
import { filePillStyle, submissionPillStyle, type PillStyle } from "../lib/status";

const COLOR_CLASSES: Record<PillStyle["color"], string> = {
  grey: "bg-ink-muted/15 text-ink-muted",
  clay: "bg-clay/15 text-clay",
  ok: "bg-ok/15 text-ok",
  warn: "bg-warn/15 text-warn",
  err: "bg-err/15 text-err",
};

interface StatusPillProps {
  status: FileStatus | SubmissionStatus;
  kind?: "file" | "submission";
  errorCategory?: string | null;
}

function isFileStatus(
  status: FileStatus | SubmissionStatus,
): status is FileStatus {
  return (
    status === "PENDING" ||
    status === "RUNNING" ||
    status === "SUCCEEDED" ||
    status === "FAILED"
  );
}

export function StatusPill({ status, kind, errorCategory }: StatusPillProps) {
  const style =
    kind === "submission"
      ? submissionPillStyle(status as SubmissionStatus)
      : isFileStatus(status)
        ? filePillStyle(status)
        : submissionPillStyle(status as SubmissionStatus);

  const title =
    style.label === "Failed" && errorCategory ? errorCategory : undefined;

  return (
    <span
      title={title}
      role="status"
      className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-0.5 text-xs font-medium ${COLOR_CLASSES[style.color]}`}
    >
      {style.animated && (
        <span
          aria-hidden="true"
          className="h-1.5 w-1.5 animate-pulse rounded-full bg-clay"
        />
      )}
      {style.label}
    </span>
  );
}
