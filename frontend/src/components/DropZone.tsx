import { useRef, useState, type DragEvent } from "react";
import {
  MAX_FILES_PER_SUBMISSION,
  MAX_FILE_BYTES,
  validateFile,
  type ValidationIssue,
} from "../lib/validate";
import { formatBytes } from "../lib/format";

interface DropZoneProps {
  stagedCount: number;
  stagedBytes: number;
  onFilesAdded: (files: File[]) => void;
}

export function DropZone({
  stagedCount,
  stagedBytes,
  onFilesAdded,
}: DropZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [rejections, setRejections] = useState<ValidationIssue[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  function acceptFiles(fileList: FileList | null) {
    if (!fileList) return;
    const incoming = Array.from(fileList);
    const accepted: File[] = [];
    const issues: ValidationIssue[] = [];

    if (stagedCount + incoming.length > MAX_FILES_PER_SUBMISSION) {
      issues.push({
        code: "TOO_MANY_FILES",
        message: `Adding these would exceed the ${MAX_FILES_PER_SUBMISSION}-file limit.`,
      });
    }

    for (const file of incoming) {
      const fileIssues = validateFile(file);
      if (fileIssues.length > 0) {
        issues.push(...fileIssues);
      } else {
        accepted.push(file);
      }
    }

    setRejections(issues);
    if (accepted.length > 0) {
      onFilesAdded(accepted);
    }
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragging(false);
    acceptFiles(e.dataTransfer.files);
  }

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-label="Drop spreadsheets or browse"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={`cursor-pointer rounded-lg border border-dashed p-8 text-center transition-colors ${
          isDragging ? "border-clay bg-clay/5" : "border-border bg-surface"
        }`}
      >
        <p className="text-sm text-ink-muted">
          Drop spreadsheets or browse · up to {MAX_FILES_PER_SUBMISSION}
        </p>
        <p className="mt-1 text-xs text-ink-muted">
          .csv .tsv .xlsx .xls .xlsm · up to {formatBytes(MAX_FILE_BYTES)} each
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          data-testid="file-input"
          accept={[".csv", ".tsv", ".xlsx", ".xls", ".xlsm"].join(",")}
          onChange={(e) => {
            acceptFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      <p className="mt-2 text-xs text-ink-muted">
        {stagedCount} staged · {formatBytes(stagedBytes)}
      </p>
      {rejections.length > 0 && (
        <ul className="mt-2 space-y-1" data-testid="rejections">
          {rejections.map((issue, i) => (
            <li key={i} className="text-xs text-err">
              {issue.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
