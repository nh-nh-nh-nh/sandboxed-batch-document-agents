import type { FileStatus, SubmissionStatus } from "../api/types";

export interface PillStyle {
  label: string;
  color: "grey" | "clay" | "ok" | "warn" | "err";
  animated?: boolean;
}

export function filePillStyle(status: FileStatus): PillStyle {
  switch (status) {
    case "PENDING":
      return { label: "Queued", color: "grey" };
    case "RUNNING":
      return { label: "Running", color: "clay", animated: true };
    case "SUCCEEDED":
      return { label: "Succeeded", color: "ok" };
    case "FAILED":
      return { label: "Failed", color: "err" };
  }
}

export function submissionPillStyle(status: SubmissionStatus): PillStyle {
  switch (status) {
    case "PENDING":
      return { label: "Queued", color: "grey" };
    case "RUNNING":
      return { label: "Running", color: "clay", animated: true };
    case "SUCCEEDED":
      return { label: "Succeeded", color: "ok" };
    case "PARTIALLY_SUCCEEDED":
      return { label: "Partially succeeded", color: "warn" };
    case "FAILED":
      return { label: "Failed", color: "err" };
  }
}

export function isTerminalSubmissionStatus(status: SubmissionStatus): boolean {
  return (
    status === "SUCCEEDED" ||
    status === "PARTIALLY_SUCCEEDED" ||
    status === "FAILED"
  );
}

export function buildHeaderSummary(
  succeededCount: number,
  failedCount: number,
  runningCount: number,
): string {
  const parts = [`SUCCEEDED ${succeededCount}`, `FAILED ${failedCount}`];
  if (runningCount > 0) parts.push(`${runningCount} running`);
  return parts.join(" · ");
}
