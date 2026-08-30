import { describe, expect, it } from "vitest";
import {
  buildHeaderSummary,
  filePillStyle,
  submissionPillStyle,
} from "../lib/status";

describe("filePillStyle", () => {
  it("renders PENDING as Queued", () => {
    expect(filePillStyle("PENDING").label).toBe("Queued");
  });

  it("renders RUNNING as Running with clay/animated", () => {
    const style = filePillStyle("RUNNING");
    expect(style.label).toBe("Running");
    expect(style.color).toBe("clay");
    expect(style.animated).toBe(true);
  });

  it("renders SUCCEEDED as Succeeded/ok", () => {
    const style = filePillStyle("SUCCEEDED");
    expect(style.label).toBe("Succeeded");
    expect(style.color).toBe("ok");
  });

  it("renders FAILED as Failed/err", () => {
    const style = filePillStyle("FAILED");
    expect(style.label).toBe("Failed");
    expect(style.color).toBe("err");
  });
});

describe("submissionPillStyle", () => {
  it("renders PENDING as Queued", () => {
    expect(submissionPillStyle("PENDING").label).toBe("Queued");
  });

  it("renders PARTIALLY_SUCCEEDED as warn", () => {
    expect(submissionPillStyle("PARTIALLY_SUCCEEDED").color).toBe("warn");
  });
});

describe("buildHeaderSummary", () => {
  it("builds the (8, 2, 2 running) summary", () => {
    expect(buildHeaderSummary(8, 2, 2)).toBe(
      "SUCCEEDED 8 · FAILED 2 · 2 running",
    );
  });
});
