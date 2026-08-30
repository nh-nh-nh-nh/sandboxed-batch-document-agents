import { describe, expect, it } from "vitest";
import {
  MAX_FILES_PER_SUBMISSION,
  MAX_FILE_BYTES,
  validateBatch,
  validateExtension,
  validateSize,
} from "../lib/validate";

function makeFile(name: string, size = 100): File {
  return new File([new Uint8Array(size)], name);
}

describe("validateExtension", () => {
  it.each([".csv", ".tsv", ".xlsx", ".xls", ".xlsm"])(
    "accepts %s",
    (ext) => {
      expect(validateExtension(makeFile(`file${ext}`))).toBeNull();
    },
  );

  it("accepts .CSV case-insensitively", () => {
    expect(validateExtension(makeFile("file.CSV"))).toBeNull();
  });

  it("rejects unsupported extensions", () => {
    const issue = validateExtension(makeFile("file.pdf"));
    expect(issue).not.toBeNull();
    expect(issue?.code).toBe("UNSUPPORTED_EXTENSION");
  });

  it("names the offending file in the error text", () => {
    const issue = validateExtension(makeFile("bad-file.exe"));
    expect(issue?.message).toContain("bad-file.exe");
  });
});

describe("validateSize", () => {
  it("accepts a file at exactly MAX_FILE_BYTES", () => {
    expect(validateSize(makeFile("a.csv", MAX_FILE_BYTES))).toBeNull();
  });

  it("rejects a file at MAX_FILE_BYTES + 1", () => {
    const issue = validateSize(makeFile("a.csv", MAX_FILE_BYTES + 1));
    expect(issue?.code).toBe("FILE_TOO_LARGE");
  });
});

describe("validateBatch", () => {
  it("accepts 1 file", () => {
    expect(validateBatch([makeFile("a.csv")])).toEqual([]);
  });

  it("accepts 100 files", () => {
    const files = Array.from({ length: 100 }, (_, i) =>
      makeFile(`f${i}.csv`),
    );
    expect(validateBatch(files)).toEqual([]);
  });

  it("rejects 0 files", () => {
    const issues = validateBatch([]);
    expect(issues.some((i) => i.code === "NO_FILES")).toBe(true);
  });

  it("rejects 101 files", () => {
    const files = Array.from({ length: 101 }, (_, i) =>
      makeFile(`f${i}.csv`),
    );
    const issues = validateBatch(files);
    expect(issues.some((i) => i.code === "TOO_MANY_FILES")).toBe(true);
  });

  it(`allows up to MAX_FILES_PER_SUBMISSION = ${MAX_FILES_PER_SUBMISSION}`, () => {
    expect(MAX_FILES_PER_SUBMISSION).toBe(100);
  });
});
