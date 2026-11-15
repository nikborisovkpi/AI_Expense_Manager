import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiClientError,
  DEFAULT_API_BASE_URL,
  apiClient,
  buildApiUrl,
  getApiBaseUrl,
} from "@/lib/api-client";

describe("api-client", () => {
  const originalEnv = process.env.NEXT_PUBLIC_API_URL;

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.NEXT_PUBLIC_API_URL;
    } else {
      process.env.NEXT_PUBLIC_API_URL = originalEnv;
    }
    vi.restoreAllMocks();
  });

  describe("buildApiUrl & getApiBaseUrl", () => {
    it("falls back to http://localhost:8000/api/v1 when NEXT_PUBLIC_API_URL is unset", () => {
      delete process.env.NEXT_PUBLIC_API_URL;
      expect(getApiBaseUrl()).toBe(DEFAULT_API_BASE_URL);
      expect(buildApiUrl("/health")).toBe("http://localhost:8000/api/v1/health");
    });

    it("normalizes trailing and leading slashes and serializes query params", () => {
      process.env.NEXT_PUBLIC_API_URL = "http://127.0.0.1:8000/api/v1/";

      const url = buildApiUrl("purchases", {
        currency: "RON",
        limit: 20,
        active: true,
        ignoredUndefined: undefined,
        ignoredNull: null,
        tag: ["food", "weekly"],
      });

      expect(url).toBe(
        "http://127.0.0.1:8000/api/v1/purchases?currency=RON&limit=20&active=true&tag=food&tag=weekly",
      );
    });
  });

  describe("apiClient requests & structured error parsing", () => {
    it("performs a typed GET request and parses JSON payload", async () => {
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      const result = await apiClient.get<{ status: string }>("/health");

      expect(result).toEqual({ status: "ok" });
      expect(fetchSpy).toHaveBeenCalledTimes(1);
      expect(fetchSpy.mock.calls[0]?.[0]).toBe("http://localhost:8000/api/v1/health");
    });

    it("parses structured backend error { error: { code, message, details } } into ApiClientError", async () => {
      const errorPayload = {
        error: {
          code: "VALIDATION_ERROR",
          message: "Purchase amount must be positive",
          details: [{ field: "amount", issue: "must be > 0" }],
        },
      };

      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(JSON.stringify(errorPayload), {
          status: 422,
          statusText: "Unprocessable Entity",
          headers: { "Content-Type": "application/json" },
        }),
      );

      await expect(
        apiClient.post("/purchases", { amount: -5, currency: "RON" }),
      ).rejects.toMatchObject({
        name: "ApiClientError",
        status: 422,
        code: "VALIDATION_ERROR",
        message: "Purchase amount must be positive",
        details: [{ field: "amount", issue: "must be > 0" }],
      });
    });

    it("falls back to HTTP_<status> code when error response is non-JSON", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response("Service Unavailable", {
          status: 503,
          statusText: "Service Unavailable",
          headers: { "Content-Type": "text/plain" },
        }),
      );

      let caught: unknown;
      try {
        await apiClient.get("/receipts");
      } catch (err) {
        caught = err;
      }

      expect(caught).toBeInstanceOf(ApiClientError);
      expect((caught as ApiClientError).status).toBe(503);
      expect((caught as ApiClientError).code).toBe("HTTP_503");
      expect((caught as ApiClientError).message).toBe("Service Unavailable");
    });

    it("returns undefined for 204 No Content responses", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(null, { status: 204 }),
      );

      const res = await apiClient.delete("/purchases/123");
      expect(res).toBeUndefined();
    });
  });
});
