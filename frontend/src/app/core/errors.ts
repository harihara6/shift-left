import { HttpErrorResponse } from '@angular/common/http';

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
  if (err.status === 0) {
    return { message: 'The service could not be reached. Try again in a moment.', blockers: [] };
  }
  const detail = err.error?.detail;
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
  return { message: fallback, blockers: [] };
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
