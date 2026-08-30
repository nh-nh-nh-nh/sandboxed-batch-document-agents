import { useEffect, useRef, useState } from "react";
import { getSubmission } from "../api/client";
import type { SubmissionDetail } from "../api/types";
import { isTerminalSubmissionStatus } from "../lib/status";

const NORMAL_INTERVAL_MS = 2000;
const LONG_BATCH_INTERVAL_MS = 5000;
const ERROR_BACKOFF_INTERVAL_MS = 15000;
const LONG_BATCH_POLL_THRESHOLD = 60;
const ERROR_BACKOFF_THRESHOLD = 5;

export interface UseSubmissionPollingResult {
  submission: SubmissionDetail | null;
  error: Error | null;
}

/**
 * Polls `GET /submissions/{id}` per §11.5:
 * - every 2000ms while PENDING/RUNNING
 * - stops immediately on a terminal status
 * - backs off to 5s after 60 consecutive polls, 15s after 5 consecutive
 *   network errors
 * - AbortController on unmount/change; never overlaps requests
 * - zero requests when there is no active submission
 */
export function useSubmissionPolling(
  tenantId: string | null,
  submissionId: string | null,
): UseSubmissionPollingResult {
  const [submission, setSubmission] = useState<SubmissionDetail | null>(null);
  const [error, setError] = useState<Error | null>(null);

  // Mutable, don't-cause-a-rerender bookkeeping.
  const pollCountRef = useRef(0);
  const errorCountRef = useRef(0);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);

  useEffect(() => {
    setSubmission(null);
    setError(null);
    pollCountRef.current = 0;
    errorCountRef.current = 0;
    inFlightRef.current = false;

    if (!tenantId || !submissionId) {
      return () => {};
    }

    let cancelled = false;

    const scheduleNext = (delayMs: number) => {
      if (cancelled) return;
      timeoutRef.current = setTimeout(poll, delayMs);
    };

    async function poll() {
      if (cancelled || inFlightRef.current) return;
      inFlightRef.current = true;
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const result = await getSubmission(
          tenantId!,
          submissionId!,
          controller.signal,
        );
        if (cancelled) return;

        pollCountRef.current += 1;
        errorCountRef.current = 0;
        setSubmission(result);
        setError(null);

        if (isTerminalSubmissionStatus(result.status)) {
          inFlightRef.current = false;
          return; // stop immediately, no further scheduling
        }

        const delay =
          pollCountRef.current >= LONG_BATCH_POLL_THRESHOLD
            ? LONG_BATCH_INTERVAL_MS
            : NORMAL_INTERVAL_MS;
        inFlightRef.current = false;
        scheduleNext(delay);
      } catch (err) {
        if (cancelled) return;
        if ((err as { name?: string }).name === "AbortError") {
          inFlightRef.current = false;
          return;
        }
        errorCountRef.current += 1;
        setError(err as Error);

        const delay =
          errorCountRef.current >= ERROR_BACKOFF_THRESHOLD
            ? ERROR_BACKOFF_INTERVAL_MS
            : NORMAL_INTERVAL_MS;
        inFlightRef.current = false;
        scheduleNext(delay);
      }
    }

    poll();

    return () => {
      cancelled = true;
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
    };
  }, [tenantId, submissionId]);

  return { submission, error };
}
