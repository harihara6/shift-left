import { HttpErrorResponse } from '@angular/common/http';

/** Statuses a gateway in front of the API answers with when the API itself didn't. */
const GATEWAY = new Set([502, 503, 504]);

/** A refusal from the API, in the API's own words, plus any unmet criteria it listed. */
export interface Refusal {
  message: string;
  blockers: string[];
}

/**
 * What the API said when it said no. FastAPI answers with `detail` as a string, as a
 * `{message, blockers}` object for a refusal that lists its reasons, or as a list of field
 * errors for a 422. Anything else falls back to `fallback`.
 */
export function refusal(err: unknown, fallback: string): Refusal {
  if (!(err instanceof HttpErrorResponse)) return { message: fallback, blockers: [] };
  const detail = err.error?.detail;
  // No answer at all, or a gateway (the dev server's proxy, nginx) saying the API behind it
  // didn't answer. The API's own 503s carry a detail and are shown in its words below.
  if (err.status === 0 || (GATEWAY.has(err.status) && !detail)) {
    const status = err.status ? ` (HTTP ${err.status})` : '';
    return {
      message:
        `The ShiftLeft API isn't answering${status}. If you run it yourself, check the backend is ` +
        'up: make backend serves it on port 8000, which the dev server forwards /api to.',
      blockers: [],
    };
  }
  if (typeof detail === 'string') return { message: detail, blockers: [] };
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return {
      message: String(detail.message),
      blockers: Array.isArray(detail.blockers) ? detail.blockers : [],
    };
  }
  if (Array.isArray(detail) && detail.length) {
    const fields = detail.map((d: { msg?: string }) => d?.msg).filter(Boolean);
    if (fields.length) return { message: fields.join('; '), blockers: [] };
  }
  // Say what came back, so "could not be loaded" is never the whole story.
  return { message: `${fallback} The API answered HTTP ${err.status}.`, blockers: [] };
}

/** `refusal(...).message`, for callers that only show one line. */
export function errorMessage(err: unknown, fallback: string): string {
  return refusal(err, fallback).message;
}

/**
 * For a write on a project. The API answers an under-privileged write with a 404 rather than a
 * 403 - an unauthorized caller learns nothing about what exists - so the page translates it.
 */
export function writeRefusal(err: unknown, fallback: string): Refusal {
  if (err instanceof HttpErrorResponse && err.status === 404) {
    return {
      message: "Your role on this project doesn't allow that. The API decides, not this page.",
      blockers: [],
    };
  }
  return refusal(err, fallback);
}
