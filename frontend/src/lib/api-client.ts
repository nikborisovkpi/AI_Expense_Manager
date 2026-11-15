import type { ApiErrorEnvelope } from "@/types/api";

export const DEFAULT_API_BASE_URL = "http://localhost:8000/api/v1";

export type QueryParamPrimitive = string | number | boolean;
export type QueryParamValue =
  | QueryParamPrimitive
  | readonly QueryParamPrimitive[]
  | null
  | undefined;
export type QueryParams = Record<string, QueryParamValue>;

export interface ApiRequestOptions extends Omit<RequestInit, "body"> {
  params?: QueryParams;
  body?: unknown;
  baseUrl?: string;
}

export class ApiClientError extends Error {
  public readonly status: number;
  public readonly code: string;
  public readonly details?: unknown;

  constructor({
    status,
    code,
    message,
    details,
  }: {
    status: number;
    code: string;
    message: string;
    details?: unknown;
  }) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function getApiBaseUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL?.trim();
  return envUrl && envUrl.length > 0 ? envUrl : DEFAULT_API_BASE_URL;
}

export function buildApiUrl(
  path: string,
  params?: QueryParams,
  baseUrl: string = getApiBaseUrl(),
): string {
  const normalizedBase = baseUrl.replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const url = new URL(`${normalizedBase}${normalizedPath}`);

  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null) {
        continue;
      }
      if (Array.isArray(value)) {
        for (const item of value) {
          url.searchParams.append(key, String(item));
        }
      } else {
        url.searchParams.set(key, String(value));
      }
    }
  }

  return url.toString();
}

function isApiErrorEnvelope(payload: unknown): payload is ApiErrorEnvelope {
  if (typeof payload !== "object" || payload === null || !("error" in payload)) {
    return false;
  }
  const errorObj = (payload as { error: unknown }).error;
  return (
    typeof errorObj === "object" &&
    errorObj !== null &&
    typeof (errorObj as { code?: unknown }).code === "string" &&
    typeof (errorObj as { message?: unknown }).message === "string"
  );
}

async function parseErrorResponse(response: Response): Promise<ApiClientError> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      const payload: unknown = await response.json();
      if (isApiErrorEnvelope(payload)) {
        return new ApiClientError({
          status: response.status,
          code: payload.error.code,
          message: payload.error.message,
          details: payload.error.details,
        });
      }
    } catch {
      // Fall through to generic HTTP error when JSON body cannot be parsed.
    }
  } else {
    try {
      const text = await response.text();
      if (text) {
        const parsed: unknown = JSON.parse(text);
        if (isApiErrorEnvelope(parsed)) {
          return new ApiClientError({
            status: response.status,
            code: parsed.error.code,
            message: parsed.error.message,
            details: parsed.error.details,
          });
        }
      }
    } catch {
      // Ignore non-JSON bodies and return status-based fallback below.
    }
  }

  return new ApiClientError({
    status: response.status,
    code: `HTTP_${response.status}`,
    message: response.statusText || `Request failed with status ${response.status}`,
  });
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const { params, body, baseUrl, headers: customHeaders, ...restInit } = options;
  const url = buildApiUrl(path, params, baseUrl);
  const headers = new Headers(customHeaders);

  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  let requestBody: BodyInit | undefined;
  if (body !== undefined) {
    if (
      body instanceof FormData ||
      body instanceof Blob ||
      body instanceof URLSearchParams ||
      typeof body === "string"
    ) {
      requestBody = body;
    } else {
      if (!headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
      }
      requestBody = JSON.stringify(body);
    }
  }

  const response = await fetch(url, {
    ...restInit,
    headers,
    body: requestBody,
  });

  if (!response.ok) {
    throw await parseErrorResponse(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }

  const text = await response.text();
  return (text ? (JSON.parse(text) as T) : (undefined as T));
}

export const apiClient = {
  get<T>(path: string, options?: Omit<ApiRequestOptions, "method" | "body">) {
    return apiRequest<T>(path, { ...options, method: "GET" });
  },
  post<T>(path: string, body?: unknown, options?: Omit<ApiRequestOptions, "method" | "body">) {
    return apiRequest<T>(path, { ...options, method: "POST", body });
  },
  patch<T>(path: string, body?: unknown, options?: Omit<ApiRequestOptions, "method" | "body">) {
    return apiRequest<T>(path, { ...options, method: "PATCH", body });
  },
  put<T>(path: string, body?: unknown, options?: Omit<ApiRequestOptions, "method" | "body">) {
    return apiRequest<T>(path, { ...options, method: "PUT", body });
  },
  delete<T = void>(path: string, options?: Omit<ApiRequestOptions, "method" | "body">) {
    return apiRequest<T>(path, { ...options, method: "DELETE" });
  },
};
