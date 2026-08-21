"use strict";
(() => {
  var PRESET_ORDER = ["video_best", "video_1080", "video_720", "video_480", "audio_only", "low_phone"];
  var DEFAULT_BUTTON_TEXT = "הורדה";

  // --- messaging -----------------------------------------------------------
  function makeError(code) {
    return { code, message: "התוסף מתעורר לרגע - נסה שוב.", messageEn: "Please try again." };
  }
  async function send(message) {
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        return await chrome.runtime.sendMessage(message);
      } catch {
        if (attempt === 0) await new Promise((r) => setTimeout(r, 250));
      }
    }
    return { ok: false, error: makeError("E_SERVER_NOT_RUNNING") };
  }

  // --- storage -------------------------------------------------------------
  var KEY = "savebridge";
  var SERVER_KEY = "savebridge.server";
  var CLIENT_KEY = "savebridge.client";
  var DEFAULT_STATE = {
    buttonText: DEFAULT_BUTTON_TEXT,
    debug: false,
    defaultOption: "video_best",
    showNotifications: true,
    encryptDownloads: false
  };
  async function getState() {
    const s = await chrome.storage.local.get(KEY);
    return { ...DEFAULT_STATE, ...s[KEY] };
  }
  async function setState(patch) {
    const cur = await getState();
    const next = { ...cur, ...patch };
    await chrome.storage.local.set({ [KEY]: next });
    return next;
  }
  async function resetState() {
    await chrome.storage.local.set({ [KEY]: DEFAULT_STATE });
    await chrome.storage.local.remove(SERVER_KEY);
    await chrome.storage.local.remove(CLIENT_KEY);
    return DEFAULT_STATE;
  }
  async function getServerConfig() {
    const s = await chrome.storage.local.get(SERVER_KEY);
    const v = s[SERVER_KEY] ?? {};
    return { url: typeof v.url === "string" ? v.url : "", token: typeof v.token === "string" ? v.token : "" };
  }
  async function setServerConfig(cfg) {
    await chrome.storage.local.set({ [SERVER_KEY]: cfg });
    await chrome.storage.local.remove(CLIENT_KEY);
  }

  // --- i18n ----------------------------------------------------------------
  var he = {
    "options.subtitle": "העדפות כפתור ההורדה.",
    "options.extVersion": "גרסה",
    "options.serverTitle": "שרת ההורדות שלך",
    "options.serverUrl": "כתובת השרת",
    "options.serverToken": "טוקן (סיסמה) — אופציונלי",
    "options.save": "שמור וחבר",
    "options.serverSaved": "נשמר. בודק חיבור…",
    "options.serverNeedUrl": "הזן כתובת שרת (למשל הכתובת ש-Colab נותן).",
    "options.connectionTitle": "מצב החיבור לשרת",
    "options.connected": "מחובר ✔",
    "options.running": "השרת מגיב אך הטוקן שגוי",
    "options.notRunning": "לא מחובר — בדוק את כתובת השרת ושהוא פעיל",
    "options.recheck": "בדוק חיבור",
    "options.prefsTitle": "העדפות",
    "options.buttonText": "טקסט הכפתור ב-YouTube",
    "options.defaultOption": "אפשרות הורדה ברירת מחדל",
    "options.debug": "מצב ניפוי שגיאות (debug)",
    "options.advancedTitle": "מתקדם",
    "options.reset": "אפס הגדרות תוסף",
    "options.saved": "נשמר",
    "options.serverHelpTitle": "איך זה עובד?",
    "options.serverHelpBody": "התוסף מוריד סרטוני YouTube דרך שרת חינמי משלך (למשל Google Colab). הפעל את השרת, העתק את הכתובת שהוא מדפיס, הדבק אותה למעלה ולחץ \"שמור וחבר\". רק ודא שאתה מחובר ל-YouTube בדפדפן — התוסף משתמש בזהות שלך אוטומטית.",
    "preset.video_best": "וידאו — איכות מיטבית",
    "preset.video_1080": "וידאו — 1080p",
    "preset.video_720": "וידאו — 720p",
    "preset.video_480": "וידאו — 480p",
    "preset.audio_only": "אודיו בלבד",
    "preset.low_phone": "3GP"
  };
  var en = {
    "options.subtitle": "Download button preferences.",
    "options.extVersion": "Version",
    "options.serverTitle": "Your download server",
    "options.serverUrl": "Server URL",
    "options.serverToken": "Token (password) — optional",
    "options.save": "Save & connect",
    "options.serverSaved": "Saved. Checking connection…",
    "options.serverNeedUrl": "Enter a server URL (e.g. the one Colab prints).",
    "options.connectionTitle": "Server connection",
    "options.connected": "Connected ✔",
    "options.running": "Server reachable but the token is wrong",
    "options.notRunning": "Not connected — check the server URL and that it is running",
    "options.recheck": "Check connection",
    "options.prefsTitle": "Preferences",
    "options.buttonText": "Button text on YouTube",
    "options.defaultOption": "Default download option",
    "options.debug": "Debug mode",
    "options.advancedTitle": "Advanced",
    "options.reset": "Reset extension settings",
    "options.saved": "Saved",
    "options.serverHelpTitle": "How it works",
    "options.serverHelpBody": "The extension downloads YouTube videos through your own free server (e.g. Google Colab). Start the server, copy the URL it prints, paste it above and click \"Save & connect\". Just make sure you're signed into YouTube in this browser — the extension uses your session automatically.",
    "preset.video_best": "Video — best quality",
    "preset.video_1080": "Video — 1080p",
    "preset.video_720": "Video — 720p",
    "preset.video_480": "Video — 480p",
    "preset.audio_only": "Audio only",
    "preset.low_phone": "3GP"
  };
  var useEnglish = navigator.language.toLowerCase().startsWith("en");
  var dict = useEnglish ? en : he;
  function t(key) {
    return dict[key] ?? he[key] ?? key;
  }
  document.documentElement.lang = useEnglish ? "en" : "he";
  document.documentElement.dir = useEnglish ? "ltr" : "rtl";

  var $ = (id) => document.getElementById(id);
  var setText = (id, key) => {
    const el = $(id);
    if (el) el.textContent = t(key);
  };

  function applyStaticText() {
    $("subtitle").textContent = t("options.subtitle");
    $("version").textContent = `${t("options.extVersion")} ${chrome.runtime.getManifest().version}`;
    setText("serverTitle", "options.serverTitle");
    setText("serverUrlLabel", "options.serverUrl");
    setText("serverTokenLabel", "options.serverToken");
    setText("saveServer", "options.save");
    setText("connectionTitle", "options.connectionTitle");
    setText("recheck", "options.recheck");
    setText("prefsTitle", "options.prefsTitle");
    setText("buttonTextLabel", "options.buttonText");
    setText("defaultOptionLabel", "options.defaultOption");
    setText("debugLabel", "options.debug");
    setText("advancedTitle", "options.advancedTitle");
    setText("reset", "options.reset");
    setText("installTitle", "options.serverHelpTitle");
    setText("installBody", "options.serverHelpBody");
    const select = $("defaultOption");
    select.replaceChildren();
    for (const id of PRESET_ORDER) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = t(`preset.${id}`);
      select.append(opt);
    }
  }

  function normalizeUrl(raw) {
    let url = (raw || "").trim();
    if (!url) return "";
    if (!/^https?:\/\//i.test(url)) url = "https://" + url;
    return url.replace(/\/+$/, "");
  }

  async function refreshConnection() {
    const conn = await send({ type: "CHECK_CONNECTION" });
    const dot = $("conn-dot");
    const text = $("conn-text");
    dot.className = "dot";
    if (conn?.state === "paired") {
      dot.classList.add("is-ok");
      text.textContent = t("options.connected");
    } else if (conn?.state === "running-unpaired") {
      dot.classList.add("is-warn");
      text.textContent = t("options.running");
    } else {
      dot.classList.add("is-fail");
      text.textContent = t("options.notRunning");
    }
  }

  async function loadPrefs() {
    const state = await getState();
    $("buttonText").value = state.buttonText;
    $("debug").checked = state.debug;
    $("defaultOption").value = state.defaultOption;
    const cfg = await getServerConfig();
    $("serverUrl").value = cfg.url;
    $("serverToken").value = cfg.token;
  }

  var toastTimer = null;
  function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.hidden = false;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.hidden = true), 1600);
  }

  function wireEvents() {
    $("saveServer").addEventListener("click", async () => {
      const url = normalizeUrl($("serverUrl").value);
      const token = $("serverToken").value.trim();
      const msgEl = $("serverMsg");
      msgEl.className = "msg";
      if (!url) {
        msgEl.classList.add("is-fail");
        msgEl.textContent = t("options.serverNeedUrl");
        return;
      }
      $("serverUrl").value = url;
      await setServerConfig({ url, token });
      msgEl.classList.add("is-ok");
      msgEl.textContent = t("options.serverSaved");
      await refreshConnection();
    });
    $("recheck").addEventListener("click", () => void refreshConnection());
    $("buttonText").addEventListener("change", async (e) => {
      const value = e.target.value.trim() || DEFAULT_BUTTON_TEXT;
      await setState({ buttonText: value });
      toast(t("options.saved"));
    });
    $("debug").addEventListener("change", async (e) => {
      await setState({ debug: e.target.checked });
      toast(t("options.saved"));
    });
    $("defaultOption").addEventListener("change", async (e) => {
      await setState({ defaultOption: e.target.value });
      toast(t("options.saved"));
    });
    $("reset").addEventListener("click", async () => {
      await resetState();
      await reload();
      toast(t("options.saved"));
    });
  }

  async function reload() {
    await loadPrefs();
    await refreshConnection();
  }

  applyStaticText();
  wireEvents();
  void reload();
})();
