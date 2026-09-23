/**
 * Suitest Web Recorder Agent
 * Injected into target web pages to capture user interactions (navigate, click, type)
 * and stream them in real-time to Suitest recorder sessions.
 */
(function () {
  if (window.__SUITEST_RECORDER_INITIALIZED__) {
    return;
  }
  window.__SUITEST_RECORDER_INITIALIZED__ = true;

  // 1. Resolve configuration from script element, window, or URL params
  var scriptTag = document.currentScript;
  var urlParams = new URLSearchParams(window.location.search);

  var sessionId =
    (scriptTag && scriptTag.getAttribute("data-session-id")) ||
    window.__SUITEST_SESSION_ID__ ||
    urlParams.get("session_id") ||
    "";

  var workspaceId =
    (scriptTag && scriptTag.getAttribute("data-workspace-id")) ||
    window.__SUITEST_WORKSPACE_ID__ ||
    urlParams.get("workspaceId") ||
    "";

  var rawApiBase =
    (scriptTag && scriptTag.getAttribute("data-api-url")) ||
    window.__SUITEST_API_URL__ ||
    "/api/v1";

  // When <base href="..."> is present in target HTML, relative fetch URLs resolve to target domain.
  // We MUST ensure apiBase is absolute with window.location.origin!
  var apiBase = rawApiBase;
  if (apiBase.startsWith("/")) {
    apiBase = window.location.origin + apiBase;
  }

  // Restore session information from sessionStorage if running in external/bookmarklet tab
  if (!sessionId) {
    try {
      var storedSession = sessionStorage.getItem("__suitest_recorder_session__");
      if (storedSession) {
        var parsed = JSON.parse(storedSession);
        sessionId = parsed.sessionId || "";
        workspaceId = workspaceId || parsed.workspaceId || "";
        apiBase = apiBase || parsed.apiBase || apiBase;
      }
    } catch (e) {
      console.debug("[Suitest Recorder] Could not read session from sessionStorage:", e);
    }
  } else {
    try {
      sessionStorage.setItem(
        "__suitest_recorder_session__",
        JSON.stringify({ sessionId: sessionId, workspaceId: workspaceId, apiBase: apiBase })
      );
    } catch (e) {
      console.debug("[Suitest Recorder] Could not save session to sessionStorage:", e);
    }
  }

  // Restore action count across navigations
  var capturedCount = 0;
  try {
    var storedCount = sessionStorage.getItem("__suitest_captured_count__");
    if (storedCount) {
      capturedCount = parseInt(storedCount, 10) || 0;
    }
  } catch (e) {
    console.debug("[Suitest Recorder] Could not restore captured count from sessionStorage:", e);
  }

  var eventQueue = [];
  var isSending = false;

  function isInBrowseMode() {
    return Boolean(
      window.__SUITEST_TARGET_URL__ ||
      window.__SUITEST_BROWSE_ENDPOINT__ ||
      (window.location.pathname && window.location.pathname.includes("/browse"))
    );
  }

  function getCurrentVirtualUrl() {
    if (window.__SUITEST_TARGET_URL__) {
      try {
        var base = new URL(window.__SUITEST_TARGET_URL__);
        return new URL(
          window.location.pathname + window.location.search + window.location.hash,
          base.origin
        ).toString();
      } catch (e) {
        return window.__SUITEST_TARGET_URL__;
      }
    }
    if (window.location.pathname && window.location.pathname.includes("/browse")) {
      var params = new URLSearchParams(window.location.search);
      var proxied = params.get("url");
      if (proxied) return proxied;
    }
    return window.location.href;
  }

  function getBrowseProxyUrl(rawTargetUrl) {
    if (!isInBrowseMode()) return rawTargetUrl;
    try {
      var resolved = new URL(rawTargetUrl, getCurrentVirtualUrl()).toString();
      var browseEndpoint =
        window.__SUITEST_BROWSE_ENDPOINT__ ||
        (window.__SUITEST_SESSION_ID__
          ? `/api/v1/generators/recorder/sessions/${window.__SUITEST_SESSION_ID__}/browse`
          : "/browse");
      var browseUrl = new URL(browseEndpoint, window.location.origin);
      browseUrl.searchParams.set("url", resolved);
      var wsId =
        window.__SUITEST_WORKSPACE_ID__ ||
        new URLSearchParams(window.location.search).get("workspaceId");
      if (wsId) {
        browseUrl.searchParams.set("workspaceId", wsId);
      }
      return browseUrl.toString();
    } catch (err) {
      return rawTargetUrl;
    }
  }

  // 2. Resilient Selector Engine
  function getSelector(el) {
    if (!el || el === document.body || el === document.documentElement) {
      return "body";
    }

    // Priority 1: data-testid or data-test
    if (el.getAttribute("data-testid")) {
      return `[data-testid="${el.getAttribute("data-testid")}"]`;
    }
    if (el.getAttribute("data-test")) {
      return `[data-test="${el.getAttribute("data-test")}"]`;
    }

    // Priority 2: Semantic ID if not auto-generated
    if (el.id && !/^[0-9]|^ember|^react-|^vue-|:[a-z0-9]+:/i.test(el.id)) {
      return `#${CSS.escape(el.id)}`;
    }

    // Priority 3: Form name or input placeholder
    var tag = el.tagName.toLowerCase();
    if (el.getAttribute("name")) {
      return `${tag}[name="${el.getAttribute("name")}"]`;
    }
    if (el.getAttribute("placeholder")) {
      return `${tag}[placeholder="${el.getAttribute("placeholder")}"]`;
    }

    // Priority 4: Button or link text content
    if (tag === "button" || (tag === "a" && el.innerText && el.innerText.length < 35)) {
      var text = (el.innerText || "").trim().replace(/\s+/g, " ");
      if (text.length > 0 && text.length <= 30) {
        return `${tag}:has-text("${text.replace(/"/g, '\\"')}")`;
      }
    }

    // Priority 5: aria-label or role
    if (el.getAttribute("aria-label")) {
      return `[aria-label="${el.getAttribute("aria-label")}"]`;
    }
    if (el.getAttribute("role")) {
      return `[role="${el.getAttribute("role")}"]`;
    }

    // Priority 6: Concise class or hierarchical path
    var classNames = Array.from(el.classList || [])
      .filter(function (c) {
        return !/^(hover|active|focus|valid|invalid|is-|has-|_)/.test(c);
      })
      .slice(0, 2);
    if (classNames.length > 0) {
      var classSelector = `${tag}.${classNames.map(CSS.escape).join(".")}`;
      if (document.querySelectorAll(classSelector).length === 1) {
        return classSelector;
      }
    }

    // Hierarchy fallback
    var parent = el.parentElement;
    if (parent) {
      var siblings = Array.from(parent.children).filter(function (c) {
        return c.tagName === el.tagName;
      });
      var index = siblings.indexOf(el) + 1;
      var parentSel = parent === document.body ? "" : getSelector(parent) + " > ";
      return `${parentSel}${tag}${siblings.length > 1 ? `:nth-of-type(${index})` : ""}`;
    }

    return tag;
  }

  // 3. Floating HUD UI
  var hudContainer = null;
  var hudCounter = null;
  var hudLastAction = null;

  function createHUD() {
    var existing = document.getElementById("suitest-recorder-hud");
    if (existing) {
      hudContainer = existing;
      hudCounter = existing.querySelector("#suitest-hud-counter");
      hudLastAction = existing.querySelector("#suitest-hud-last-action");
      return;
    }

    hudContainer = document.createElement("div");
    hudContainer.id = "suitest-recorder-hud";
    hudContainer.style.cssText = [
      "position: fixed",
      "bottom: 24px",
      "right: 24px",
      "z-index: 2147483647",
      "display: flex",
      "flex-direction: column",
      "gap: 8px",
      "background: rgba(15, 23, 42, 0.96)",
      "backdrop-filter: blur(12px)",
      "-webkit-backdrop-filter: blur(12px)",
      "border: 1px solid rgba(255, 255, 255, 0.18)",
      "border-radius: 12px",
      "padding: 12px 16px",
      "box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5)",
      "color: #f8fafc",
      "font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
      "font-size: 12px",
      "max-width: 340px",
      "user-select: none",
      "transition: box-shadow 0.2s ease",
    ].join(";");

    var header = document.createElement("div");
    header.style.cssText = "display: flex; align-items: center; justify-content: space-between; gap: 12px;";

    var titleWrapper = document.createElement("div");
    titleWrapper.style.cssText = "display: flex; align-items: center; gap: 8px; font-weight: 600;";

    var pulseDot = document.createElement("span");
    pulseDot.style.cssText = [
      "width: 8px",
      "height: 8px",
      "border-radius: 50%",
      "background-color: #ef4444",
      "box-shadow: 0 0 8px #ef4444",
      "display: inline-block",
    ].join(";");

    var titleText = document.createElement("span");
    titleText.textContent = "Suitest Recorder";

    titleWrapper.appendChild(pulseDot);
    titleWrapper.appendChild(titleText);

    hudCounter = document.createElement("span");
    hudCounter.id = "suitest-hud-counter";
    hudCounter.style.cssText =
      "background: rgba(239, 68, 68, 0.2); color: #fca5a5; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600;";
    hudCounter.textContent = `${capturedCount} action${capturedCount === 1 ? "" : "s"}`;

    header.appendChild(titleWrapper);
    header.appendChild(hudCounter);

    hudLastAction = document.createElement("div");
    hudLastAction.id = "suitest-hud-last-action";
    hudLastAction.style.cssText = [
      "font-size: 11px",
      "color: #94a3b8",
      "overflow: hidden",
      "text-overflow: ellipsis",
      "white-space: nowrap",
      "padding-top: 4px",
      "border-top: 1px solid rgba(255, 255, 255, 0.08)",
    ].join(";");
    hudLastAction.textContent = isInBrowseMode()
      ? "Recording active in proxy tab"
      : "Recording active (Bookmarklet tab)";

    hudContainer.appendChild(header);
    hudContainer.appendChild(hudLastAction);

    // Make HUD draggable
    var isDragging = false;
    var startX, startY, initialX, initialY;

    header.style.cursor = "grab";
    header.addEventListener("mousedown", function (e) {
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      var rect = hudContainer.getBoundingClientRect();
      initialX = rect.left;
      initialY = rect.top;
      header.style.cursor = "grabbing";
    });

    window.addEventListener("mousemove", function (e) {
      if (!isDragging) return;
      var dx = e.clientX - startX;
      var dy = e.clientY - startY;
      hudContainer.style.left = `${initialX + dx}px`;
      hudContainer.style.top = `${initialY + dy}px`;
      hudContainer.style.bottom = "auto";
      hudContainer.style.right = "auto";
    });

    window.addEventListener("mouseup", function () {
      if (isDragging) {
        isDragging = false;
        header.style.cursor = "grab";
      }
    });

    var targetParent = document.body || document.documentElement;
    if (targetParent) {
      targetParent.appendChild(hudContainer);
    }
  }

  // Observe DOM changes to re-inject HUD if page framework clears or resets the DOM
  var hudCheckScheduled = false;
  if (window.MutationObserver && document.documentElement) {
    var hudObserver = new MutationObserver(function () {
      if (!hudCheckScheduled) {
        hudCheckScheduled = true;
        setTimeout(function () {
          hudCheckScheduled = false;
          if (!document.getElementById("suitest-recorder-hud")) {
            createHUD();
          }
        }, 150);
      }
    });
    hudObserver.observe(document.documentElement, { childList: true, subtree: true });
  }

  function sanitizeString(str, maxLen) {
    if (typeof str !== "string") return "";
    return str.slice(0, maxLen || 1024);
  }

  // 4. Send Event to Suitest Session API
  function postEvent(eventData) {
    if (!sessionId || typeof sessionId !== "string" || !/^[a-zA-Z0-9_-]+$/.test(sessionId)) {
      console.warn("[Suitest Recorder] Valid session_id required, event ignored:", eventData);
      return;
    }

    var validKinds = ["click", "type", "navigate", "assert", "network"];
    if (!eventData || !validKinds.includes(eventData.kind)) {
      return;
    }

    var safeEvent = {
      kind: eventData.kind,
      timestamp: sanitizeString(eventData.timestamp, 64) || new Date().toISOString(),
      url: sanitizeString(eventData.url, 2048) || getCurrentVirtualUrl(),
      selector: sanitizeString(eventData.selector, 512),
      text: sanitizeString(eventData.text, 2048),
      masked: Boolean(eventData.masked),
    };

    // If un-sent event at the end of the queue is typing or clicking the same selector, update in-place
    if (eventQueue.length > 0) {
      var lastInQueue = eventQueue[eventQueue.length - 1];
      if (
        (lastInQueue.kind === "type" && safeEvent.kind === "type" && lastInQueue.selector === safeEvent.selector) ||
        (lastInQueue.kind === "click" && safeEvent.kind === "type" && lastInQueue.selector === safeEvent.selector)
      ) {
        eventQueue[eventQueue.length - 1] = safeEvent;
        return;
      }
    }

    eventQueue.push(safeEvent);
    processQueue();
  }

  function updateCapturedCount(newCount) {
    if (typeof newCount === "number") {
      capturedCount = newCount;
    } else {
      capturedCount++;
    }
    try {
      sessionStorage.setItem("__suitest_captured_count__", String(capturedCount));
    } catch (e) {
      console.debug("[Suitest Recorder] Could not persist captured count:", e);
    }
    if (hudCounter) {
      hudCounter.textContent = `${capturedCount} action${capturedCount === 1 ? "" : "s"}`;
    }
  }

  async function sendViaNativeBridge(eventItem) {
    var rawRes = await window.__suitest_native_post_event__(JSON.stringify(eventItem));
    var res = rawRes;
    if (typeof res === "string") {
      try {
        res = JSON.parse(res);
      } catch (err) {
        console.debug("[Suitest Recorder] Native res JSON parse failed:", err);
      }
    }
    updateCapturedCount(res && typeof res.count === "number" ? res.count : null);
    if (hudLastAction) {
      hudLastAction.textContent = formatActionPreview(eventItem);
    }
    return true;
  }

  async function sendViaHttpFetch(eventItem) {
    var query = workspaceId ? `?workspaceId=${encodeURIComponent(workspaceId)}` : "";
    var url = `${apiBase}/generators/recorder/sessions/${encodeURIComponent(sessionId)}/events${query}`;
    var headers = { "Content-Type": "application/json" };
    if (workspaceId) {
      headers["X-Workspace-Id"] = workspaceId;
    }

    var res = await fetch(url, {
      method: "POST",
      headers: headers,
      credentials: "omit",
      keepalive: true,
      body: JSON.stringify(eventItem),
    });

    if (!res.ok) {
      console.error("[Suitest Recorder] Failed to send event:", res.status, await res.text());
      return false;
    }

    var data = null;
    try {
      data = await res.json();
    } catch (e) {
      console.debug("[Suitest Recorder] Response is not JSON:", e);
    }
    updateCapturedCount(data && typeof data.count === "number" ? data.count : null);
    if (hudLastAction) {
      hudLastAction.textContent = formatActionPreview(eventItem);
    }
    return true;
  }

  async function processQueue() {
    if (isSending || eventQueue.length === 0) return;
    isSending = true;

    var current = eventQueue.shift();
    try {
      if (typeof window.__suitest_native_post_event__ === "function") {
        try {
          await sendViaNativeBridge(current);
          return;
        } catch (nativeErr) {
          console.debug("[Suitest Recorder] Native bridge call failed, falling back to fetch:", nativeErr);
        }
      }
      await sendViaHttpFetch(current);
    } catch (err) {
      console.error("[Suitest Recorder] Error sending event:", err);
    } finally {
      isSending = false;
      if (eventQueue.length > 0) {
        setTimeout(processQueue, 40);
      }
    }
  }

  function formatActionPreview(evt) {
    if (evt.kind === "navigate") return `Navigate → ${evt.url}`;
    if (evt.kind === "click") return `Click → ${evt.selector}`;
    if (evt.kind === "type") return `Type → ${evt.selector} (${evt.masked ? "••••••" : evt.text})`;
    return evt.kind;
  }

  // 5. Typing Debounce and Immediate Flush
  var typingTimer = null;
  var lastValueMap = new WeakMap();
  var pendingTypingTarget = null;
  var pendingTypingSelector = "";
  var pendingTypingMasked = false;

  function flushTyping() {
    if (typingTimer) {
      clearTimeout(typingTimer);
      typingTimer = null;
    }
    if (!pendingTypingTarget) return;

    var target = pendingTypingTarget;
    var val = target.value;
    if (lastValueMap.get(target) !== val) {
      lastValueMap.set(target, val);
      postEvent({
        kind: "type",
        timestamp: new Date().toISOString(),
        selector: pendingTypingSelector || getSelector(target),
        text: val,
        masked: pendingTypingMasked,
        url: getCurrentVirtualUrl(),
      });
    }
    pendingTypingTarget = null;
  }

  // 6. Navigation Interception for /browse mode
  function setupNavigationInterception() {
    if (!isInBrowseMode()) return;

    // Wrap Location.prototype.assign and replace so scripted redirects stay in proxy
    try {
      if (window.Location && window.Location.prototype) {
        var origAssign = window.Location.prototype.assign;
        if (typeof origAssign === "function") {
          window.Location.prototype.assign = function (dest) {
            return origAssign.call(this, getBrowseProxyUrl(dest));
          };
        }
        var origReplace = window.Location.prototype.replace;
        if (typeof origReplace === "function") {
          window.Location.prototype.replace = function (dest) {
            return origReplace.call(this, getBrowseProxyUrl(dest));
          };
        }
      }
    } catch (e) {
      console.debug("[Suitest Recorder] Location patch not permitted by browser:", e);
    }

    // Wrap window.open
    try {
      var origOpen = window.open;
      window.open = function (url, target, features) {
        if (url && typeof url === "string" && !url.startsWith("javascript:") && !url.startsWith("#")) {
          var proxied = getBrowseProxyUrl(url);
          return origOpen.call(window, proxied, target, features);
        }
        return origOpen.apply(window, arguments);
      };
    } catch (e) {
      console.debug("[Suitest Recorder] window.open patch failed:", e);
    }
  }

  // 7. DOM Listeners
  function initListeners() {
    setupNavigationInterception();

    function sendPendingItem(destUrl, item) {
      try {
        if (navigator.sendBeacon) {
          var blob = new Blob([JSON.stringify(item)], { type: "application/json" });
          navigator.sendBeacon(destUrl, blob);
        } else {
          fetch(destUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(item),
            keepalive: true,
          }).catch(function (err) {
            console.debug("[Suitest Recorder] Beacon fetch error:", err);
          });
        }
      } catch (e) {
        console.debug("[Suitest Recorder] Beacon send failed:", e);
      }
    }

    // Flush typing before unload or pagehide
    function flushBeforeUnload() {
      flushTyping();
      if (eventQueue.length === 0) return;
      var item = eventQueue.shift();
      eventQueue.length = 0;
      if (typeof window.__suitest_native_post_event__ === "function") {
        try {
          window.__suitest_native_post_event__(JSON.stringify(item));
          return;
        } catch (e) {
          console.debug("[Suitest Recorder] Native bridge flush error:", e);
        }
      }
      var query = workspaceId ? `?workspaceId=${encodeURIComponent(workspaceId)}` : "";
      var destUrl = `${apiBase}/generators/recorder/sessions/${encodeURIComponent(sessionId)}/events${query}`;
      sendPendingItem(destUrl, item);
    }

    window.addEventListener("beforeunload", flushBeforeUnload);
    window.addEventListener("pagehide", flushBeforeUnload);

    // Enter key submits or commits typing immediately
    document.addEventListener(
      "keydown",
      function (e) {
        if (e.key === "Enter") {
          flushTyping();
        }
      },
      true
    );

    // Form submission
    document.addEventListener(
      "submit",
      function (e) {
        var form = e.target;
        if (!form) return;

        flushTyping();

        var action = form.action || getCurrentVirtualUrl();

        if (isInBrowseMode()) {
          var method = (form.method || "GET").toUpperCase();
          if (method === "GET") {
            e.preventDefault();
            e.stopPropagation();
            try {
              var formUrl = new URL(action, getCurrentVirtualUrl());
              var formData = new FormData(form);
              for (var pair of formData.entries()) {
                formUrl.searchParams.append(pair[0], pair[1]);
              }
              window.location.href = getBrowseProxyUrl(formUrl.toString());
            } catch (err) {
              console.debug("[Suitest Recorder] Failed to rewrite GET form submission:", err);
            }
          } else {
            // For POST: rewrite form action to the browse proxy endpoint
            try {
              form.action = getBrowseProxyUrl(action);
            } catch (err) {
              console.debug("[Suitest Recorder] Failed to rewrite POST form action:", err);
            }
          }
        }
      },
      true
    );

    // Clicks
    document.addEventListener(
      "click",
      function (e) {
        var target = e.target;
        if (!target) return;

        // Skip clicks on our own HUD
        if (hudContainer && (target === hudContainer || hudContainer.contains(target))) {
          return;
        }

        flushTyping();
        if (eventQueue.length > 0) {
          processQueue();
        }

        // Avoid capturing redundant focus-clicks on typable text/password inputs that user clicks to type
        var tag = (target.tagName || "").toLowerCase();
        var isTypableInput =
          (tag === "input" && !/^(button|submit|reset|checkbox|radio|file|image)$/i.test(target.type || "")) ||
          tag === "textarea";
        if (isTypableInput) {
          return;
        }

        var selector = getSelector(target);
        var now = new Date().toISOString();
        var currentUrl = getCurrentVirtualUrl();

        postEvent({
          kind: "click",
          timestamp: now,
          selector: selector,
          url: currentUrl,
        });

        // If in browse proxy mode and user clicks an <a> tag, route through the proxy
        if (isInBrowseMode()) {
          var anchor = target.closest("a");
          if (anchor) {
            var rawHref = anchor.getAttribute("href") || "";
            if (
              rawHref &&
              !rawHref.startsWith("#") &&
              !rawHref.startsWith("javascript:") &&
              !anchor.getAttribute("target")?.includes("_blank")
            ) {
              e.preventDefault();
              e.stopPropagation();
              window.location.href = getBrowseProxyUrl(anchor.href);
            }
          }
        }
      },
      true
    );

    // Input events (continuous typing)
    document.addEventListener(
      "input",
      function (e) {
        var target = e.target;
        if (!target || !("value" in target)) return;
        if (hudContainer && (target === hudContainer || hudContainer.contains(target))) return;

        clearTimeout(typingTimer);
        pendingTypingTarget = target;
        pendingTypingSelector = getSelector(target);
        pendingTypingMasked = target.type === "password" || target.getAttribute("autocomplete") === "current-password";

        var val = target.value;

        // Debounce continuous typing so we send coalesced value after typing pauses
        typingTimer = setTimeout(function () {
          flushTyping();
        }, 1000);
      },
      true
    );

    // On blur / change commit immediately
    document.addEventListener(
      "change",
      function (e) {
        var target = e.target;
        if (!target || !("value" in target)) return;
        if (hudContainer && (target === hudContainer || hudContainer.contains(target))) return;

        flushTyping();
      },
      true
    );

    // Listen for SPA navigation (pushState, replaceState, popstate, hashchange)
    var lastRecordedUrl = getCurrentVirtualUrl();
    function checkUrlChange() {
      var current = getCurrentVirtualUrl();
      if (current !== lastRecordedUrl) {
        lastRecordedUrl = current;
        postEvent({
          kind: "navigate",
          timestamp: new Date().toISOString(),
          url: current,
        });
      }
    }

    window.addEventListener("popstate", checkUrlChange);
    window.addEventListener("hashchange", checkUrlChange);

    window.addEventListener("beforeunload", function () {
      if (window.__SUITEST_BROWSE_ORIGINAL_URL__) {
        try {
          window.history.replaceState(null, "", window.__SUITEST_BROWSE_ORIGINAL_URL__);
        } catch (err) {
          console.debug("[Suitest Recorder] Failed to restore browse URL on beforeunload:", err);
        }
      }
    });

    var origPushState = history.pushState;
    if (origPushState) {
      history.pushState = function () {
        var ret = origPushState.apply(this, arguments);
        setTimeout(checkUrlChange, 80);
        return ret;
      };
    }

    var origReplaceState = history.replaceState;
    if (origReplaceState) {
      history.replaceState = function () {
        var ret = origReplaceState.apply(this, arguments);
        setTimeout(checkUrlChange, 80);
        return ret;
      };
    }
  }

  // 8. Initialize on DOM Ready
  function start() {
    createHUD();
    initListeners();

    // Emit initial navigate event
    postEvent({
      kind: "navigate",
      timestamp: new Date().toISOString(),
      url: getCurrentVirtualUrl(),
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
