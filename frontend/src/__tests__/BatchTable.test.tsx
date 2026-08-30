import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "./mocks/server";
import { BatchTable } from "../components/BatchTable";
import { ReportDrawer } from "../components/ReportDrawer";
import type { FileRow, SubmissionDetail } from "../api/types";
import { useState } from "react";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const TENANT_ID = "tenant-1";

function makeFile(overrides: Partial<FileRow>): FileRow {
  return {
    id: "file-1",
    submission_id: "sub-1",
    original_filename: "clean_sales.csv",
    size_bytes: 2048,
    status: "SUCCEEDED",
    has_report: true,
    error_category: null,
    error_message: null,
    attempt_count: 1,
    turn_count: 4,
    started_at: "2024-01-01T00:00:00Z",
    finished_at: "2024-01-01T00:00:05Z",
    ...overrides,
  };
}

function makeSubmission(files: FileRow[]): SubmissionDetail {
  return {
    id: "sub-1",
    tenant_id: TENANT_ID,
    status: "PARTIALLY_SUCCEEDED",
    file_count: files.length,
    succeeded_count: files.filter((f) => f.status === "SUCCEEDED").length,
    failed_count: files.filter((f) => f.status === "FAILED").length,
    error_message: null,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    files,
  };
}

describe("BatchTable", () => {
  it("renders one row per file", () => {
    const submission = makeSubmission([
      makeFile({ id: "f1", original_filename: "a.csv" }),
      makeFile({ id: "f2", original_filename: "b.csv" }),
      makeFile({ id: "f3", original_filename: "c.csv" }),
    ]);
    render(<BatchTable submission={submission} onSelectFile={() => {}} />);
    expect(screen.getByText("a.csv")).toBeInTheDocument();
    expect(screen.getByText("b.csv")).toBeInTheDocument();
    expect(screen.getByText("c.csv")).toBeInTheDocument();
  });

  it("shows error_category on a failed row", () => {
    const submission = makeSubmission([
      makeFile({
        id: "f1",
        status: "FAILED",
        error_category: "SANDBOX",
        error_message: "sandbox lost",
        has_report: false,
      }),
    ]);
    render(<BatchTable submission={submission} onSelectFile={() => {}} />);
    const pill = screen.getByText("Failed");
    expect(pill).toHaveAttribute("title", "SANDBOX");
  });

  it("clicking a row opens the drawer, which shows summary and severity-coded findings", async () => {
    server.use(
      http.get(
        `*/api/tenants/${TENANT_ID}/files/f1/report`,
        () =>
          HttpResponse.json({
            summary: "A clean, tidy sales export.",
            findings: [
              { title: "No missing values", detail: "All columns full.", severity: "info" },
              { title: "Outlier revenue row", detail: "Row 42 is 10x median.", severity: "warning" },
            ],
          }),
      ),
    );

    const file = makeFile({ id: "f1" });
    const submission = makeSubmission([file]);

    function Harness() {
      const [selected, setSelected] = useState<FileRow | null>(null);
      return (
        <>
          <BatchTable submission={submission} onSelectFile={setSelected} />
          <ReportDrawer
            tenantId={TENANT_ID}
            file={selected}
            onClose={() => setSelected(null)}
          />
        </>
      );
    }

    render(<Harness />);
    fireEvent.click(screen.getByText("clean_sales.csv"));

    await waitFor(() =>
      expect(
        screen.getByText("A clean, tidy sales export."),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("No missing values")).toBeInTheDocument();
    expect(screen.getByText("Outlier revenue row")).toBeInTheDocument();
  });

  it("shows the error instead of a report for a failed file", async () => {
    const file = makeFile({
      id: "f1",
      status: "FAILED",
      has_report: false,
      error_category: "LLM",
      error_message: "model returned a 400",
    });
    const submission = makeSubmission([file]);

    function Harness() {
      const [selected, setSelected] = useState<FileRow | null>(null);
      return (
        <>
          <BatchTable submission={submission} onSelectFile={setSelected} />
          <ReportDrawer
            tenantId={TENANT_ID}
            file={selected}
            onClose={() => setSelected(null)}
          />
        </>
      );
    }

    render(<Harness />);
    fireEvent.click(screen.getByText("clean_sales.csv"));

    expect(await screen.findByText("model returned a 400")).toBeInTheDocument();
    expect(screen.getByText("LLM")).toBeInTheDocument();
  });
});
