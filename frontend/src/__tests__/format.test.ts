import { describe, expect, it } from "vitest";
import { formatBytes, formatDuration } from "../lib/format";

describe("formatBytes", () => {
  it("renders 0 bytes as 0 B", () => {
    expect(formatBytes(0)).toBe("0 B");
  });

  it("renders 999 bytes as 999 B", () => {
    expect(formatBytes(999)).toBe("999 B");
  });

  it("renders exactly 1024 bytes as 1.0 KB", () => {
    expect(formatBytes(1024)).toBe("1.0 KB");
  });

  it("renders a value in the MB range", () => {
    // 1.2 MiB
    expect(formatBytes(1258291)).toBe("1.2 MB");
  });
});

describe("formatDuration", () => {
  it("renders sub-second durations in ms", () => {
    const start = "2024-01-01T00:00:00.000Z";
    const end = "2024-01-01T00:00:00.500Z";
    expect(formatDuration(start, end)).toBe("500ms");
  });

  it("renders a null finished_at as elapsed-so-far using the provided clock", () => {
    const start = "2024-01-01T00:00:00.000Z";
    const now = () => new Date("2024-01-01T00:00:05.000Z").getTime();
    expect(formatDuration(start, null, now)).toBe("5.0s");
  });

  it("renders minutes", () => {
    const start = "2024-01-01T00:00:00.000Z";
    const end = "2024-01-01T00:02:05.000Z";
    expect(formatDuration(start, end)).toBe("2m 5s");
  });

  it("renders a placeholder when there is no start time", () => {
    expect(formatDuration(null, null)).toBe("—");
  });
});
