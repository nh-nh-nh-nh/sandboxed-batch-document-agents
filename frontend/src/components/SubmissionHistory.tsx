import { useEffect, useState } from "react";
import { getSubmission, listSubmissions } from "../api/client";
import type { FileRow, SubmissionDetail, SubmissionSummary } from "../api/types";
import { StatusPill } from "./StatusPill";
import { BatchTable } from "./BatchTable";

interface SubmissionHistoryProps {
  tenantId: string;
  onSelectFile: (file: FileRow) => void;
  /** bump to trigger a refetch, e.g. after a new submission completes */
  refreshToken?: number;
}

const HISTORY_LIMIT = 20;

export function SubmissionHistory({
  tenantId,
  onSelectFile,
  refreshToken,
}: SubmissionHistoryProps) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<SubmissionSummary[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<SubmissionDetail | null>(
    null,
  );

  useEffect(() => {
    const controller = new AbortController();
    listSubmissions(tenantId, HISTORY_LIMIT, 0, controller.signal)
      .then(setItems)
      .catch(() => {});
    return () => controller.abort();
  }, [tenantId, refreshToken]);

  async function toggleExpand(id: string) {
    if (expandedId === id) {
      setExpandedId(null);
      setExpandedDetail(null);
      return;
    }
    setExpandedId(id);
    try {
      const detail = await getSubmission(tenantId, id);
      setExpandedDetail(detail);
    } catch {
      setExpandedDetail(null);
    }
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-sm font-medium text-ink"
      >
        <span aria-hidden="true">{open ? "▾" : "▸"}</span>
        History ({items.length})
      </button>
      {open && (
        <ul className="mt-2 space-y-1">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => toggleExpand(item.id)}
                className="flex w-full items-center justify-between rounded-lg px-1 py-1 text-left text-sm hover:bg-canvas"
              >
                <span className="text-ink-muted">
                  {new Date(item.created_at).toLocaleString()} ·{" "}
                  {item.file_count} files
                </span>
                <StatusPill status={item.status} kind="submission" />
              </button>
              {expandedId === item.id && expandedDetail && (
                <div className="mt-2 pl-2">
                  <BatchTable
                    submission={expandedDetail}
                    onSelectFile={onSelectFile}
                  />
                </div>
              )}
            </li>
          ))}
          {items.length === 0 && (
            <li className="text-xs text-ink-muted">No submissions yet.</li>
          )}
        </ul>
      )}
    </div>
  );
}
