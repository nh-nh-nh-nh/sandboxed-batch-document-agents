export const MAX_FILES_PER_SUBMISSION = 100;
export const MAX_FILE_BYTES = 1048576; // 1 MiB — SPEC.md §5.2

const ALLOWED_EXTENSIONS = [".csv", ".tsv", ".xlsx", ".xls", ".xlsm"];

export type ValidationCode =
  | "UNSUPPORTED_EXTENSION"
  | "FILE_TOO_LARGE"
  | "NO_FILES"
  | "TOO_MANY_FILES";

export interface ValidationIssue {
  code: ValidationCode;
  message: string;
}

export function validateExtension(file: File): ValidationIssue | null {
  const lower = file.name.toLowerCase();
  if (ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext))) return null;
  return {
    code: "UNSUPPORTED_EXTENSION",
    message: `${file.name} has an unsupported extension.`,
  };
}

export function validateSize(file: File): ValidationIssue | null {
  if (file.size <= MAX_FILE_BYTES) return null;
  return {
    code: "FILE_TOO_LARGE",
    message: `${file.name} is larger than the ${MAX_FILE_BYTES}-byte limit.`,
  };
}

export function validateFile(file: File): ValidationIssue[] {
  return [validateExtension(file), validateSize(file)].filter(
    (issue): issue is ValidationIssue => issue !== null,
  );
}

export function validateBatch(files: File[]): ValidationIssue[] {
  const issues: ValidationIssue[] = [];

  if (files.length === 0) {
    issues.push({ code: "NO_FILES", message: "Add at least one file." });
  }
  if (files.length > MAX_FILES_PER_SUBMISSION) {
    issues.push({
      code: "TOO_MANY_FILES",
      message: `A submission is limited to ${MAX_FILES_PER_SUBMISSION} files.`,
    });
  }

  for (const file of files) {
    issues.push(...validateFile(file));
  }

  return issues;
}
