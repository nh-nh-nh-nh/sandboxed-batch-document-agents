import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "./mocks/server";
import { useSubmissionPolling } from "../hooks/useSubmissionPolling";

const TENANT_ID = "tenant-1";
const SUBMISSION_ID = "sub-1";
const URL_PATTERN = `*/api/tenants/${TENANT_ID}/submissions/${SUBMISSION_ID}`;

function submissionPayload(status: string) {
  return {
    id: SUBMISSION_ID,
    tenant_id: TENANT_ID,
    status,
    file_count: 1,
    succeeded_count: 0,
    failed_count: 0,
    error_message: null,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    files: [],
  };
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  vi.useRealTimers();
});
afterAll(() => server.close());

beforeEach(() => {
  vi.useFakeTimers();
});

describe("useSubmissionPolling", () => {
  it("issues zero requests when there is no active submission", async () => {
    let callCount = 0;
    server.use(
      http.get(URL_PATTERN, () => {
        callCount += 1;
        return HttpResponse.json(submissionPayload("RUNNING"));
      }),
    );

    renderHook(() => useSubmissionPolling(null, null));
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(callCount).toBe(0);
  });

  it("polls every 2000ms while RUNNING", async () => {
    let callCount = 0;
    server.use(
      http.get(URL_PATTERN, () => {
        callCount += 1;
        return HttpResponse.json(submissionPayload("RUNNING"));
      }),
    );

    renderHook(() => useSubmissionPolling(TENANT_ID, SUBMISSION_ID));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(callCount).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(callCount).toBe(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(callCount).toBe(3);
  });

  it("stops immediately on a terminal status", async () => {
    let callCount = 0;
    server.use(
      http.get(URL_PATTERN, () => {
        callCount += 1;
        return HttpResponse.json(submissionPayload("SUCCEEDED"));
      }),
    );

    renderHook(() => useSubmissionPolling(TENANT_ID, SUBMISSION_ID));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(callCount).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(callCount).toBe(1);
  });

  it("never issues overlapping requests", async () => {
    let inFlight = 0;
    let maxInFlight = 0;
    server.use(
      http.get(URL_PATTERN, async () => {
        inFlight += 1;
        maxInFlight = Math.max(maxInFlight, inFlight);
        await new Promise((r) => setTimeout(r, 1));
        inFlight -= 1;
        return HttpResponse.json(submissionPayload("RUNNING"));
      }),
    );

    renderHook(() => useSubmissionPolling(TENANT_ID, SUBMISSION_ID));
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(maxInFlight).toBe(1);
  });

  it("backs off to 5s after 60 consecutive polls", async () => {
    let callCount = 0;
    server.use(
      http.get(URL_PATTERN, () => {
        callCount += 1;
        return HttpResponse.json(submissionPayload("RUNNING"));
      }),
    );

    renderHook(() => useSubmissionPolling(TENANT_ID, SUBMISSION_ID));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); }); // poll #1

    // Drive 59 more 2000ms cycles to reach 60 total polls.
    for (let i = 0; i < 59; i++) {
      await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    }
    expect(callCount).toBe(60);

    // After the 60th poll, the next interval should be 5000ms, not 2000ms.
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(callCount).toBe(60);
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(callCount).toBe(61);
  });

  it("backs off to 15s after 5 consecutive network errors", async () => {
    let callCount = 0;
    server.use(
      http.get(URL_PATTERN, () => {
        callCount += 1;
        return HttpResponse.error();
      }),
    );

    renderHook(() => useSubmissionPolling(TENANT_ID, SUBMISSION_ID));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); }); // error #1

    for (let i = 0; i < 3; i++) {
      await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    }
    expect(callCount).toBe(4);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); }); // error #5, now backed off
    expect(callCount).toBe(5);

    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(callCount).toBe(5);
    await act(async () => { await vi.advanceTimersByTimeAsync(13000); });
    expect(callCount).toBe(6);
  });

  it("aborts in-flight requests on unmount", async () => {
    let aborted = false;
    server.use(
      http.get(URL_PATTERN, async ({ request }) => {
        await new Promise((resolve) => {
          const timer = setTimeout(resolve, 5000);
          request.signal.addEventListener("abort", () => {
            aborted = true;
            clearTimeout(timer);
            resolve(undefined);
          });
        });
        return HttpResponse.json(submissionPayload("RUNNING"));
      }),
    );

    const { unmount } = renderHook(() =>
      useSubmissionPolling(TENANT_ID, SUBMISSION_ID),
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(aborted).toBe(true);
  });
});
