import { formatBytes } from "../lib/format";

export interface StagedFile {
  key: string; // stable per-add id — duplicate filenames are allowed
  file: File;
}

interface StagedFileListProps {
  files: StagedFile[];
  onRemove: (key: string) => void;
  onClear: () => void;
}

export function StagedFileList({
  files,
  onRemove,
  onClear,
}: StagedFileListProps) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-ink">
          Staged ({files.length})
        </h3>
        {files.length > 0 && (
          <button
            type="button"
            onClick={onClear}
            className="text-xs text-ink-muted hover:text-ink"
          >
            Clear
          </button>
        )}
      </div>
      <ul className="mt-2 divide-y divide-border">
        {files.map(({ key, file }) => (
          <li
            key={key}
            className="flex items-center justify-between py-1.5 text-sm"
          >
            <span className="truncate">{file.name}</span>
            <span className="ml-2 flex items-center gap-3 text-ink-muted">
              <span className="text-xs">{formatBytes(file.size)}</span>
              <button
                type="button"
                aria-label={`Remove ${file.name}`}
                onClick={() => onRemove(key)}
                className="hover:text-err"
              >
                ×
              </button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
