import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "./mocks/server";
import { TenantPanel } from "../components/TenantPanel";
import type { Tenant } from "../api/types";

const TENANT: Tenant = {
  id: "tenant-1",
  slug: "company-a",
  display_name: "Company A",
};

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function stageAFile() {
  const input = screen.getByTestId("file-input") as HTMLInputElement;
  const file = new File(["a,b\n1,2"], "clean.csv", { type: "text/csv" });
  fireEvent.change(input, { target: { files: [file] } });
}

describe("Submit button", () => {
  it("is disabled with 0 staged files", () => {
    server.use(
      http.get(`*/api/tenants/${TENANT.id}/submissions`, () =>
        HttpResponse.json([]),
      ),
    );
    render(<TenantPanel tenant={TENANT} />);
    expect(screen.getByRole("button", { name: /submit/i })).toBeDisabled();
  });

  it("is disabled while a submit is in flight, and issues exactly one POST on a double click", async () => {
    let postCount = 0;
    const receivedKeys: (string | null)[] = [];

    server.use(
      http.get(`*/api/tenants/${TENANT.id}/submissions`, () =>
        HttpResponse.json([]),
      ),
      http.post(`*/api/tenants/${TENANT.id}/submissions`, async ({ request }) => {
        postCount += 1;
        receivedKeys.push(request.headers.get("Idempotency-Key"));
        await new Promise((r) => setTimeout(r, 20));
        return HttpResponse.json(
          {
            id: "sub-1",
            tenant_id: TENANT.id,
            status: "PENDING",
            file_count: 1,
            succeeded_count: 0,
            failed_count: 0,
            error_message: null,
            created_at: "2024-01-01T00:00:00Z",
            updated_at: "2024-01-01T00:00:00Z",
            files: [],
          },
          { status: 202 },
        );
      }),
      http.get(`*/api/tenants/${TENANT.id}/submissions/sub-1`, () =>
        HttpResponse.json({
          id: "sub-1",
          tenant_id: TENANT.id,
          status: "PENDING",
          file_count: 1,
          succeeded_count: 0,
          failed_count: 0,
          error_message: null,
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
          files: [],
        }),
      ),
    );

    render(<TenantPanel tenant={TENANT} />);
    stageAFile();

    const button = await screen.findByRole("button", { name: /submit 1 file/i });
    expect(button).not.toBeDisabled();

    // Double click in quick succession — the second click should be a no-op
    // because the button disables itself once the first click starts.
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(postCount).toBe(1));
    expect(receivedKeys).toHaveLength(1);
    expect(receivedKeys[0]).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
  });

  it("reuses the same Idempotency-Key across a retry of the same click", async () => {
    let attempt = 0;
    const receivedKeys: (string | null)[] = [];

    server.use(
      http.get(`*/api/tenants/${TENANT.id}/submissions`, () =>
        HttpResponse.json([]),
      ),
      http.post(`*/api/tenants/${TENANT.id}/submissions`, async ({ request }) => {
        attempt += 1;
        receivedKeys.push(request.headers.get("Idempotency-Key"));
        if (attempt === 1) {
          return HttpResponse.error();
        }
        return HttpResponse.json(
          {
            id: "sub-1",
            tenant_id: TENANT.id,
            status: "PENDING",
            file_count: 1,
            succeeded_count: 0,
            failed_count: 0,
            error_message: null,
            created_at: "2024-01-01T00:00:00Z",
            updated_at: "2024-01-01T00:00:00Z",
            files: [],
          },
          { status: 202 },
        );
      }),
      http.get(`*/api/tenants/${TENANT.id}/submissions/sub-1`, () =>
        HttpResponse.json({
          id: "sub-1",
          tenant_id: TENANT.id,
          status: "PENDING",
          file_count: 1,
          succeeded_count: 0,
          failed_count: 0,
          error_message: null,
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
          files: [],
        }),
      ),
    );

    render(<TenantPanel tenant={TENANT} />);
    stageAFile();

    const button = await screen.findByRole("button", { name: /submit 1 file/i });
    fireEvent.click(button);

    await waitFor(() => expect(attempt).toBe(1));
    expect(await screen.findByText(/failed/i)).toBeInTheDocument();

    // Files are still staged after a failed attempt — retry the same click.
    const retryButton = screen.getByRole("button", { name: /submit 1 file/i });
    fireEvent.click(retryButton);

    await waitFor(() => expect(attempt).toBe(2));
    expect(receivedKeys[0]).toBe(receivedKeys[1]);
  });
});
