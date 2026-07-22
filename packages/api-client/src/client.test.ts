import { describe, expect, it, vi } from "vitest";
import { createApi, decodeJwtExpMs, isPremiumRequired, ApiError } from "./index";
import type {
  FetchResponseLike,
  MediaTokenStore,
  RequestInitLike,
  SessionRecord,
  SessionStore,
  UploadPort,
} from "./index";

// --- test doubles -----------------------------------------------------------

function jsonResponse(status: number, body: unknown, statusText = ""): FetchResponseLike {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: async () => body,
  };
}

/** In-memory SessionStore that records every write for assertions. */
function memSessionStore(initial: SessionRecord | null = null) {
  let rec = initial;
  const writes: SessionRecord[] = [];
  const store: SessionStore = {
    read: () => rec,
    write: (r) => {
      rec = r;
      writes.push(r);
    },
    clear: () => {
      rec = null;
    },
  };
  return { store, writes, current: () => rec };
}

function memMediaStore(initial: { token: string; expEpochMs: number } | null = null) {
  let rec = initial;
  const store: MediaTokenStore = {
    read: () => rec,
    write: (token, expEpochMs) => {
      rec = { token, expEpochMs };
    },
    clear: () => {
      rec = null;
    },
  };
  return { store, current: () => rec };
}

const noopUpload: UploadPort<never> = {
  contentType: () => "application/octet-stream",
  put: async () => {},
};

interface HarnessOpts {
  session?: SessionRecord | null;
  media?: { mode: "header" } | { mode: "media-token"; initial?: { token: string; expEpochMs: number } | null };
  isTestnet?: boolean;
  now?: () => number;
  fetchImpl: (url: string, init: RequestInitLike) => Promise<FetchResponseLike> | FetchResponseLike;
}

function harness(opts: HarnessOpts) {
  const sess = memSessionStore(opts.session ?? null);
  const onSessionExpired = vi.fn();
  const fetchSpy = vi.fn(async (url: string, init: RequestInitLike) => opts.fetchImpl(url, init));
  const mediaCfg =
    !opts.media || opts.media.mode === "header"
      ? ({ mode: "header" } as const)
      : ({ mode: "media-token" as const, store: memMediaStore(opts.media.initial ?? null).store });
  const media = mediaCfg;
  const client = createApi<never>({
    apiUrl: "https://api.test",
    fetch: fetchSpy,
    store: sess.store,
    media,
    upload: noopUpload,
    isTestnet: opts.isTestnet ?? false,
    onSessionExpired,
    now: opts.now,
  });
  return { client, fetchSpy, onSessionExpired, sess };
}

function jwtWithExp(expSeconds: number): string {
  const b64url = (obj: unknown) =>
    Buffer.from(JSON.stringify(obj)).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${b64url({ alg: "HS256" })}.${b64url({ exp: expSeconds })}.sig`;
}

// --- request() ---------------------------------------------------------------

describe("request()", () => {
  it("sends Content-Type + Authorization and returns parsed JSON", async () => {
    const { client, fetchSpy } = harness({
      session: { token: "tok-abc", expEpochMs: null, remembered: false },
      fetchImpl: () => jsonResponse(200, [{ id: "f1" }]),
    });
    const out = await client.api.myFamilies();
    expect(out).toEqual([{ id: "f1" }]);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("https://api.test/families");
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      Authorization: "Bearer tok-abc",
    });
  });

  it("omits Authorization when there is no session", async () => {
    const { client, fetchSpy } = harness({
      fetchImpl: () => jsonResponse(200, { access_token: "x" }),
    });
    await client.api.login("a@b.co", "pw");
    const [, init] = fetchSpy.mock.calls[0];
    expect(init.headers).not.toHaveProperty("Authorization");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ email: "a@b.co", password: "pw", remember_me: false }));
  });

  it("parses a structured premium_required (402) error", async () => {
    const { client } = harness({
      session: { token: "t", expEpochMs: null, remembered: false },
      fetchImpl: () =>
        jsonResponse(402, {
          detail: { code: "premium_required", capability: "video_upload", message: "Upgrade to add video" },
        }),
    });
    const err = await client.api.getPremiumStatus("fam1").then(
      () => null,
      (e) => e
    );
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(402);
    expect(err.message).toBe("Upgrade to add video");
    expect(err.code).toBe("premium_required");
    expect(err.capability).toBe("video_upload");
    expect(isPremiumRequired(err)).toBe(true);
  });

  it("parses a structured session_expired (401) and calls onSessionExpired", async () => {
    const { client, onSessionExpired } = harness({
      session: { token: "t", expEpochMs: null, remembered: false },
      fetchImpl: () => jsonResponse(401, { detail: { code: "session_expired", message: "Session expired" } }),
    });
    const err = await client.api.familyFeed("fam1").then(
      () => null,
      (e) => e
    );
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(401);
    expect(err.code).toBe("session_expired");
    expect(onSessionExpired).toHaveBeenCalledTimes(1);
  });

  it("does NOT redirect on a 401 to an auth-flow path", async () => {
    const { client, onSessionExpired } = harness({
      session: { token: "t", expEpochMs: null, remembered: false },
      fetchImpl: () => jsonResponse(401, { detail: "bad creds" }),
    });
    await client.api.login("a@b.co", "pw").catch(() => {});
    expect(onSessionExpired).not.toHaveBeenCalled();
  });

  it("suppresses the 401 redirect on testnet", async () => {
    const { client, onSessionExpired } = harness({
      session: { token: "t", expEpochMs: null, remembered: false },
      isTestnet: true,
      fetchImpl: () => jsonResponse(401, { detail: { code: "session_expired" } }),
    });
    await client.api.familyFeed("fam1").catch(() => {});
    expect(onSessionExpired).not.toHaveBeenCalled();
  });

  it("returns undefined for a 204 without touching the body", async () => {
    const jsonSpy = vi.fn(async () => ({}));
    const { client } = harness({
      session: { token: "t", expEpochMs: null, remembered: false },
      fetchImpl: () => ({ ok: true, status: 204, statusText: "", json: jsonSpy }),
    });
    const out = await client.api.deleteComment("c1");
    expect(out).toBeUndefined();
    expect(jsonSpy).not.toHaveBeenCalled();
  });
});

// --- silent session refresh --------------------------------------------------

describe("ensureSessionFresh()", () => {
  it("dedups concurrent calls into a single /auth/refresh and preserves remember-ness", async () => {
    const NOW = 1_000_000_000_000;
    // Remembered session inside the 24h remember-refresh window (1h left).
    const startExp = NOW + 60 * 60 * 1000;
    let resolveRefresh: (r: FetchResponseLike) => void = () => {};
    const refreshDeferred = new Promise<FetchResponseLike>((res) => {
      resolveRefresh = res;
    });
    const { client, fetchSpy, sess } = harness({
      session: { token: "old", expEpochMs: startExp, remembered: true },
      now: () => NOW,
      fetchImpl: (url) => {
        if (url.endsWith("/auth/refresh")) return refreshDeferred;
        return jsonResponse(200, {});
      },
    });

    // Fire several concurrent triggers synchronously.
    client.ensureSessionFresh();
    client.ensureSessionFresh();
    client.ensureSessionFresh();

    const refreshCalls = fetchSpy.mock.calls.filter(([u]) => u.endsWith("/auth/refresh"));
    expect(refreshCalls).toHaveLength(1);

    resolveRefresh(jsonResponse(200, { access_token: "new", expires_in_seconds: 1800 }));
    await refreshDeferred;
    // Drain ALL pending microtasks (the awaited response.json() hop plus the
    // writeRecord that follows it) deterministically via a macrotask flush;
    // ensureSessionFresh is fire-and-forget (void), so we can't await it directly.
    await new Promise((r) => setTimeout(r, 0));

    const rec = sess.current();
    expect(rec?.token).toBe("new");
    expect(rec?.remembered).toBe(true); // remember-ness preserved on refresh
  });

  it("is a no-op when the token has comfortable life left", async () => {
    const NOW = 1_000_000_000_000;
    const { client, fetchSpy } = harness({
      session: { token: "fresh", expEpochMs: NOW + 20 * 60 * 1000, remembered: false }, // 20m > 10m window
      now: () => NOW,
      fetchImpl: () => jsonResponse(200, {}),
    });
    client.ensureSessionFresh();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

// --- media token -------------------------------------------------------------

describe("ensureMediaToken() (media-token mode)", () => {
  it("mints once when nothing is cached and builds a ?token= media URL", async () => {
    const NOW = 1_000_000_000_000;
    const { client, fetchSpy } = harness({
      session: { token: "sess", expEpochMs: NOW + 60 * 60 * 1000, remembered: false },
      media: { mode: "media-token", initial: null },
      now: () => NOW,
      fetchImpl: (url) => {
        if (url.endsWith("/auth/media-token"))
          return jsonResponse(200, { media_token: "mtok", expires_in_seconds: 3600 });
        return jsonResponse(200, {});
      },
    });
    await client.ensureMediaToken();
    await client.ensureMediaToken();
    const mints = fetchSpy.mock.calls.filter(([u]) => u.endsWith("/auth/media-token"));
    expect(mints).toHaveLength(1);
    expect(client.mediaUrl("media123")).toBe("https://api.test/media/media123?token=mtok");
  });

  it("is a no-op in header mode and yields a bare media URL", async () => {
    const { client, fetchSpy } = harness({
      session: { token: "sess", expEpochMs: null, remembered: false },
      media: { mode: "header" },
      fetchImpl: () => jsonResponse(200, {}),
    });
    await client.ensureMediaToken();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(client.mediaUrl("m1")).toBe("https://api.test/media/m1");
  });
});

// --- base64url JWT decode (atob replacement) ---------------------------------

describe("decodeJwtExpMs()", () => {
  it("decodes exp from a base64url JWT payload without atob", () => {
    expect(decodeJwtExpMs(jwtWithExp(1_700_000_000))).toBe(1_700_000_000_000);
  });
  it("returns null for a malformed token", () => {
    expect(decodeJwtExpMs("not-a-jwt")).toBeNull();
  });
});

// --- browser-shaped two-store adapter ---------------------------------------

/** A minimal Web Storage stand-in. */
function fakeStorage() {
  const m = new Map<string, string>();
  return {
    getItem: (k: string) => (m.has(k) ? m.get(k)! : null),
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
    _map: m,
  };
}

describe("browser two-store adapter (reproduces web behavior)", () => {
  const TOKEN_KEY = "futureroots_token";
  const TOKEN_EXP_KEY = "futureroots_token_exp";

  function browserHarness() {
    const local = fakeStorage();
    const session = fakeStorage();
    const store: SessionStore = {
      read() {
        const s = session.getItem(TOKEN_KEY);
        if (s) {
          const raw = session.getItem(TOKEN_EXP_KEY);
          return { token: s, expEpochMs: raw ? Number(raw) : null, remembered: false };
        }
        const l = local.getItem(TOKEN_KEY);
        if (l) {
          const raw = local.getItem(TOKEN_EXP_KEY);
          return { token: l, expEpochMs: raw ? Number(raw) : null, remembered: true };
        }
        return null;
      },
      write(rec) {
        const primary = rec.remembered ? local : session;
        const other = rec.remembered ? session : local;
        other.removeItem(TOKEN_KEY);
        other.removeItem(TOKEN_EXP_KEY);
        primary.setItem(TOKEN_KEY, rec.token);
        if (rec.expEpochMs) primary.setItem(TOKEN_EXP_KEY, String(rec.expEpochMs));
        else primary.removeItem(TOKEN_EXP_KEY);
      },
      clear() {
        session.removeItem(TOKEN_KEY);
        session.removeItem(TOKEN_EXP_KEY);
        local.removeItem(TOKEN_KEY);
        local.removeItem(TOKEN_EXP_KEY);
      },
    };
    const client = createApi<never>({
      apiUrl: "https://api.test",
      fetch: async () => jsonResponse(200, {}),
      store,
      media: { mode: "media-token", store: memMediaStore().store },
      upload: noopUpload,
      isTestnet: false,
      onSessionExpired: () => {},
    });
    return { client, local, session };
  }

  it("remembered login lands in localStorage; default login wins over it", () => {
    const { client, local, session } = browserHarness();

    client.setToken(jwtWithExp(2_000_000_000), { remember: true });
    expect(local.getItem(TOKEN_KEY)).toBeTruthy();
    expect(session.getItem(TOKEN_KEY)).toBeNull();
    expect(client.isRemembered()).toBe(true);

    // A default (non-remembered) login supersedes and clears the other store.
    client.setToken("default-tok");
    expect(session.getItem(TOKEN_KEY)).toBe("default-tok");
    expect(local.getItem(TOKEN_KEY)).toBeNull();
    expect(client.getToken()).toBe("default-tok");
    expect(client.isRemembered()).toBe(false);

    // Clearing wipes both stores.
    client.setToken(null);
    expect(client.getToken()).toBeNull();
    expect(local._map.size + session._map.size).toBe(0);
  });

  it("stores the decoded exp alongside a remembered token", () => {
    const { client, local } = browserHarness();
    client.setToken(jwtWithExp(1_700_000_000), { remember: true });
    expect(local.getItem(TOKEN_EXP_KEY)).toBe(String(1_700_000_000_000));
  });
});
