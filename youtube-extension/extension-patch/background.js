try{importScripts("extsync-bridge.js");}catch(e){}
"use strict";
(() => {
  // ../../packages/shared/src/constants.ts
  var DEFAULT_PORT = 9797;
  var PORT_RANGE = Object.freeze(
    Array.from({ length: 10 }, (_, i) => DEFAULT_PORT + i)
  );
  var PAIRING_CODE_TTL_MS = 5 * 60 * 1e3;
  var LOCAL_HOSTS = Object.freeze([
    "127.0.0.1",
    "localhost"
  ]);
  var YOUTUBE_ORIGINS = Object.freeze([
    "https://www.youtube.com",
    "https://m.youtube.com"
  ]);

  // ../../packages/shared/src/errors.ts
  var ERRORS = {
    E_UNKNOWN: {
      he: "אירעה שגיאה לא צפויה.",
      en: "An unexpected error occurred.",
      hintHe: "נסה שוב, ואם הבעיה חוזרת פתח את מסך אבחון הרשת."
    },
    E_BAD_REQUEST: {
      he: "הבקשה אינה תקינה.",
      en: "The request was invalid."
    },
    E_UNPAIRED: {
      he: "התוסף עדיין לא חובר לתוכנה.",
      en: "The extension is not paired with the app yet.",
      hintHe: "פתח את הגדרות התוסף והזן את כתובת השרת."
    },
    E_INVALID_TOKEN: {
      he: "אסימון החיבור אינו תקף.",
      en: "The pairing token is invalid.",
      hintHe: "בדוק את הטוקן בהגדרות התוסף."
    },
    E_FORBIDDEN_ORIGIN: {
      he: "הבקשה הגיעה ממקור שאינו מורשה.",
      en: "The request came from a forbidden origin."
    },
    E_INVALID_PAIRING_CODE: {
      he: "קוד החיבור שגוי.",
      en: "The pairing code is incorrect."
    },
    E_PAIRING_EXPIRED: {
      he: "קוד החיבור פג תוקף.",
      en: "The pairing code has expired."
    },
    E_PROTOCOL_INCOMPATIBLE: {
      he: "גרסת התוסף אינה תואמת לגרסת התוכנה.",
      en: "The extension version is not compatible with the app."
    },
    E_INVALID_URL: {
      he: "הכתובת אינה תקינה.",
      en: "The URL is invalid."
    },
    E_UNSUPPORTED_SOURCE: {
      he: "המקור אינו נתמך.",
      en: "This source is not supported."
    },
    E_NOT_DIRECT_MEDIA: {
      he: "הכתובת אינה קובץ מדיה ישיר.",
      en: "The URL is not a direct media file."
    },
    E_AUTHORIZATION_REQUIRED: {
      he: "נדרש אישור שימוש מורשה לפני ההורדה.",
      en: "Authorized-use confirmation is required before downloading."
    },
    E_JOB_NOT_FOUND: {
      he: "ההורדה המבוקשת לא נמצאה.",
      en: "The requested download was not found."
    },
    E_CONCURRENCY_LIMIT: {
      he: "הגעת למספר המרבי של הורדות במקביל.",
      en: "The maximum number of concurrent downloads was reached."
    },
    E_DOWNLOAD_FAILED: {
      he: "ההורדה נכשלה.",
      en: "The download failed.",
      hintHe: "בדוק את החיבור לרשת ונסה שוב."
    },
    E_NETWORK: {
      he: "בעיית רשת מנעה את ההורדה.",
      en: "A network problem prevented the download."
    },
    E_CANCELLED: {
      he: "ההורדה בוטלה.",
      en: "The download was cancelled."
    },
    E_SERVER_NOT_RUNNING: {
      he: "התוסף מתעורר לרגע - נסה שוב.",
      en: "The extension is waking up - please try again."
    },
    E_SERVER_UNREACHABLE: {
      he: "לא ניתן להגיע לשרת ההורדות כרגע.",
      en: "Could not reach the download server right now.",
      hintHe: "ודא שכתובת השרת בהגדרות נכונה ושהשרת (Colab) פעיל."
    }
  };
  function makeError(code, detail) {
    const def = ERRORS[code] ?? ERRORS.E_UNKNOWN;
    const error = {
      code,
      message: def.he,
      messageEn: def.en
    };
    if (def.hintHe) error.hint = def.hintHe;
    if (detail) error.detail = sanitizeDetail(detail);
    return error;
  }
  function sanitizeDetail(detail) {
    return detail.replace(/(X-SaveBridge-Token['":\s]*)[A-Za-z0-9_-]+/gi, "$1***").replace(/([?&](?:token|key|secret|auth)=)[^&\s]+/gi, "$1***").replace(/[A-Za-z]:\\Users\\[^\\\s]+/g, "%USERPROFILE%").replace(/\/home\/[^/\s]+/g, "~").slice(0, 500);
  }

  // ../../packages/shared/src/types.ts
  var TERMINAL_STATUSES = ["completed", "failed", "cancelled"];
  function isTerminalStatus(status) {
    return TERMINAL_STATUSES.includes(status);
  }
  var DEFAULT_BUTTON_TEXT = "הורדה";

  // src/shared/serverApi.ts
  var trimBase = (url) => (url || "").replace(/\/+$/, "");
  function authHeaders(token) {
    return token ? { Authorization: `Bearer ${token}` } : {};
  }
  async function ping(base, token, timeoutMs = 8e3) {
    if (!base) return { reachable: false, authorized: false, ytDlp: null, ffmpeg: false };
    try {
      const res = await fetch(`${trimBase(base)}/api/ping`, {
        headers: authHeaders(token),
        signal: AbortSignal.timeout(timeoutMs)
      });
      if (res.status === 401) return { reachable: true, authorized: false, ytDlp: null, ffmpeg: false };
      const json = await res.json().catch(() => null);
      return { reachable: true, authorized: res.ok, ytDlp: json?.ytDlp ?? null, ffmpeg: Boolean(json?.ffmpeg) };
    } catch {
      return { reachable: false, authorized: false, ytDlp: null, ffmpeg: false };
    }
  }
  async function register(base, timeoutMs = 8e3) {
    if (!base) return null;
    try {
      const res = await fetch(`${trimBase(base)}/api/hello`, {
        method: "POST",
        signal: AbortSignal.timeout(timeoutMs)
      });
      if (!res.ok) return null;
      const json = await res.json().catch(() => null);
      return typeof json?.token === "string" && json.token ? json.token : null;
    } catch {
      return null;
    }
  }
  async function startDownload(base, token, input) {
    try {
      const res = await fetch(`${trimBase(base)}/api/start`, {
        method: "POST",
        headers: { ...authHeaders(token), "Content-Type": "application/json" },
        body: JSON.stringify(input),
        signal: AbortSignal.timeout(2e4)
      });
      if (res.status === 401) return { ok: false, error: makeError("E_UNPAIRED") };
      const json = await res.json().catch(() => null);
      if (res.ok && json?.jobId) return { ok: true, jobId: json.jobId };
      return { ok: false, error: makeError("E_DOWNLOAD_FAILED", `HTTP ${res.status}`) };
    } catch {
      return { ok: false, error: makeError("E_SERVER_UNREACHABLE") };
    }
  }
  async function getJob(base, token, id) {
    try {
      const res = await fetch(`${trimBase(base)}/api/jobs/${encodeURIComponent(id)}`, {
        headers: authHeaders(token),
        signal: AbortSignal.timeout(8e3)
      });
      if (res.status === 401) return { ok: false, error: makeError("E_UNPAIRED") };
      const json = await res.json().catch(() => null);
      if (res.ok && json && typeof json.status === "string") return { ok: true, job: json };
      return { ok: false, error: makeError("E_UNKNOWN", `HTTP ${res.status}`) };
    } catch {
      return { ok: false, error: makeError("E_SERVER_UNREACHABLE") };
    }
  }
  async function cancelJob(base, token, id) {
    try {
      const res = await fetch(`${trimBase(base)}/api/jobs/${encodeURIComponent(id)}/cancel`, {
        method: "POST",
        headers: authHeaders(token),
        signal: AbortSignal.timeout(8e3)
      });
      if (res.status === 401) return { ok: false, error: makeError("E_UNPAIRED") };
      return res.ok ? { ok: true } : { ok: false, error: makeError("E_UNKNOWN", `HTTP ${res.status}`) };
    } catch {
      return { ok: false, error: makeError("E_SERVER_UNREACHABLE") };
    }
  }
  function fileUrl(base, token, id) {
    const q = token ? `?token=${encodeURIComponent(token)}` : "";
    return `${trimBase(base)}/api/jobs/${encodeURIComponent(id)}/file${q}`;
  }

  // src/shared/cookies.ts
  var COOKIE_DOMAINS = ["youtube.com", "google.com"];
  async function exportYoutubeCookies() {
    if (!chrome.cookies?.getAll) return null;
    try {
      const groups = await Promise.all(COOKIE_DOMAINS.map((domain) => chrome.cookies.getAll({ domain })));
      const seen = /* @__PURE__ */ new Set();
      const lines = ["# Netscape HTTP Cookie File"];
      for (const c of groups.flat()) {
        const key = `${c.domain}|${c.name}|${c.path}`;
        if (seen.has(key)) continue;
        seen.add(key);
        let domain = c.domain;
        if (!c.hostOnly && !domain.startsWith(".")) domain = `.${domain}`;
        const includeSub = c.hostOnly ? "FALSE" : "TRUE";
        const secure = c.secure ? "TRUE" : "FALSE";
        const expiry = c.expirationDate ? Math.floor(c.expirationDate) : 0;
        const prefix = c.httpOnly ? "#HttpOnly_" : "";
        lines.push(`${prefix}${domain}	${includeSub}	${c.path}	${secure}	${expiry}	${c.name}	${c.value}`);
      }
      return lines.length > 1 ? `${lines.join("\n")}
` : null;
    } catch {
      return null;
    }
  }

  // src/shared/storage.ts
  var KEY = "savebridge";
  var DEFAULT_STATE = {
    buttonText: DEFAULT_BUTTON_TEXT,
    debug: false,
    defaultOption: "video_best",
    showNotifications: true,
    encryptDownloads: false
  };
  var LEGACY_BUTTON_TEXT = "להוריד";
  async function getState() {
    const stored = await chrome.storage.local.get(KEY);
    const state = { ...DEFAULT_STATE, ...stored[KEY] };
    if (state.buttonText === LEGACY_BUTTON_TEXT) state.buttonText = DEFAULT_BUTTON_TEXT;
    return state;
  }
  async function setState(patch) {
    const current = await getState();
    const next = { ...current, ...patch };
    await chrome.storage.local.set({ [KEY]: next });
    return next;
  }
  // --- server connection config (your own free relay) ---
  var SERVER_KEY = "savebridge.server";
  async function getServerConfig() {
    const stored = await chrome.storage.local.get(SERVER_KEY);
    const v = stored[SERVER_KEY] ?? {};
    return { url: typeof v.url === "string" ? v.url : "", token: typeof v.token === "string" ? v.token : "" };
  }
  var CLIENT_KEY = "savebridge.client";
  async function getClientToken() {
    const stored = await chrome.storage.local.get(CLIENT_KEY);
    const v = stored[CLIENT_KEY];
    return v?.token ?? null;
  }
  async function setClientToken(token) {
    await chrome.storage.local.set({ [CLIENT_KEY]: { token } });
  }
  async function clearClientToken() {
    await chrome.storage.local.remove(CLIENT_KEY);
  }
  function onStateChange(cb) {
    const listener = (changes, area) => {
      if (area === "local" && changes[KEY]) {
        cb({ ...DEFAULT_STATE, ...changes[KEY].newValue });
      }
    };
    chrome.storage.onChanged.addListener(listener);
    return () => chrome.storage.onChanged.removeListener(listener);
  }

  // src/shared/log.ts
  var debugEnabled = false;
  function setDebug(enabled) {
    debugEnabled = enabled;
  }
  function isDebug() {
    return debugEnabled;
  }
  function log(...args) {
    if (debugEnabled) console.log("%c[SaveBridge]", "color:#4d8bff", ...args);
  }

  // src/background/index.ts
  //
  // The download backend is now YOUR OWN relay server (see youtube-extension/server),
  // configured from the options page. No hardcoded paid relay, no request signing,
  // and cookies go only to the server you control.
  var BASE = "";
  var userToken = "";
  var lastBase = null;
  async function refreshServerConfig() {
    const cfg = await getServerConfig();
    BASE = trimBase(cfg.url);
    userToken = cfg.token || "";
    if (BASE !== lastBase) {
      clientToken = null;
      lastBase = BASE;
    }
  }
  var notified = /* @__PURE__ */ new Set();
  var saved = /* @__PURE__ */ new Set();
  var clientToken = null;
  var tokenInFlight = null;
  async function ensureToken() {
    if (userToken) return userToken;
    if (clientToken) return clientToken;
    if (!tokenInFlight) {
      tokenInFlight = (async () => {
        const stored = await getClientToken();
        if (stored) {
          clientToken = stored;
          return stored;
        }
        const fresh = await register(BASE);
        if (fresh) {
          clientToken = fresh;
          await setClientToken(fresh);
          return fresh;
        }
        return "";
      })().finally(() => {
        tokenInFlight = null;
      });
    }
    return tokenInFlight;
  }
  async function reregister() {
    clientToken = null;
    await clearClientToken();
    return ensureToken();
  }
  async function withToken(call) {
    const res = await call(await ensureToken());
    if (!res.ok && res.error?.code === "E_UNPAIRED" && !userToken) {
      return call(await reregister());
    }
    return res;
  }
  async function initDebug() {
    setDebug((await getState()).debug);
  }
  void initDebug();
  void refreshServerConfig();
  onStateChange((s) => setDebug(s.debug));
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes[SERVER_KEY]) void refreshServerConfig();
  });
  async function ensureConnection() {
    await refreshServerConfig();
    if (!BASE) return { state: "disconnected", ytDlp: null, serverUrl: BASE };
    const p = await ping(BASE, await ensureToken());
    if (!p.reachable) return { state: "disconnected", ytDlp: null, serverUrl: BASE };
    if (!p.authorized) return { state: "running-unpaired", ytDlp: p.ytDlp, serverUrl: BASE };
    return { state: "paired", ytDlp: p.ytDlp, serverUrl: BASE };
  }
  async function buildPrefs() {
    const state = await getState();
    const conn = await ensureConnection();
    return {
      buttonText: state.buttonText,
      debug: state.debug,
      defaultOption: state.defaultOption,
      connection: conn.state
    };
  }
  function toPublicJob(j) {
    const terminal = isTerminalStatus(j.status);
    return {
      id: j.id,
      url: "",
      title: j.title,
      source: "youtube",
      format: j.format,
      quality: j.quality,
      status: j.status,
      percent: j.percent,
      speed: j.speed,
      eta: j.eta,
      bytesDownloaded: 0,
      bytesTotal: null,
      outputPath: null,
      createdAt: Date.now(),
      startedAt: null,
      finishedAt: terminal ? Date.now() : null,
      error: j.error,
      cancellable: j.status === "preparing" || j.status === "downloading",
      playlist: false,
      playlistProgress: null
    };
  }
  async function saveFile(job) {
    if (saved.has(job.id)) return;
    saved.add(job.id);
    try {
      const token = await ensureToken();
      await chrome.downloads.download({ url: fileUrl(BASE, token, job.id), filename: outputName(job) });
    } catch (err) {
      saved.delete(job.id);
      if (isDebug()) log("save failed", err);
    }
  }
  function safeDownloadName(name) {
    if (!name) return void 0;
    const cleaned = name.replace(/[\\/]+/g, "_").replace(/^[.\s]+/, "").trim();
    return cleaned || void 0;
  }
  function outputName(job) {
    const clean = safeDownloadName(job.fileName);
    if (clean && /\.[a-z0-9]{2,5}$/i.test(clean)) return clean;
    const ext = job.format === "audio" ? "mp3" : job.format === "low_phone" ? "3gp" : "mp4";
    const base = clean?.replace(/\.[^.]*$/, "") || safeDownloadName(job.title) || "video";
    return `${base}.${ext}`;
  }
  async function handle(msg) {
    await refreshServerConfig();
    switch (msg.type) {
      case "CHECK_CONNECTION":
        return ensureConnection();
      case "GET_PREFS":
        return buildPrefs();
      case "GET_EXT_SETTINGS": {
        const state = await getState();
        return { buttonText: state.buttonText, debug: state.debug };
      }
      case "SET_EXT_SETTINGS": {
        const next = await setState(msg.patch);
        setDebug(next.debug);
        return { buttonText: next.buttonText, debug: next.debug };
      }
      case "START_DOWNLOAD": {
        if (!BASE) return { ok: false, error: makeError("E_UNPAIRED") };
        const cookies = await exportYoutubeCookies() ?? void 0;
        const result = await withToken(
          (token) => startDownload(BASE, token, {
            url: msg.payload.url,
            title: msg.payload.title,
            format: msg.payload.format,
            quality: msg.payload.quality,
            cookies,
            audioLang: msg.payload.audioLang,
            subLang: msg.payload.subLang,
            subData: msg.payload.subData
          })
        );
        return result;
      }
      case "POLL_JOB": {
        const result = await withToken((token) => getJob(BASE, token, msg.jobId));
        if (!result.ok) return result;
        const job = result.job;
        if (job.status === "completed" && job.hasFile) await saveFile(job);
        await maybeNotify(job.id, job.status, job.title, job.error?.message);
        return { ok: true, job: toPublicJob(job) };
      }
      case "CANCEL_JOB":
        return withToken((token) => cancelJob(BASE, token, msg.jobId));
      case "OPEN_DOWNLOADS": {
        try {
          chrome.downloads.showDefaultFolder();
        } catch {
        }
        return { ok: true };
      }
      case "OPEN_OPTIONS":
        await chrome.runtime.openOptionsPage();
        return { ok: true };
      default:
        return { ok: false, error: makeError("E_BAD_REQUEST") };
    }
  }
  async function maybeNotify(jobId, status, title, errorMessage) {
    if (status !== "completed" && status !== "failed") return;
    if (!(await getState()).showNotifications) return;
    const key = `${jobId}:${status}`;
    if (notified.has(key)) return;
    notified.add(key);
    try {
      chrome.notifications.create(key, {
        type: "basic",
        iconUrl: chrome.runtime.getURL("icons/icon-128.png"),
        title: status === "completed" ? "ההורדה הסתיימה" : "ההורדה נכשלה",
        message: status === "completed" ? title : errorMessage ?? title
      });
    } catch {
    }
  }
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.target === "offscreen") return false;
    handle(message).then((result) => sendResponse(result)).catch((err) => {
      if (isDebug()) log("handler error", err);
      sendResponse({ ok: false, error: makeError("E_UNKNOWN", String(err)) });
    });
    return true;
  });
  chrome.action.onClicked.addListener(() => {
    void chrome.runtime.openOptionsPage();
  });
  log("background worker ready (self-hosted server mode)");
})();
