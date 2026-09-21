import { afterEach, describe, expect, it, vi } from "vitest";

import { saveLlmSettings, testLlmSettings } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

function mockJsonResponse(payload: unknown): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => payload
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("LLM settings API", () => {
  it("tests the edited URL and model while reusing the saved key", async () => {
    const fetchMock = mockJsonResponse({
      ok: true,
      endpoint: "https://example.com/v1/chat/completions",
      model: "edited-model"
    });

    await testLlmSettings({
      base_url: "https://example.com/v1",
      model: "edited-model"
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      base_url: "https://example.com/v1",
      model: "edited-model",
      api_key: "",
      clear_api_key: false
    });
  });

  it("sends an explicit clear-key request", async () => {
    const fetchMock = mockJsonResponse({
      saved: true,
      base_url: "https://example.com/v1",
      model: "edited-model",
      api_key_set: false,
      api_key_preview: "",
      defaults: { base_url: "https://api.deepseek.com", model: "deepseek-v4-flash" }
    });

    await saveLlmSettings({
      base_url: "https://example.com/v1",
      model: "edited-model",
      clear_api_key: true
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toMatchObject({
      api_key: "",
      clear_api_key: true
    });
  });
});
