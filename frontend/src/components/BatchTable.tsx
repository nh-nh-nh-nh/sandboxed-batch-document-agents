import type { FileRow, SubmissionDetail } from "../api/types";
import { formatBytes, formatDuration } from "../lib/format";
import { buildHeaderSummary } from "../lib/status";
import { StatusPill } from "./StatusPill";

interface BatchTableProps {
  submission: SubmissionDetail;
  onSelectFile: (file: FileRow) => void;
}

export function BatchTable({ submission, onSelectFile }: BatchTableProps) {
  const running = submission.files.filter((f) => f.status === "RUNNING").length;
  const summary = buildHeaderSummary(
    submission.succeeded_count,
    submission.failed_count,
    running,
  );

  return (
    <div>
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
          {summary}
        </p>
        <StatusPill status={submission.status} kind="submission" />
      </div>
      <table className="mt-2 w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-ink-muted">
            <th className="py-1.5 font-medium">Filename</th>
            <th className="py-1.5 font-medium">Size</th>
            <th className="py-1.5 font-medium">Status</th>
            <th className="py-1.5 font-medium">Duration</th>
            <th className="py-1.5 font-medium">Turns</th>
          </tr>
        </thead>
        <tbody>
          {submission.files.map((file) => (
            <tr
              key={file.id}
              role="row"
              tabIndex={0}
              onClick={() => onSelectFile(file)}
              onKeyDown={(e) => {
                if (e.key === "Enter") onSelectFile(file);
              }}
              className="cursor-pointer border-b border-border last:border-0 hover:bg-canvas"
            >
              <td className="py-1.5 pr-2">{file.original_filename}</td>
              <td className="py-1.5 pr-2 text-ink-muted">
                {formatBytes(file.size_bytes)}
              </td>
              <td className="py-1.5 pr-2">
                <StatusPill
                  status={file.status}
                  kind="file"
                  errorCategory={file.error_category}
                />
              </td>
              <td className="py-1.5 pr-2 text-ink-muted">
                {formatDuration(file.started_at, file.finished_at)}
              </td>
              <td className="py-1.5 text-ink-muted">{file.turn_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
