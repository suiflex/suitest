/**
 * Suitest Web Recorder Agent
 * Injected into target web pages to capture user interactions (navigate, click, type)
 * and stream them in real-time to Suitest recorder sessions.
 */
(function () {
  // Track whether recorder is running in top-level window or nested subframe (iframe)
  var isSubframe = window !== window.top;
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

  // Restore session information from sessionStorage if previously persisted
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

  // Restore action count and captured steps across navigations
  var capturedCount = 0;
  var capturedSteps = [];
  var hasUserEditedSteps = false;
  try {
    hasUserEditedSteps = sessionStorage.getItem("__suitest_user_edited__") === "true";
  } catch (e) {
    console.debug("[Suitest Recorder] Could not restore user edited state:", e);
  }
  try {
    var storedCount = sessionStorage.getItem("__suitest_captured_count__");
    if (storedCount) {
      capturedCount = parseInt(storedCount, 10) || 0;
    }
  } catch (e) {
    console.debug("[Suitest Recorder] Could not restore captured count from sessionStorage:", e);
  }

  try {
    var storedSteps = sessionStorage.getItem("__suitest_captured_steps__");
    if (storedSteps) {
      capturedSteps = JSON.parse(storedSteps) || [];
      if (capturedSteps.length > capturedCount) {
        capturedCount = capturedSteps.length;
      }
    }
  } catch (e) {
    console.debug("[Suitest Recorder] Could not restore captured steps from sessionStorage:", e);
  }

  var isStepsPanelOpen = true;
  try {
    var storedOpen = sessionStorage.getItem("__suitest_hud_steps_open__");
    if (storedOpen !== null) {
      isStepsPanelOpen = storedOpen === "true";
    }
  } catch (e) {
    console.debug("[Suitest Recorder] Could not restore steps open state:", e);
  }

  // Pause/Resume recording state across navigations
  var isPaused = false;
  try {
    var storedPause = sessionStorage.getItem("__suitest_recorder_paused__");
    isPaused = storedPause === "true";
  } catch (e) {
    console.debug("[Suitest Recorder] Could not read pause state:", e);
  }

  var eventQueue = [];
  var isSending = false;
  var lastHudInteractionTime = 0;

  function getCurrentVirtualUrl() {
    return window.location.href;
  }

  function getCleanElementText(element) {
    if (!element) return "";
    try {
      var clone = element.cloneNode(true);
      var badges = clone.querySelectorAll(
        '.badge, .pill, .chip, .tag, [class*="badge"], [class*="chip"], [class*="tag"], svg, style, script'
      );
      for (var i = 0; i < badges.length; i++) {
        badges[i].remove();
      }
      return (clone.innerText || clone.textContent || "").trim().replace(/\s+/g, " ");
    } catch (e) {
      return (element.innerText || element.textContent || "").trim().replace(/\s+/g, " ");
    }
  }

  function getSingleFrameSelector(win) {
    if (!win) return "iframe";
    try {
      if (win.frameElement) {
        var fe = win.frameElement;
        if (fe.id && !/^[0-9]|^ember|^react-|^vue-|:[a-z0-9]+:/i.test(fe.id)) {
          return `iframe#${CSS.escape(fe.id)}`;
        }
        var dt = fe.getAttribute("data-testid") || fe.getAttribute("data-test");
        if (dt) {
          return `iframe[data-testid="${dt}"]`;
        }
        var name = fe.getAttribute("name");
        if (name) {
          return `iframe[name="${name}"]`;
        }
        var src = fe.getAttribute("src");
        if (src && !src.startsWith("about:") && !src.startsWith("javascript:")) {
          return `iframe[src*="${src.replace(/"/g, '\\"')}"]`;
        }
        if (fe.ownerDocument) {
          var iframes = Array.from(fe.ownerDocument.querySelectorAll("iframe"));
          var idx = iframes.indexOf(fe);
          if (idx >= 0) {
            return `iframe >> nth=${idx}`;
          }
        }
      }
    } catch (e) {
      console.debug("[Suitest Recorder] FrameElement access denied:", e);
    }

    if (win.name) {
      return `iframe[name="${win.name}"]`;
    }
    try {
      if (win.location && win.location.pathname && win.location.pathname !== "/" && win.location.pathname !== "blank") {
        return `iframe[src*="${win.location.pathname}"]`;
      }
    } catch (e) {
      console.debug("[Suitest Recorder] Location pathname access error:", e);
    }

    return "iframe";
  }

  function getFrameSelector() {
    if (!isSubframe) return null;
    var chain = [];
    var curr = window;
    var depth = 0;
    while (curr && curr !== window.top && depth < 10) {
      depth++;
      var sel = getSingleFrameSelector(curr);
      chain.unshift(sel);
      try {
        if (!curr.parent || curr.parent === curr) {
          break;
        }
        curr = curr.parent;
      } catch (e) {
        console.debug("[Suitest Recorder] Cannot access parent window in chain:", e);
        break;
      }
    }
    return chain.length > 0 ? chain.join(" >>> ") : null;
  }

  // 2. Resilient Selector Engine
  function getSelector(el) {
    if (!el || el === document.body || el === document.documentElement) {
      return "body";
    }

    // Interactive element uplift: if target is a child of button, link, menu item, or dropdown option, uplift to that container
    if (el.closest) {
      var interactiveParent = el.closest(
        'a, button, [role="button"], [role="menuitem"], [role="option"], [role="tab"], [role="combobox"]'
      );
      if (interactiveParent && interactiveParent !== el) {
        el = interactiveParent;
      }
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

    var tag = el.tagName.toLowerCase();

    // Priority 3: Links with clean href (super stable for menus/submenus)
    if (tag === "a") {
      var rawHref = el.getAttribute("href") || "";
      if (
        rawHref &&
        !rawHref.startsWith("#") &&
        !rawHref.startsWith("javascript:") &&
        !rawHref.startsWith("data:")
      ) {
        var hrefSel = `a[href="${rawHref.replace(/"/g, '\\"')}"]`;
        if (document.querySelectorAll(hrefSel).length === 1) {
          return hrefSel;
        }
      }
    }

    // Priority 4: Form name or input placeholder
    if (el.getAttribute("name")) {
      return `${tag}[name="${el.getAttribute("name")}"]`;
    }
    if (el.getAttribute("placeholder")) {
      return `${tag}[placeholder="${el.getAttribute("placeholder")}"]`;
    }

    // Priority 5: ARIA role with clean text (combobox, option, menuitem, tab)
    var role = el.getAttribute("role");
    if (role && (role === "option" || role === "menuitem" || role === "tab" || role === "button")) {
      var roleText = getCleanElementText(el);
      if (roleText && roleText.length > 0 && roleText.length <= 40) {
        var roleSel = `[role="${role}"]:has-text("${roleText.replace(/"/g, '\\"')}")`;
        if (document.querySelectorAll(roleSel).length === 1) {
          return roleSel;
        }
      }
    }

    // Priority 6: List items in dropdowns/menus
    if (tag === "li") {
      var liText = getCleanElementText(el);
      if (liText && liText.length > 0 && liText.length <= 40) {
        var liSel = `li:has-text("${liText.replace(/"/g, '\\"')}")`;
        if (document.querySelectorAll(liSel).length === 1) {
          return liSel;
        }
      }
    }

    // Priority 7: Button or link text content (cleaned of badge noise)
    if (tag === "button" || tag === "a") {
      var cleanText = getCleanElementText(el);
      if (cleanText.length > 0 && cleanText.length <= 35) {
        var textSel = `${tag}:has-text("${cleanText.replace(/"/g, '\\"')}")`;
        if (document.querySelectorAll(textSel).length === 1) {
          return textSel;
        }
      }
    }

    // Priority 8: aria-label or role
    if (el.getAttribute("aria-label")) {
      return `[aria-label="${el.getAttribute("aria-label")}"]`;
    }
    if (el.getAttribute("role")) {
      return `[role="${el.getAttribute("role")}"]`;
    }

    // Priority 9: Concise class or hierarchical path
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
  var hudAlertNotice = null;
  var hudStepsDrawer = null;
  var hudStepsList = null;
  var hudDrawerTitle = null;
  var isAssertMode = false;
  var pickerOverlay = null;
  var assertPopover = null;
  var pendingAlert = { el: null, text: "" };
  var editingStepIdx = null;
  var editDraft = null;
  var lastUserInteractionTime = 0;

  function toDynamicVariableTemplate(val) {
    var v = (val || "").trim();
    if (v.includes("@")) {
      return "{{email}}";
    }
    if (/^\+?\d{8,15}$/.test(v.replace(/[\s-]/g, ""))) {
      return "{{phone}}";
    }
    if (/^[a-zA-Z0-9_-]+$/.test(v) && v.length < 24) {
      return "{{" + v.toLowerCase().replace(/[^a-z0-9_]/g, "_") + "}}";
    }
    return "{{variable}}";
  }

  function syncCleanedStepsToServer(steps) {
    if (!sessionId) return;
    if (typeof window.__suitest_native_post_event__ === "function") {
      window.__suitest_native_post_event__(JSON.stringify({
        action: "sync_events",
        sessionId: sessionId,
        workspaceId: workspaceId,
        events: steps,
      })).catch(function (err) {
        console.debug("[Suitest Recorder] Native sync_events failed, fallback to HTTP:", err);
        httpSync();
      });
    } else {
      httpSync();
    }

    function httpSync() {
      var query = workspaceId ? "?workspaceId=" + encodeURIComponent(workspaceId) : "";
      var url = apiBase + "/generators/recorder/sessions/" + encodeURIComponent(sessionId) + "/sync" + query;
      var headers = { "Content-Type": "application/json" };
      if (workspaceId) headers["X-Workspace-Id"] = workspaceId;
      fetch(url, {
        method: "PUT",
        headers: headers,
        credentials: "omit",
        body: JSON.stringify({ events: steps }),
      }).catch(function (e) {
        console.debug("[Suitest Recorder] HTTP sync failed:", e);
      });
    }
  }

  function saveStepEdit(idx, updated) {
    if (idx < 0 || idx >= capturedSteps.length) return;
    capturedSteps[idx] = updated;
    editingStepIdx = null;
    editDraft = null;
    hasUserEditedSteps = true;
    try {
      sessionStorage.setItem("__suitest_captured_steps__", JSON.stringify(capturedSteps));
      sessionStorage.setItem("__suitest_user_edited__", "true");
    } catch (e) {
      console.debug("[Suitest Recorder] Failed to persist edited step:", e);
    }
    renderStepsList();
    syncCleanedStepsToServer(capturedSteps);
  }

  function deleteStep(idx) {
    if (idx < 0 || idx >= capturedSteps.length) return;
    capturedSteps.splice(idx, 1);
    capturedCount = capturedSteps.length;
    hasUserEditedSteps = true;
    if (editingStepIdx === idx) {
      editingStepIdx = null;
      editDraft = null;
    } else if (editingStepIdx !== null && editingStepIdx > idx) {
      editingStepIdx--;
    }
    try {
      sessionStorage.setItem("__suitest_captured_steps__", JSON.stringify(capturedSteps));
      sessionStorage.setItem("__suitest_captured_count__", String(capturedCount));
      sessionStorage.setItem("__suitest_user_edited__", "true");
    } catch (e) {
      console.debug("[Suitest Recorder] Failed to persist deleted step:", e);
    }
    updateCounterDisplay();
    renderStepsList();
    syncCleanedStepsToServer(capturedSteps);
  }

  function moveStep(idx, direction) {
    var target = direction === "up" ? idx - 1 : idx + 1;
    if (target < 0 || target >= capturedSteps.length) return;
    var tmp = capturedSteps[idx];
    capturedSteps[idx] = capturedSteps[target];
    capturedSteps[target] = tmp;
    hasUserEditedSteps = true;
    if (editingStepIdx === idx) {
      editingStepIdx = target;
    } else if (editingStepIdx === target) {
      editingStepIdx = idx;
    }
    try {
      sessionStorage.setItem("__suitest_captured_steps__", JSON.stringify(capturedSteps));
      sessionStorage.setItem("__suitest_user_edited__", "true");
    } catch (e) {
      console.debug("[Suitest Recorder] Failed to persist moved step:", e);
    }
    renderStepsList();
    syncCleanedStepsToServer(capturedSteps);
  }

  function cleanNoise() {
    if (capturedSteps.length <= 1) return;
    var cleaned = [];
    for (var i = 0; i < capturedSteps.length; i++) {
      var curr = capturedSteps[i];
      if (!curr) continue;

      // Filter empty typing actions
      if (curr.kind === "type" && (!curr.text || curr.text.trim() === "")) {
        continue;
      }

      // Filter accidental clicks on root body or html
      if (curr.kind === "click" && (curr.selector === "body" || curr.selector === "html")) {
        continue;
      }

      var prev = cleaned[cleaned.length - 1];
      if (!prev) {
        cleaned.push(curr);
        continue;
      }

      // Filter duplicate consecutive navigate to same URL
      if (curr.kind === "navigate" && prev.kind === "navigate" && curr.url === prev.url) {
        continue;
      }

      // Filter consecutive rapid clicks on identical selector (< 200ms)
      if (
        curr.kind === "click" &&
        prev.kind === "click" &&
        curr.selector === prev.selector
      ) {
        if (curr.timestamp && prev.timestamp) {
          var diff = Math.abs(new Date(curr.timestamp).getTime() - new Date(prev.timestamp).getTime());
          if (diff < 200) continue;
        }
      }

      // Filter click on input immediately followed by type into same input
      if (prev.kind === "click" && curr.kind === "type" && prev.selector === curr.selector) {
        cleaned[cleaned.length - 1] = curr;
        continue;
      }

      cleaned.push(curr);
    }
    capturedSteps = cleaned;
    capturedCount = capturedSteps.length;
    editingStepIdx = null;
    editDraft = null;
    hasUserEditedSteps = true;
    try {
      sessionStorage.setItem("__suitest_captured_steps__", JSON.stringify(capturedSteps));
      sessionStorage.setItem("__suitest_captured_count__", String(capturedCount));
      sessionStorage.setItem("__suitest_user_edited__", "true");
    } catch (e) {
      console.debug("[Suitest Recorder] Failed to persist cleaned steps:", e);
    }
    updateCounterDisplay();
    renderStepsList();
    syncCleanedStepsToServer(capturedSteps);
  }

  function addManualStep() {
    var newStep = {
      kind: "click",
      selector: "",
      timestamp: new Date().toISOString(),
      url: getCurrentVirtualUrl(),
    };
    capturedSteps.push(newStep);
    capturedCount = capturedSteps.length;
    editingStepIdx = capturedSteps.length - 1;
    editDraft = JSON.parse(JSON.stringify(newStep));
    try {
      sessionStorage.setItem("__suitest_captured_steps__", JSON.stringify(capturedSteps));
      sessionStorage.setItem("__suitest_captured_count__", String(capturedCount));
    } catch (e) {
      console.debug("[Suitest Recorder] Failed to persist manual step:", e);
    }
    updateCounterDisplay();
    renderStepsList();
  }

  function updateCounterDisplay() {
    if (!hudCounter) return;
    var chevron = isStepsPanelOpen ? " ▴" : " ▾";
    if (isPaused) {
      hudCounter.textContent = "Paused (" + capturedCount + ")" + chevron;
    } else {
      hudCounter.textContent = capturedCount + " " + (capturedCount === 1 ? "step" : "steps") + chevron;
    }
  }

  function toggleStepsDrawer(forceState) {
    if (typeof forceState === "boolean") {
      isStepsPanelOpen = forceState;
    } else {
      isStepsPanelOpen = !isStepsPanelOpen;
    }
    try {
      sessionStorage.setItem("__suitest_hud_steps_open__", isStepsPanelOpen ? "true" : "false");
    } catch (err) {
      console.debug("[Suitest Recorder] Failed to store steps panel state:", err);
    }
    if (hudStepsDrawer) {
      hudStepsDrawer.style.display = isStepsPanelOpen ? "flex" : "none";
    }
    updateCounterDisplay();
  }

  function handleStepsListClick(e) {
    var target = e.target;
    var actionEl = target && target.closest ? target.closest("[data-recorder-action]") : null;
    if (!actionEl) return;
    e.stopPropagation();
    var action = actionEl.getAttribute("data-recorder-action");
    var idxStr = actionEl.getAttribute("data-index");
    var rawIdx = idxStr !== null ? parseInt(idxStr, 10) : -1;
    var idx = Number.isInteger(rawIdx) && rawIdx >= 0 && rawIdx < capturedSteps.length ? rawIdx : -1;

    if (action === "move-up" && idx > 0) {
      moveStep(idx, "up");
    } else if (action === "move-down" && idx >= 0) {
      moveStep(idx, "down");
    } else if (action === "edit" && idx >= 0) {
      editingStepIdx = idx;
      editDraft = JSON.parse(JSON.stringify(capturedSteps[idx]));
      renderStepsList();
    } else if (action === "delete" && idx >= 0) {
      deleteStep(idx);
    } else if (action === "cancel-edit") {
      editingStepIdx = null;
      editDraft = null;
      renderStepsList();
    } else if (action === "save-edit" && idx >= 0) {
      saveStepEdit(idx, editDraft);
    } else if (action === "make-var") {
      if (editDraft && editDraft.text) {
        editDraft.text = toDynamicVariableTemplate(editDraft.text);
        renderStepsList();
      }
    }
  }

  function handleStepsListChange(e) {
    var target = e.target;
    if (target && target.getAttribute("data-recorder-change") === "kind") {
      if (editDraft) {
        editDraft.kind = target.value;
        renderStepsList();
      }
    }
  }

  function renderStepsList() {
    if (!hudStepsList) return;
    hudStepsList.onclick = handleStepsListClick;
    hudStepsList.onchange = handleStepsListChange;
    hudStepsList.innerHTML = "";

    if (hudDrawerTitle) {
      hudDrawerTitle.textContent = "CAPTURED STEPS (" + capturedSteps.length + ")";
    }

    var cleanBtn = document.getElementById("suitest-hud-clean-noise");
    if (cleanBtn) {
      cleanBtn.style.display = capturedSteps.length > 1 ? "inline-block" : "none";
    }

    if (capturedSteps.length === 0) {
      var emptyDiv = document.createElement("div");
      emptyDiv.style.cssText = "color: #64748b; font-size: 10.5px; text-align: center; padding: 14px 4px; font-style: italic;";
      emptyDiv.innerHTML = "No actions recorded yet.<br>Click or type on the page to record steps.";
      hudStepsList.appendChild(emptyDiv);
      return;
    }

    var kindColors = {
      navigate: { bg: "rgba(34, 211, 238, 0.12)", text: "#22d3ee", border: "rgba(34, 211, 238, 0.25)" },
      click: { bg: "rgba(52, 211, 153, 0.12)", text: "#34d399", border: "rgba(52, 211, 153, 0.25)" },
      type: { bg: "rgba(251, 191, 36, 0.12)", text: "#fbbf24", border: "rgba(251, 191, 36, 0.25)" },
      select: { bg: "rgba(56, 189, 248, 0.12)", text: "#38bdf8", border: "rgba(56, 189, 248, 0.25)" },
      upload: { bg: "rgba(244, 114, 182, 0.12)", text: "#f472b6", border: "rgba(244, 114, 182, 0.25)" },
      assert: { bg: "rgba(192, 132, 252, 0.12)", text: "#c084fc", border: "rgba(192, 132, 252, 0.25)" },
    };

    capturedSteps.forEach(function (step, idx) {
      if (editingStepIdx === idx && editDraft) {
        var editCard = document.createElement("div");
        editCard.style.cssText = [
          "display: flex",
          "flex-direction: column",
          "gap: 6px",
          "background: rgba(30, 41, 59, 0.95)",
          "border: 1px solid rgba(99, 102, 241, 0.45)",
          "border-radius: 6px",
          "padding: 8px",
          "font-size: 11px",
          "color: #f1f5f9",
        ].join(";");

        var cardHead = document.createElement("div");
        cardHead.style.cssText = "display: flex; align-items: center; justify-content: space-between;";

        var stepNumLabel = document.createElement("span");
        stepNumLabel.style.cssText = "font-weight: 600; font-family: monospace; color: #818cf8; font-size: 11px;";
        stepNumLabel.textContent = "Step " + (idx + 1);

        var kindSel = document.createElement("select");
        kindSel.style.cssText = "background: #0f172a; border: 1px solid #334155; color: #f8fafc; font-family: monospace; font-size: 10px; border-radius: 4px; padding: 2px 4px;";
        var kinds = ["navigate", "click", "type", "select", "upload", "assert"];
        kinds.forEach(function (kd) {
          var opt = document.createElement("option");
          opt.value = kd;
          opt.textContent = kd.toUpperCase();
          if (kd === editDraft.kind) opt.selected = true;
          kindSel.appendChild(opt);
        });
        kindSel.setAttribute("data-recorder-change", "kind");

        cardHead.appendChild(stepNumLabel);
        cardHead.appendChild(kindSel);
        editCard.appendChild(cardHead);

        if (editDraft.kind === "navigate") {
          var uDiv = document.createElement("div");
          uDiv.style.cssText = "display: flex; flex-direction: column; gap: 2px;";
          var uLbl = document.createElement("span");
          uLbl.style.cssText = "font-size: 10px; color: #94a3b8;";
          uLbl.textContent = "Target URL";
          var uInp = document.createElement("input");
          uInp.type = "text";
          uInp.value = editDraft.url || "";
          uInp.style.cssText = "background: #0f172a; border: 1px solid #334155; color: #f8fafc; font-size: 11px; padding: 3px 6px; border-radius: 4px;";
          uInp.oninput = function (e) { editDraft.url = e.target.value; };
          uDiv.appendChild(uLbl);
          uDiv.appendChild(uInp);
          editCard.appendChild(uDiv);
        }

        if (editDraft.kind !== "navigate") {
          var sDiv = document.createElement("div");
          sDiv.style.cssText = "display: flex; flex-direction: column; gap: 2px;";
          var sLbl = document.createElement("span");
          sLbl.style.cssText = "font-size: 10px; color: #94a3b8;";
          sLbl.textContent = "Selector";
          var sInp = document.createElement("input");
          sInp.type = "text";
          sInp.value = editDraft.selector || "";
          sInp.placeholder = 'e.g. button#submit or [name="email"]';
          sInp.style.cssText = "background: #0f172a; border: 1px solid #334155; color: #f8fafc; font-family: monospace; font-size: 10.5px; padding: 3px 6px; border-radius: 4px;";
          sInp.oninput = function (e) { editDraft.selector = e.target.value; };
          sDiv.appendChild(sLbl);
          sDiv.appendChild(sInp);
          editCard.appendChild(sDiv);
        }

        if (editDraft.kind === "type") {
          var tDiv = document.createElement("div");
          tDiv.style.cssText = "display: flex; flex-direction: column; gap: 2px;";
          var tHead = document.createElement("div");
          tHead.style.cssText = "display: flex; align-items: center; justify-content: space-between;";
          var tLbl = document.createElement("span");
          tLbl.style.cssText = "font-size: 10px; color: #94a3b8;";
          tLbl.textContent = "Value / Text";

          var varBtn = document.createElement("button");
          varBtn.type = "button";
          varBtn.style.cssText = "background: none; border: none; color: #818cf8; font-size: 10px; cursor: pointer; text-decoration: underline;";
          varBtn.textContent = "Make variable";
          varBtn.setAttribute("data-recorder-action", "make-var");
          tHead.appendChild(tLbl);
          tHead.appendChild(varBtn);

          var tInp = document.createElement("input");
          tInp.type = "text";
          tInp.value = editDraft.text || "";
          tInp.style.cssText = "background: #0f172a; border: 1px solid #334155; color: #f8fafc; font-size: 11px; padding: 3px 6px; border-radius: 4px;";
          tInp.oninput = function (e) { editDraft.text = e.target.value; };

          var mLabel = document.createElement("label");
          mLabel.style.cssText = "display: flex; align-items: center; gap: 4px; font-size: 10px; color: #94a3b8; cursor: pointer; margin-top: 2px;";
          var mCheck = document.createElement("input");
          mCheck.type = "checkbox";
          mCheck.checked = Boolean(editDraft.masked);
          mCheck.onchange = function (e) { editDraft.masked = e.target.checked; };
          var mSpan = document.createElement("span");
          mSpan.textContent = "Mask secret ({{password}})";
          mLabel.appendChild(mCheck);
          mLabel.appendChild(mSpan);

          tDiv.appendChild(tHead);
          tDiv.appendChild(tInp);
          tDiv.appendChild(mLabel);
          editCard.appendChild(tDiv);
        }

        if (editDraft.kind === "assert") {
          var aDiv = document.createElement("div");
          aDiv.style.cssText = "display: flex; flex-direction: column; gap: 2px;";
          var aLbl = document.createElement("span");
          aLbl.style.cssText = "font-size: 10px; color: #94a3b8;";
          aLbl.textContent = "Expected Condition / Text";
          var aInp = document.createElement("input");
          aInp.type = "text";
          aInp.value = (editDraft.assertion && editDraft.assertion.expected) || editDraft.text || "";
          aInp.style.cssText = "background: #0f172a; border: 1px solid #334155; color: #f8fafc; font-size: 11px; padding: 3px 6px; border-radius: 4px;";
          aInp.oninput = function (e) {
            if (!editDraft.assertion) editDraft.assertion = {};
            editDraft.assertion.expected = e.target.value;
            editDraft.text = e.target.value;
          };
          aDiv.appendChild(aLbl);
          aDiv.appendChild(aInp);
          editCard.appendChild(aDiv);
        }

        var bRow = document.createElement("div");
        bRow.style.cssText = "display: flex; align-items: center; justify-content: flex-end; gap: 5px; margin-top: 4px;";

        var cBtn = document.createElement("button");
        cBtn.type = "button";
        cBtn.style.cssText = "background: none; border: 1px solid #334155; color: #94a3b8; font-size: 10px; padding: 2px 7px; border-radius: 4px; cursor: pointer;";
        cBtn.textContent = "Cancel";
        cBtn.setAttribute("data-recorder-action", "cancel-edit");

        var sBtn = document.createElement("button");
        sBtn.type = "button";
        sBtn.style.cssText = "background: #4f46e5; border: 1px solid #6366f1; color: #ffffff; font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 4px; cursor: pointer;";
        sBtn.textContent = "Save";
        sBtn.setAttribute("data-recorder-action", "save-edit");
        sBtn.setAttribute("data-index", String(idx));

        bRow.appendChild(cBtn);
        bRow.appendChild(sBtn);
        editCard.appendChild(bRow);

        hudStepsList.appendChild(editCard);
        return;
      }

      var row = document.createElement("div");
      row.style.cssText = [
        "display: flex",
        "align-items: center",
        "justify-content: space-between",
        "gap: 6px",
        "padding: 3px 6px",
        "border-radius: 4px",
        "background: rgba(255, 255, 255, 0.03)",
        "border: 1px solid rgba(255, 255, 255, 0.06)",
        "font-size: 11px",
        "transition: background 0.15s ease",
      ].join(";");

      var leftDiv = document.createElement("div");
      leftDiv.style.cssText = "display: flex; align-items: center; gap: 6px; min-width: 0; flex: 1;";

      var num = document.createElement("span");
      num.style.cssText = "color: #64748b; font-size: 10px; font-weight: 600; font-family: monospace; min-width: 14px; text-align: right;";
      num.textContent = (idx + 1);

      var k = (step.kind || "").toLowerCase();
      var col = kindColors[k] || { bg: "rgba(148, 163, 184, 0.12)", text: "#94a3b8", border: "rgba(148, 163, 184, 0.25)" };

      var badge = document.createElement("span");
      badge.style.cssText = [
        "background: " + col.bg,
        "color: " + col.text,
        "border: 1px solid " + col.border,
        "font-size: 9px",
        "font-weight: 700",
        "padding: 1px 4px",
        "border-radius: 3px",
        "letter-spacing: 0.03em",
        "text-transform: uppercase",
        "flex-shrink: 0",
      ].join(";");
      badge.textContent = k === "navigate" ? "NAV" : k;

      var desc = document.createElement("span");
      desc.style.cssText = [
        "overflow: hidden",
        "text-overflow: ellipsis",
        "white-space: nowrap",
        "color: #cbd5e1",
        "font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
        "font-size: 10.5px",
        "flex: 1",
      ].join(";");

      var label = "";
      if (k === "click") {
        label = step.selector || "element";
      } else if (k === "type") {
        label = (step.selector || "input") + " = " + (step.masked ? "••••••" : (step.text || ""));
      } else if (k === "navigate") {
        label = step.url || "";
      } else if (k === "assert") {
        label = (step.assertion && (step.assertion.description || step.assertion.expected)) || step.selector || "condition";
      } else if (k === "select") {
        label = (step.selector || "select") + " → " + ((step.assertion && step.assertion.label) || step.text || "");
      } else if (k === "upload") {
        label = (step.selector || "upload") + " ← " + (step.text || "file");
      } else {
        label = step.selector || step.text || k;
      }
      desc.textContent = label;
      desc.title = label + (step.selector && step.selector !== label ? " (" + step.selector + ")" : "");

      leftDiv.appendChild(num);
      leftDiv.appendChild(badge);
      if (step.frame_selector) {
        var frameBadge = document.createElement("span");
        frameBadge.style.cssText = [
          "background: rgba(168, 85, 247, 0.15)",
          "color: #c084fc",
          "border: 1px solid rgba(168, 85, 247, 0.3)",
          "font-size: 8.5px",
          "font-weight: 600",
          "padding: 0 4px",
          "border-radius: 3px",
          "flex-shrink: 0",
        ].join(";");
        frameBadge.textContent = "IFRAME";
        frameBadge.title = "Target inside frame: " + step.frame_selector;
        leftDiv.appendChild(frameBadge);
      }
      leftDiv.appendChild(desc);
      row.appendChild(leftDiv);

      var actionsDiv = document.createElement("div");
      actionsDiv.style.cssText = "display: flex; align-items: center; gap: 2px; flex-shrink: 0; opacity: 0.65;";
      row.onmouseenter = function () { actionsDiv.style.opacity = "1"; };
      row.onmouseleave = function () { actionsDiv.style.opacity = "0.65"; };

      if (idx > 0) {
        var upBtn = document.createElement("button");
        upBtn.type = "button";
        upBtn.style.cssText = "background: none; border: none; color: #94a3b8; font-size: 9px; cursor: pointer; padding: 1px 3px; border-radius: 3px;";
        upBtn.textContent = "↑";
        upBtn.title = "Move up";
        upBtn.setAttribute("data-recorder-action", "move-up");
        upBtn.setAttribute("data-index", String(idx));
        actionsDiv.appendChild(upBtn);
      }

      if (idx < capturedSteps.length - 1) {
        var dnBtn = document.createElement("button");
        dnBtn.type = "button";
        dnBtn.style.cssText = "background: none; border: none; color: #94a3b8; font-size: 9px; cursor: pointer; padding: 1px 3px; border-radius: 3px;";
        dnBtn.textContent = "↓";
        dnBtn.title = "Move down";
        dnBtn.setAttribute("data-recorder-action", "move-down");
        dnBtn.setAttribute("data-index", String(idx));
        actionsDiv.appendChild(dnBtn);
      }

      var eBtn = document.createElement("button");
      eBtn.type = "button";
      eBtn.style.cssText = "background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); color: #cbd5e1; font-size: 9.5px; cursor: pointer; padding: 1px 4px; border-radius: 3px;";
      eBtn.textContent = "Edit";
      eBtn.title = "Edit step";
      eBtn.setAttribute("data-recorder-action", "edit");
      eBtn.setAttribute("data-index", String(idx));
      actionsDiv.appendChild(eBtn);

      var dBtn = document.createElement("button");
      dBtn.type = "button";
      dBtn.style.cssText = "background: none; border: none; color: #f87171; font-size: 11px; cursor: pointer; padding: 1px 3px; border-radius: 3px;";
      dBtn.textContent = "✕";
      dBtn.title = "Delete step";
      dBtn.setAttribute("data-recorder-action", "delete");
      dBtn.setAttribute("data-index", String(idx));
      actionsDiv.appendChild(dBtn);

      row.appendChild(actionsDiv);
      hudStepsList.appendChild(row);
    });

    if (editingStepIdx === null) {
      hudStepsList.scrollTop = hudStepsList.scrollHeight;
    }
  }

  function handleIncomingIframeEvent(evt) {
    if (isPaused || !evt || !evt.kind) return;
    var alreadyExists = capturedSteps.some(function (st) {
      return (
        st.timestamp === evt.timestamp &&
        st.kind === evt.kind &&
        st.selector === evt.selector &&
        st.frame_selector === evt.frame_selector
      );
    });
    if (alreadyExists) return;

    addCapturedStep(evt);
    if (hudLastAction) {
      hudLastAction.textContent = formatActionPreview(evt);
    }
  }

  function addCapturedStep(safeEvent) {
    if (capturedSteps.length > 0) {
      var lastStep = capturedSteps[capturedSteps.length - 1];
      if (lastStep.kind === "navigate" && safeEvent.kind === "navigate" && lastStep.url === safeEvent.url) {
        return;
      }
      if (lastStep.kind === "click" && safeEvent.kind === "navigate") {
        return;
      }
      if (lastStep.kind === "type" && safeEvent.kind === "type" && lastStep.selector === safeEvent.selector) {
        capturedSteps[capturedSteps.length - 1] = safeEvent;
      } else {
        capturedSteps.push(safeEvent);
      }
    } else {
      capturedSteps.push(safeEvent);
    }

    capturedCount = capturedSteps.length;
    try {
      sessionStorage.setItem("__suitest_captured_steps__", JSON.stringify(capturedSteps));
      sessionStorage.setItem("__suitest_captured_count__", String(capturedCount));
      localStorage.setItem("__suitest_captured_steps__", JSON.stringify(capturedSteps));
    } catch (e) {
      console.debug("[Suitest Recorder] Failed to persist captured steps:", e);
    }

    updateCounterDisplay();
    renderStepsList();
  }

  function syncStepsFromServer(onComplete) {
    var doneCalled = false;
    function finish() {
      if (!doneCalled) {
        doneCalled = true;
        if (typeof onComplete === "function") onComplete();
      }
    }
    if (!sessionId) {
      finish();
      return;
    }
    function applyServerSteps(serverEvents) {
      if (hasUserEditedSteps && capturedSteps.length > 0) {
        finish();
        return;
      }
      if (serverEvents.length >= capturedSteps.length || capturedSteps.length === 0) {
        capturedSteps = serverEvents;
        capturedCount = serverEvents.length;
        try {
          sessionStorage.setItem("__suitest_captured_steps__", JSON.stringify(capturedSteps));
          sessionStorage.setItem("__suitest_captured_count__", String(capturedCount));
        } catch (e) {
          console.debug("[Suitest Recorder] Failed to persist server steps:", e);
        }
        updateCounterDisplay();
        renderStepsList();
      }
      finish();
    }

    if (typeof window.__suitest_native_post_event__ === "function") {
      window.__suitest_native_post_event__(JSON.stringify({ action: "get_events", sessionId: sessionId, workspaceId: workspaceId }))
        .then(function (res) {
          if (typeof res === "string") {
            try {
              res = JSON.parse(res);
            } catch (e) {
              console.debug("[Suitest Recorder] Failed to parse native events response:", e);
            }
          }
          if (res && Array.isArray(res.events) && res.events.length > 0) {
            applyServerSteps(res.events);
          } else {
            finish();
          }
        })
        .catch(function (err) {
          console.debug("[Suitest Recorder] Native get_events failed, falling back to HTTP:", err);
          fetchHttpEvents();
        });
    } else {
      fetchHttpEvents();
    }

    function fetchHttpEvents() {
      var query = workspaceId ? "?workspaceId=" + encodeURIComponent(workspaceId) : "";
      var url = apiBase + "/generators/recorder/sessions/" + encodeURIComponent(sessionId) + "/events" + query;
      var headers = {};
      if (workspaceId) headers["X-Workspace-Id"] = workspaceId;
      fetch(url, { method: "GET", headers: headers, credentials: "omit" })
        .then(function (res) { return res.ok ? res.json() : null; })
        .then(function (data) {
          if (data && Array.isArray(data.events) && data.events.length > 0) {
            applyServerSteps(data.events);
          } else {
            finish();
          }
        })
        .catch(function (e) {
          console.debug("[Suitest Recorder] Failed to fetch events from server:", e);
          finish();
        });
    }
  }

  function createHUD() {
    // Only render HUD in top-level window (never in nested iframes)
    if (window !== window.top) {
      return;
    }

    var existing = document.getElementById("suitest-recorder-hud");
    if (existing) {
      hudContainer = existing;
      hudCounter = existing.querySelector("#suitest-hud-counter");
      hudLastAction = existing.querySelector("#suitest-hud-last-action");
      hudAlertNotice = existing.querySelector("#suitest-hud-alert-notice");
      hudStepsDrawer = existing.querySelector("#suitest-hud-steps-drawer");
      hudStepsList = existing.querySelector("#suitest-hud-steps-list");
      hudDrawerTitle = existing.querySelector("#suitest-hud-drawer-title");
      renderStepsList();
      updateCounterDisplay();
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
      "min-width: 280px",
      "max-width: 90vw",
      "min-height: 80px",
      "max-height: 85vh",
      "box-sizing: border-box",
      "resize: none",
      "overflow: hidden",
      "user-select: none",
      "transition: box-shadow 0.2s ease",
    ].join(";");

    var header = document.createElement("div");
    header.style.cssText = "display: flex; align-items: center; justify-content: space-between; gap: 12px;";

    var titleWrapper = document.createElement("div");
    titleWrapper.style.cssText = "display: flex; align-items: center; gap: 8px; font-weight: 600;";

    var pulseDot = document.createElement("span");
    pulseDot.id = "suitest-hud-dot";
    pulseDot.style.cssText = [
      "width: 8px",
      "height: 8px",
      "border-radius: 50%",
      "background-color: " + (isPaused ? "#f59e0b" : "#ef4444"),
      "box-shadow: 0 0 8px " + (isPaused ? "#f59e0b" : "#ef4444"),
      "display: inline-block",
      "transition: all 0.2s ease",
    ].join(";");

    var titleText = document.createElement("span");
    titleText.textContent = "Suitest Recorder";

    titleWrapper.appendChild(pulseDot);
    titleWrapper.appendChild(titleText);

    hudCounter = document.createElement("button");
    hudCounter.id = "suitest-hud-counter";
    hudCounter.type = "button";
    hudCounter.style.cssText = [
      "background: " + (isPaused ? "rgba(245, 158, 11, 0.2)" : "rgba(239, 68, 68, 0.2)"),
      "border: 1px solid " + (isPaused ? "rgba(245, 158, 11, 0.35)" : "rgba(239, 68, 68, 0.35)"),
      "color: " + (isPaused ? "#fcd34d" : "#fca5a5"),
      "padding: 2px 7px",
      "border-radius: 6px",
      "font-size: 11px",
      "font-weight: 600",
      "cursor: pointer",
      "display: flex",
      "align-items: center",
      "gap: 4px",
      "transition: all 0.15s ease",
    ].join(";");
    hudCounter.title = "Click to toggle captured steps list";
    updateCounterDisplay();

    hudCounter.addEventListener("click", function (e) {
      e.stopPropagation();
      e.preventDefault();
      toggleStepsDrawer();
    });

    header.appendChild(titleWrapper);
    header.appendChild(hudCounter);

    // Action Toolbar: Assert + Pause/Resume + Finalize
    var toolbar = document.createElement("div");
    toolbar.id = "suitest-hud-toolbar";
    toolbar.style.cssText = "display: flex; align-items: center; justify-content: space-between; gap: 6px; padding-top: 2px;";

    var assertBtn = document.createElement("button");
    assertBtn.id = "suitest-hud-assert-btn";
    assertBtn.type = "button";
    assertBtn.style.cssText = [
      "background: rgba(56, 189, 248, 0.12)",
      "border: 1px solid rgba(56, 189, 248, 0.3)",
      "color: #38bdf8",
      "padding: 3px 8px",
      "border-radius: 6px",
      "font-size: 11px",
      "font-weight: 500",
      "cursor: pointer",
      "display: flex",
      "align-items: center",
      "gap: 4px",
      "transition: all 0.15s ease",
    ].join(";");
    assertBtn.textContent = "Assert";

    assertBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      e.preventDefault();
      setAssertMode(!isAssertMode);
    });

    var pauseBtn = document.createElement("button");
    pauseBtn.id = "suitest-hud-pause-btn";
    pauseBtn.type = "button";
    pauseBtn.style.cssText = [
      "background: rgba(255, 255, 255, 0.08)",
      "border: 1px solid rgba(255, 255, 255, 0.15)",
      "color: " + (isPaused ? "#34d399" : "#e2e8f0"),
      "padding: 3px 8px",
      "border-radius: 6px",
      "font-size: 11px",
      "font-weight: 500",
      "cursor: pointer",
      "display: flex",
      "align-items: center",
      "gap: 4px",
      "transition: background 0.15s ease",
    ].join(";");
    pauseBtn.textContent = isPaused ? "Resume" : "Pause";

    pauseBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      e.preventDefault();
      isPaused = !isPaused;
      try {
        sessionStorage.setItem("__suitest_recorder_paused__", isPaused ? "true" : "false");
      } catch (err) {
        console.debug("[Suitest Recorder] Failed to store pause state:", err);
      }
      if (isPaused) {
        pulseDot.style.backgroundColor = "#f59e0b";
        pulseDot.style.boxShadow = "0 0 8px #f59e0b";
        hudCounter.style.background = "rgba(245, 158, 11, 0.2)";
        hudCounter.style.borderColor = "rgba(245, 158, 11, 0.35)";
        hudCounter.style.color = "#fcd34d";
        pauseBtn.textContent = "Resume";
        pauseBtn.style.color = "#34d399";
        if (hudLastAction) hudLastAction.textContent = "Recording paused — actions ignored";
      } else {
        pulseDot.style.backgroundColor = "#ef4444";
        pulseDot.style.boxShadow = "0 0 8px #ef4444";
        hudCounter.style.background = "rgba(239, 68, 68, 0.2)";
        hudCounter.style.borderColor = "rgba(239, 68, 68, 0.35)";
        hudCounter.style.color = "#fca5a5";
        pauseBtn.textContent = "Pause";
        pauseBtn.style.color = "#e2e8f0";
        if (hudLastAction) hudLastAction.textContent = "Recording active";
      }
      updateCounterDisplay();
    });

    var finalizeBtn = document.createElement("button");
    finalizeBtn.id = "suitest-hud-finalize-btn";
    finalizeBtn.type = "button";
    finalizeBtn.style.cssText = [
      "background: #4f46e5",
      "border: 1px solid #6366f1",
      "color: #ffffff",
      "padding: 3px 10px",
      "border-radius: 6px",
      "font-size: 11px",
      "font-weight: 600",
      "cursor: pointer",
      "display: flex",
      "align-items: center",
      "gap: 4px",
      "box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4)",
      "transition: opacity 0.15s ease",
    ].join(";");
    finalizeBtn.textContent = "Finalize";

    var isFinalizing = false;
    finalizeBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      e.preventDefault();
      if (isFinalizing) return;
      isFinalizing = true;
      finalizeBtn.disabled = true;
      finalizeBtn.style.opacity = "0.7";
      finalizeBtn.textContent = "Saving...";
      if (hudLastAction) hudLastAction.textContent = "Saving steps and closing browser...";

      function onSavedAndClose() {
        finalizeBtn.textContent = "Saved! Closing...";
        finalizeBtn.style.background = "#10b981";
        finalizeBtn.style.borderColor = "#059669";
        pulseDot.style.backgroundColor = "#10b981";
        pulseDot.style.boxShadow = "0 0 8px #10b981";
        if (hudLastAction) hudLastAction.textContent = "Steps saved. Returning to SuiteTest...";

        setTimeout(function () {
          if (typeof window.__suitest_native_post_event__ === "function") {
            window.__suitest_native_post_event__(JSON.stringify({
              action: "close_browser",
              reason: "hud_finalize",
              sessionId: sessionId,
              workspaceId: workspaceId,
            })).catch(function (err) {
              console.debug("[Suitest Recorder] Native close error:", err);
            });
          }
          try {
            window.close();
          } catch (err) {
            console.debug("[Suitest Recorder] window.close() error:", err);
          }
        }, 600);
      }

      if (typeof flushTyping === "function") {
        try {
          flushTyping();
        } catch (err) {
          console.debug("[Suitest Recorder] flushTyping error:", err);
        }
      }

      if (typeof window.__suitest_native_post_event__ === "function") {
        window.__suitest_native_post_event__(JSON.stringify({
          action: "finish_recording",
          reason: "hud_finalize",
          sessionId: sessionId,
          workspaceId: workspaceId,
          events: capturedSteps,
        }))
          .then(function () {
            onSavedAndClose();
          })
          .catch(function () {
            onSavedAndClose();
          });
      } else {
        var query = workspaceId ? "?workspaceId=" + encodeURIComponent(workspaceId) : "";
        var url = apiBase + "/generators/recorder/sessions/" + encodeURIComponent(sessionId) + "/sync" + query;
        var headers = { "Content-Type": "application/json" };
        if (workspaceId) headers["X-Workspace-Id"] = workspaceId;
        fetch(url, {
          method: "PUT",
          headers: headers,
          body: JSON.stringify({ events: capturedSteps }),
        }).finally(function () {
          onSavedAndClose();
        });
      }
    });

    toolbar.appendChild(assertBtn);
    toolbar.appendChild(pauseBtn);
    toolbar.appendChild(finalizeBtn);

    hudAlertNotice = document.createElement("div");
    hudAlertNotice.id = "suitest-hud-alert-notice";
    hudAlertNotice.style.cssText = [
      "display: none",
      "background: rgba(99, 102, 241, 0.15)",
      "border: 1px solid rgba(99, 102, 241, 0.3)",
      "border-radius: 6px",
      "padding: 4px 6px",
      "font-size: 10.5px",
      "color: #c7d2fe",
      "align-items: center",
      "justify-content: space-between",
      "gap: 4px",
    ].join(";");

    var alertTxtSpan = document.createElement("span");
    alertTxtSpan.id = "suitest-hud-alert-text";
    alertTxtSpan.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:140px;";
    hudAlertNotice.appendChild(alertTxtSpan);

    var alertActionsDiv = document.createElement("div");
    alertActionsDiv.style.cssText = "display:flex;align-items:center;gap:3px;shrink:0;";

    var assertAlertBtn = document.createElement("button");
    assertAlertBtn.id = "suitest-hud-assert-alert";
    assertAlertBtn.style.cssText = "background:#4f46e5;color:#ffffff;border:none;padding:2px 6px;border-radius:3px;cursor:pointer;font-size:10px;font-weight:600;";
    assertAlertBtn.textContent = "Assert";
    assertAlertBtn.onclick = function (e) {
      e.stopPropagation();
      if (!pendingAlert.el) return;
      var sel = getSelector(pendingAlert.el);
      var sampleText = (pendingAlert.text || "").slice(0, 100);
      postEvent({
        kind: "assert",
        timestamp: new Date().toISOString(),
        selector: sel,
        text: sampleText,
        assertion: {
          type: "text",
          expected: 'Alert shows "' + sampleText.slice(0, 50) + '"',
          description: "Assert alert shows: " + sampleText.slice(0, 50),
          code: "() => { var el = document.querySelector(" + JSON.stringify(sel) + "); return !!(el && (el.textContent || '').includes(" + JSON.stringify(sampleText.slice(0, 50)) + ")); }",
        },
      });
      hudAlertNotice.style.display = "none";
      if (hudLastAction) hudLastAction.textContent = "Asserted alert notification";
    };

    var dismissAlertBtn = document.createElement("button");
    dismissAlertBtn.id = "suitest-hud-dismiss-alert";
    dismissAlertBtn.style.cssText = "background:none;border:none;color:#94a3b8;cursor:pointer;font-size:12px;padding:0 2px;";
    dismissAlertBtn.textContent = "✕";
    dismissAlertBtn.onclick = function (e) {
      e.stopPropagation();
      hudAlertNotice.style.display = "none";
    };

    alertActionsDiv.appendChild(assertAlertBtn);
    alertActionsDiv.appendChild(dismissAlertBtn);
    hudAlertNotice.appendChild(alertActionsDiv);

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
    hudLastAction.textContent = isPaused
      ? "Recording paused — actions ignored"
      : "Recording active";

    hudStepsDrawer = document.createElement("div");
    hudStepsDrawer.id = "suitest-hud-steps-drawer";
    hudStepsDrawer.style.cssText = [
      "display: " + (isStepsPanelOpen ? "flex" : "none"),
      "flex-direction: column",
      "gap: 6px",
      "background: rgba(15, 23, 42, 0.8)",
      "border: 1px solid rgba(255, 255, 255, 0.12)",
      "border-radius: 8px",
      "padding: 8px 10px",
      "flex: 1 1 auto",
      "min-height: 80px",
      "margin-top: 2px",
      "box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.3)",
      "overflow: hidden",
    ].join(";");

    var drawerHeader = document.createElement("div");
    drawerHeader.style.cssText = "display: flex; align-items: center; justify-content: space-between; font-size: 10.5px; color: #94a3b8; font-weight: 600; padding-bottom: 4px; border-bottom: 1px solid rgba(255, 255, 255, 0.08);";

    hudDrawerTitle = document.createElement("span");
    hudDrawerTitle.id = "suitest-hud-drawer-title";
    hudDrawerTitle.textContent = "Recorded Steps (" + capturedSteps.length + ")";

    var drawerActions = document.createElement("div");
    drawerActions.style.cssText = "display: flex; align-items: center; gap: 4px;";

    var cleanBtn = document.createElement("button");
    cleanBtn.type = "button";
    cleanBtn.id = "suitest-hud-clean-noise";
    cleanBtn.style.cssText = "background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.12); color: #94a3b8; font-size: 10px; cursor: pointer; padding: 1px 6px; border-radius: 3px; font-weight: 500;";
    cleanBtn.textContent = "Clean noise";
    cleanBtn.title = "Remove consecutive duplicate actions";
    cleanBtn.onclick = function (e) {
      e.stopPropagation();
      e.preventDefault();
      cleanNoise();
    };

    var addStepBtn = document.createElement("button");
    addStepBtn.type = "button";
    addStepBtn.id = "suitest-hud-add-step";
    addStepBtn.style.cssText = "background: rgba(56, 189, 248, 0.12); border: 1px solid rgba(56, 189, 248, 0.3); color: #38bdf8; font-size: 10px; cursor: pointer; padding: 1px 6px; border-radius: 3px; font-weight: 600;";
    addStepBtn.textContent = "+ Step";
    addStepBtn.title = "Add custom step";
    addStepBtn.onclick = function (e) {
      e.stopPropagation();
      e.preventDefault();
      addManualStep();
    };

    var drawerCloseBtn = document.createElement("button");
    drawerCloseBtn.type = "button";
    drawerCloseBtn.id = "suitest-hud-drawer-close";
    drawerCloseBtn.style.cssText = "background: none; border: none; color: #64748b; font-size: 11px; cursor: pointer; padding: 0 2px; margin-left: 2px;";
    drawerCloseBtn.textContent = "✕";
    drawerCloseBtn.title = "Close drawer";
    drawerCloseBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      e.preventDefault();
      toggleStepsDrawer(false);
    });

    drawerActions.appendChild(cleanBtn);
    drawerActions.appendChild(addStepBtn);
    drawerActions.appendChild(drawerCloseBtn);

    drawerHeader.appendChild(hudDrawerTitle);
    drawerHeader.appendChild(drawerActions);
    hudStepsDrawer.appendChild(drawerHeader);

    hudStepsList = document.createElement("div");
    hudStepsList.id = "suitest-hud-steps-list";
    hudStepsList.style.cssText = [
      "display: flex",
      "flex-direction: column",
      "gap: 4px",
      "overflow-y: auto",
      "flex: 1 1 auto",
      "min-height: 60px",
      "padding-right: 2px",
    ].join(";");
    hudStepsDrawer.appendChild(hudStepsList);

    // Interactive corner resize grip handle
    var resizeGrip = document.createElement("div");
    resizeGrip.id = "suitest-hud-resize-grip";
    resizeGrip.style.cssText = [
      "position: absolute",
      "right: 2px",
      "bottom: 2px",
      "width: 14px",
      "height: 14px",
      "cursor: nwse-resize",
      "display: flex",
      "align-items: center",
      "justify-content: center",
      "opacity: 0.5",
      "transition: opacity 0.15s ease",
      "user-select: none",
      "z-index: 10",
    ].join(";");
    resizeGrip.innerHTML = '<svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M9 1L1 9M9 5L5 9M9 9L9 9" stroke="#94a3b8" stroke-width="1.5" stroke-linecap="round"/></svg>';
    resizeGrip.title = "Drag to resize";
    resizeGrip.addEventListener("mouseenter", function () { resizeGrip.style.opacity = "1"; });
    resizeGrip.addEventListener("mouseleave", function () { if (!isResizing) resizeGrip.style.opacity = "0.5"; });

    var isResizing = false;
    var resizeStartX, resizeStartY, resizeStartWidth, resizeStartHeight;

    resizeGrip.addEventListener("mousedown", function (e) {
      e.stopPropagation();
      e.preventDefault();
      isResizing = true;
      lastHudInteractionTime = Date.now();
      resizeStartX = e.clientX;
      resizeStartY = e.clientY;
      var rect = hudContainer.getBoundingClientRect();
      resizeStartWidth = rect.width;
      resizeStartHeight = rect.height;
      document.body.style.cursor = "nwse-resize";
    });

    window.addEventListener("mousemove", function (e) {
      if (!isResizing) return;
      lastHudInteractionTime = Date.now();
      var newW = Math.max(280, resizeStartWidth + (e.clientX - resizeStartX));
      var newH = Math.max(90, resizeStartHeight + (e.clientY - resizeStartY));
      hudContainer.style.width = newW + "px";
      hudContainer.style.height = newH + "px";
    });

    window.addEventListener(
      "mouseup",
      function (e) {
        if (isResizing) {
          isResizing = false;
          lastHudInteractionTime = Date.now();
          document.body.style.cursor = "";
          e.stopPropagation();
        }
      },
      true
    );

    hudContainer.appendChild(header);
    hudContainer.appendChild(toolbar);
    hudContainer.appendChild(hudStepsDrawer);
    hudContainer.appendChild(hudAlertNotice);
    hudContainer.appendChild(hudLastAction);
    hudContainer.appendChild(resizeGrip);

    renderStepsList();

    // Make HUD draggable
    var isDragging = false;
    var startX, startY, initialX, initialY;

    header.style.cursor = "grab";
    header.addEventListener("mousedown", function (e) {
      isDragging = true;
      lastHudInteractionTime = Date.now();
      startX = e.clientX;
      startY = e.clientY;
      var rect = hudContainer.getBoundingClientRect();
      initialX = rect.left;
      initialY = rect.top;
      header.style.cursor = "grabbing";
    });

    window.addEventListener("mousemove", function (e) {
      if (!isDragging) return;
      lastHudInteractionTime = Date.now();
      var dx = e.clientX - startX;
      var dy = e.clientY - startY;
      hudContainer.style.left = `${initialX + dx}px`;
      hudContainer.style.top = `${initialY + dy}px`;
      hudContainer.style.bottom = "auto";
      hudContainer.style.right = "auto";
    });

    window.addEventListener(
      "mouseup",
      function (e) {
        if (isDragging) {
          isDragging = false;
          lastHudInteractionTime = Date.now();
          header.style.cursor = "grab";
          e.stopPropagation();
        }
      },
      true
    );

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

  function ensurePickerOverlay() {
    if (pickerOverlay && document.getElementById("suitest-picker-overlay")) {
      return pickerOverlay;
    }
    pickerOverlay = document.createElement("div");
    pickerOverlay.id = "suitest-picker-overlay";
    pickerOverlay.style.cssText = [
      "position: fixed",
      "display: none",
      "pointer-events: none",
      "z-index: 2147483646",
      "border: 2px dashed #06b6d4",
      "background: rgba(6, 182, 212, 0.15)",
      "box-shadow: 0 0 12px rgba(6, 182, 212, 0.35)",
      "border-radius: 4px",
      "box-sizing: border-box",
    ].join(";");

    var badge = document.createElement("div");
    badge.id = "suitest-picker-badge";
    badge.style.cssText = [
      "position: absolute",
      "top: -24px",
      "left: 0",
      "background: #0891b2",
      "color: #ffffff",
      "font-family: monospace, sans-serif",
      "font-size: 10px",
      "font-weight: 600",
      "padding: 2px 6px",
      "border-radius: 3px",
      "white-space: nowrap",
      "box-shadow: 0 2px 4px rgba(0, 0, 0, 0.4)",
      "pointer-events: none",
    ].join(";");
    pickerOverlay.appendChild(badge);

    var root = document.body || document.documentElement;
    if (root) root.appendChild(pickerOverlay);
    return pickerOverlay;
  }

  function broadcastAssertMode(active) {
    try {
      var iframes = document.querySelectorAll("iframe");
      for (var i = 0; i < iframes.length; i++) {
        try {
          if (iframes[i].contentWindow) {
            iframes[i].contentWindow.postMessage(
              {
                __suitest_recorder__: true,
                type: "suitest_set_assert_mode",
                active: Boolean(active),
              },
              "*"
            );
          }
        } catch (e) {
          console.debug("[Suitest Recorder] Failed to postMessage to iframe:", e);
        }
      }
    } catch (err) {
      console.debug("[Suitest Recorder] Failed to query iframes:", err);
    }
  }

  function setAssertMode(active) {
    isAssertMode = active;
    broadcastAssertMode(active);
    if (isSubframe) {
      try {
        window.top.postMessage(
          {
            __suitest_recorder__: true,
            type: "suitest_set_assert_mode",
            active: Boolean(active),
          },
          "*"
        );
      } catch (err) {
        console.debug("[Suitest Recorder] Failed to notify top window of assert mode:", err);
      }
    }
    var btn = document.getElementById("suitest-hud-assert-btn");
    if (isAssertMode) {
      ensurePickerOverlay();
      if (btn) {
        btn.style.background = "#0284c7";
        btn.style.borderColor = "#38bdf8";
        btn.style.color = "#ffffff";
        btn.textContent = "Pick... (Esc)";
      }
      if (hudLastAction) {
        hudLastAction.textContent = "Click any element on page to assert";
      }
    } else {
      if (pickerOverlay) pickerOverlay.style.display = "none";
      if (assertPopover) {
        assertPopover.remove();
        assertPopover = null;
      }
      if (btn) {
        btn.style.background = "rgba(56, 189, 248, 0.12)";
        btn.style.borderColor = "rgba(56, 189, 248, 0.3)";
        btn.style.color = "#38bdf8";
        btn.textContent = "Assert";
      }
      if (hudLastAction && !isPaused) {
        hudLastAction.textContent = "Recording active";
      }
    }
  }

  function openAssertPopover(targetEl, iframeInfo) {
    if (assertPopover) {
      assertPopover.remove();
      assertPopover = null;
    }
    var sel = "";
    var rawText = "";
    var frameSel = null;
    var rect = null;

    if (iframeInfo) {
      sel = iframeInfo.selector || "";
      rawText = (iframeInfo.text || "").trim();
      frameSel = iframeInfo.frame_selector || null;
      rect = {
        top: Math.max(80, Math.min(window.innerHeight - 250, 150)),
        bottom: Math.max(140, Math.min(window.innerHeight - 190, 210)),
        left: Math.max(20, Math.min(window.innerWidth - 300, 100)),
      };
    } else if (targetEl) {
      sel = getSelector(targetEl);
      rawText = (targetEl.innerText || targetEl.textContent || "").trim();
      frameSel = null;
      rect = targetEl.getBoundingClientRect();
    } else {
      return;
    }
    var sampleText = rawText.slice(0, 80);

    var popover = document.createElement("div");
    popover.id = "suitest-assert-popover";
    popover.style.cssText = [
      "position: fixed",
      "z-index: 2147483647",
      "background: #0f172a",
      "border: 1px solid #38bdf8",
      "border-radius: 8px",
      "padding: 10px",
      "box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.6), 0 0 15px rgba(56, 189, 248, 0.25)",
      "font-family: system-ui, -apple-system, sans-serif",
      "color: #f1f5f9",
      "width: 270px",
      "max-width: 90vw",
    ].join(";");

    var topPos = Math.max(10, Math.min(window.innerHeight - 200, rect.bottom + 8));
    var leftPos = Math.max(10, Math.min(window.innerWidth - 290, rect.left));
    popover.style.top = topPos + "px";
    popover.style.left = leftPos + "px";

    var popHeader = document.createElement("div");
    popHeader.style.cssText = "display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;";
    var popTitle = document.createElement("span");
    popTitle.style.cssText = "font-weight:600;font-size:12px;color:#38bdf8;display:flex;align-items:center;gap:4px;";
    popTitle.textContent = frameSel ? "Add Assertion (iframe)" : "Add Assertion";
    var popClose = document.createElement("button");
    popClose.id = "suitest-popover-close";
    popClose.style.cssText = "background:none;border:none;color:#94a3b8;cursor:pointer;font-size:13px;padding:0 2px;";
    popClose.textContent = "✕";
    popClose.onclick = function (e) {
      e.stopPropagation();
      setAssertMode(false);
    };
    popHeader.appendChild(popTitle);
    popHeader.appendChild(popClose);
    popover.appendChild(popHeader);

    var selBadge = document.createElement("div");
    selBadge.style.cssText = "font-family:monospace;font-size:10px;color:#94a3b8;background:#1e293b;padding:4px 6px;border-radius:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:8px;";
    var badgeLabel = frameSel ? frameSel + " ➔ " + sel : sel;
    selBadge.title = badgeLabel;
    selBadge.textContent = badgeLabel;
    popover.appendChild(selBadge);

    var btnGroup = document.createElement("div");
    btnGroup.style.cssText = "display:flex;flex-direction:column;gap:5px;";

    var btnVis = document.createElement("button");
    btnVis.id = "suitest-btn-assert-visible";
    btnVis.style.cssText = "background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:6px 8px;border-radius:5px;font-size:11px;font-weight:500;text-align:left;cursor:pointer;display:flex;align-items:center;gap:6px;";
    btnVis.textContent = "Assert Element is Visible";
    btnGroup.appendChild(btnVis);

    var btnTxt = null;
    if (sampleText) {
      btnTxt = document.createElement("button");
      btnTxt.id = "suitest-btn-assert-text";
      btnTxt.style.cssText = "background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:6px 8px;border-radius:5px;font-size:11px;font-weight:500;text-align:left;cursor:pointer;display:flex;align-items:center;gap:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
      btnTxt.title = sampleText;
      btnTxt.textContent = "Assert Text: \"" + sampleText.slice(0, 24) + (sampleText.length > 24 ? "…" : "") + "\"";
      btnGroup.appendChild(btnTxt);
    }
    popover.appendChild(btnGroup);

    var root = document.body || document.documentElement;
    if (root) root.appendChild(popover);
    assertPopover = popover;

    var btnVisEl = popover.querySelector("#suitest-btn-assert-visible");
    if (btnVisEl) {
      btnVisEl.onclick = function (e) {
        e.stopPropagation();
        postEvent({
          kind: "assert",
          timestamp: new Date().toISOString(),
          selector: sel,
          frame_selector: frameSel || undefined,
          text: "",
          assertion: {
            type: "visible",
            expected: sel + (frameSel ? " in frame " + frameSel : "") + " is visible",
            description: "Assert " + sel + (frameSel ? " in frame " + frameSel : "") + " is visible",
            code: "() => { var el = document.querySelector(" + JSON.stringify(sel) + "); return !!(el && el.offsetParent !== null); }",
          },
        });
        setAssertMode(false);
        if (hudLastAction) hudLastAction.textContent = "Asserted " + sel + " visible";
      };
    }

    var btnTxtEl = popover.querySelector("#suitest-btn-assert-text");
    if (btnTxtEl && sampleText) {
      btnTxtEl.onclick = function (e) {
        e.stopPropagation();
        postEvent({
          kind: "assert",
          timestamp: new Date().toISOString(),
          selector: sel,
          frame_selector: frameSel || undefined,
          text: sampleText,
          assertion: {
            type: "text",
            expected: sel + (frameSel ? " in frame " + frameSel : "") + ' contains "' + sampleText + '"',
            description: "Assert text of " + sel + (frameSel ? " in frame " + frameSel : ""),
            code: "() => { var el = document.querySelector(" + JSON.stringify(sel) + "); return !!(el && (el.textContent || '').includes(" + JSON.stringify(sampleText) + ")); }",
          },
        });
        setAssertMode(false);
        if (hudLastAction) hudLastAction.textContent = 'Asserted text "' + sampleText.slice(0, 16) + '"';
      };
    }
  }

  function setupAlertObserver() {
    if (!window.MutationObserver || !document.documentElement) return;
    var seenAlerts = new WeakSet();
    var alertTimeout = null;

    function checkNode(node) {
      if (!node || node.nodeType !== 1) return;
      if (
        node.id === "suitest-recorder-hud" ||
        node.id === "suitest-picker-overlay" ||
        node.id === "suitest-assert-popover" ||
        seenAlerts.has(node)
      ) {
        return;
      }

      var matches = false;
      var alertEl = null;
      var sel = '[role="alert"], [role="status"], [role="dialog"], [aria-modal="true"], .toast, .alert, [class*="toast"], [class*="swal"], [class*="notification"], [class*="snackbar"]';
      if (node.matches && node.matches(sel)) {
        matches = true;
        alertEl = node;
      } else if (node.querySelector) {
        alertEl = node.querySelector(sel);
        if (alertEl) matches = true;
      }

      if (matches && alertEl && !seenAlerts.has(alertEl)) {
        seenAlerts.add(alertEl);
        var txt = (alertEl.innerText || alertEl.textContent || "").trim();
        if (txt.length > 2 && txt.length < 300) {
          showDetectedAlert(alertEl, txt);
        }
      }
    }

    function showDetectedAlert(el, text) {
      if (!hudAlertNotice) return;
      pendingAlert.el = el;
      pendingAlert.text = text;
      var alertTxt = hudAlertNotice.querySelector("#suitest-hud-alert-text");
      if (alertTxt) {
        var shortTxt = text.slice(0, 45) + (text.length > 45 ? "…" : "");
        alertTxt.title = text;
        alertTxt.textContent = "Alert: " + shortTxt;
      }
      hudAlertNotice.style.display = "flex";

      if (alertTimeout) clearTimeout(alertTimeout);
      alertTimeout = setTimeout(function () {
        if (hudAlertNotice) hudAlertNotice.style.display = "none";
      }, 10000);
    }

    var pendingNodes = [];
    var debounceTimer = null;

    function processPendingNodes() {
      var nodes = pendingNodes.splice(0, pendingNodes.length);
      for (var i = 0; i < nodes.length; i++) {
        checkNode(nodes[i]);
      }
    }

    var alertObserver = new MutationObserver(function (mutations) {
      for (var m of mutations) {
        if (m.type === "childList" && m.addedNodes && m.addedNodes.length) {
          Array.prototype.push.apply(pendingNodes, m.addedNodes);
        } else if (m.type === "attributes") {
          pendingNodes.push(m.target);
        }
      }
      if (pendingNodes.length > 50) {
        pendingNodes.length = 50;
      }
      if (!debounceTimer) {
        debounceTimer = setTimeout(function () {
          debounceTimer = null;
          processPendingNodes();
        }, 150);
      }
    });
    alertObserver.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class", "role", "aria-modal", "style"],
    });
  }

  function sanitizeString(str, maxLen) {
    if (typeof str !== "string") return "";
    return str.slice(0, maxLen || 1024);
  }

  // 4. Send Event to Suitest Session API
  function postEvent(eventData) {
    if (isPaused) {
      return;
    }
    if (!sessionId || typeof sessionId !== "string" || !/^[a-zA-Z0-9_-]+$/.test(sessionId)) {
      console.warn("[Suitest Recorder] Valid session_id required, event ignored:", eventData);
      return;
    }

    var validKinds = ["click", "type", "navigate", "assert", "network", "select", "upload"];
    if (!eventData || !validKinds.includes(eventData.kind)) {
      return;
    }

    var frameSel = eventData.frameSelector
      ? sanitizeString(eventData.frameSelector, 512)
      : (eventData.frame_selector
        ? sanitizeString(eventData.frame_selector, 512)
        : (isSubframe ? getFrameSelector() : undefined));

    var safeEvent = {
      kind: eventData.kind,
      timestamp: sanitizeString(eventData.timestamp, 64) || new Date().toISOString(),
      url: sanitizeString(eventData.url, 2048) || getCurrentVirtualUrl(),
      selector: sanitizeString(eventData.selector, 512),
      frame_selector: frameSel || undefined,
      text: sanitizeString(eventData.text, 2048),
      masked: Boolean(eventData.masked),
      assertion: eventData.assertion && typeof eventData.assertion === "object" ? eventData.assertion : undefined,
      data: eventData.data && typeof eventData.data === "object" ? eventData.data : undefined,
    };

    addCapturedStep(safeEvent);

    if (isSubframe) {
      try {
        window.top.postMessage(
          {
            __suitest_recorder__: true,
            type: "iframe_event",
            event: safeEvent,
          },
          "*"
        );
      } catch (e) {
        console.debug("[Suitest Recorder] Failed to postMessage iframe event to window.top:", e);
      }
    }

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
      capturedCount = Math.max(capturedCount, newCount);
    } else {
      capturedCount = Math.max(capturedCount, capturedSteps.length);
    }
    try {
      sessionStorage.setItem("__suitest_captured_count__", String(capturedCount));
    } catch (e) {
      console.debug("[Suitest Recorder] Could not persist captured count:", e);
    }
    updateCounterDisplay();
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
    if (evt.kind === "assert") return `Assert → ${evt.selector || ""} (${(evt.assertion && evt.assertion.expected) || "condition"})`;
    if (evt.kind === "select") return `Select → ${evt.selector} (${(evt.assertion && evt.assertion.label) || evt.text})`;
    if (evt.kind === "upload") return `Upload → ${evt.selector} (${evt.text || "file"})`;
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


  function isPasswordField(el) {
    if (!el || !el.tagName) return false;
    var tag = el.tagName.toLowerCase();
    if (tag !== "input" && tag !== "textarea") return false;
    if (el.type === "password") return true;

    var autocomplete = (el.getAttribute("autocomplete") || "").toLowerCase();
    if (autocomplete === "current-password" || autocomplete === "new-password" || autocomplete === "password") {
      return true;
    }

    var name = (el.name || "").toLowerCase();
    if (/pass(word|wd)?/i.test(name)) return true;

    var id = (el.id || "").toLowerCase();
    if (/pass(word|wd)?/i.test(id)) return true;

    var ariaLabel = (el.getAttribute("aria-label") || "").toLowerCase();
    if (/password/i.test(ariaLabel)) return true;

    var placeholder = (el.getAttribute("placeholder") || "").toLowerCase();
    if (/password/i.test(placeholder)) return true;

    var testId = (el.getAttribute("data-test") || el.getAttribute("data-testid") || "").toLowerCase();
    if (/pass(word|wd)?/i.test(testId)) return true;

    return false;
  }

  // 7. DOM Listeners
  function initListeners() {
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
        if (e.key === "Escape" && isAssertMode) {
          setAssertMode(false);
          return;
        }
        if (e.key === "Enter") {
          flushTyping();
        }
      },
      true
    );

    // Mousemove for Assert Mode element hover highlighter
    document.addEventListener(
      "mousemove",
      function (e) {
        if (!isAssertMode || !pickerOverlay) return;
        var target = e.target;
        if (!target || target === document.body || target === document.documentElement) {
          pickerOverlay.style.display = "none";
          return;
        }
        if (
          (hudContainer && (target === hudContainer || hudContainer.contains(target))) ||
          (assertPopover && (target === assertPopover || assertPopover.contains(target))) ||
          target === pickerOverlay ||
          pickerOverlay.contains(target)
        ) {
          pickerOverlay.style.display = "none";
          return;
        }

        var rect = target.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) {
          pickerOverlay.style.display = "none";
          return;
        }

        pickerOverlay.style.display = "block";
        pickerOverlay.style.top = rect.top + "px";
        pickerOverlay.style.left = rect.left + "px";
        pickerOverlay.style.width = rect.width + "px";
        pickerOverlay.style.height = rect.height + "px";

        var badge = document.getElementById("suitest-picker-badge");
        if (badge) {
          var tag = (target.tagName || "").toLowerCase();
          var txt = (target.innerText || target.textContent || "").trim().slice(0, 24);
          badge.textContent = tag + (txt ? ' "' + txt + '"' : "");
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
      },
      true
    );

    // Clicks
    document.addEventListener(
      "click",
      function (e) {
        var target = e.target;
        if (!target) return;

        // Skip clicks immediately after dragging or resizing the HUD (< 400ms)
        if (Date.now() - lastHudInteractionTime < 400) {
          e.stopPropagation();
          e.preventDefault();
          return;
        }

        // Skip clicks on our own HUD
        if (hudContainer && (target === hudContainer || hudContainer.contains(target))) {
          return;
        }

        // Skip clicks on root document body or html element (empty page background)
        if (target === document.body || target === document.documentElement) {
          return;
        }

        // Intercept clicks when in Assert Mode to open Assertion Popover
        if (isAssertMode) {
          if (assertPopover && (target === assertPopover || assertPopover.contains(target))) {
            return;
          }
          e.preventDefault();
          e.stopPropagation();
          if (pickerOverlay) pickerOverlay.style.display = "none";
          if (isSubframe) {
            var frameSel = getFrameSelector() || "iframe";
            var sel = getSelector(target);
            var rawText = (target.innerText || target.textContent || "").trim();
            try {
              window.top.postMessage(
                {
                  __suitest_recorder__: true,
                  type: "suitest_open_assert_popover",
                  selector: sel,
                  text: rawText,
                  frame_selector: frameSel,
                },
                "*"
              );
            } catch (err) {
              console.debug("[Suitest Recorder] Failed to postMessage open_assert_popover to window.top:", err);
            }
            return;
          }
          openAssertPopover(target);
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

        lastUserInteractionTime = Date.now();
        postEvent({
          kind: "click",
          timestamp: now,
          selector: selector,
          url: currentUrl,
        });
      },
      true
    );

    document.addEventListener(
      "submit",
      function (e) {
        lastUserInteractionTime = Date.now();
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

        // Ignore file inputs — file inputs fire 'input' with fake paths (e.g. C:\fakepath\...)
        // and are properly handled by the 'change' upload event listener.
        var tag = (target.tagName || "").toLowerCase();
        if (tag === "input" && (target.type || "").toLowerCase() === "file") {
          return;
        }

        clearTimeout(typingTimer);
        pendingTypingTarget = target;
        pendingTypingSelector = getSelector(target);
        pendingTypingMasked = isPasswordField(target);

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
        if (!target) return;
        if (hudContainer && (target === hudContainer || hudContainer.contains(target))) return;

        // 1. Capture native <select> dropdown option changes
        if (target.tagName && target.tagName.toLowerCase() === "select") {
          var vals = [];
          var labels = [];
          if (target.selectedOptions && target.selectedOptions.length > 0) {
            for (var sIdx = 0; sIdx < target.selectedOptions.length; sIdx++) {
              var sOpt = target.selectedOptions[sIdx];
              vals.push(sOpt.value);
              labels.push(sOpt.text || sOpt.label || sOpt.value);
            }
          } else if (target.options && target.selectedIndex >= 0) {
            var opt = target.options[target.selectedIndex];
            vals.push(opt.value);
            labels.push(opt.text || opt.label || opt.value);
          } else if (target.value) {
            vals.push(target.value);
            labels.push(target.value);
          }
          var val = vals[0] || "";
          var label = labels.join(", ") || val;
          var sel = getSelector(target);
          postEvent({
            kind: "select",
            timestamp: new Date().toISOString(),
            selector: sel,
            text: val,
            assertion: {
              label: label,
              value: val,
              values: vals,
            },
            data: {
              values: vals,
              labels: labels,
            },
          });
          return;
        }

        // 2. Capture native <input type="file"> file upload changes
        if (target.tagName && target.tagName.toLowerCase() === "input" && (target.type || "").toLowerCase() === "file") {
          if (target.files && target.files.length > 0) {
            var filesList = Array.from(target.files);
            var fSel = getSelector(target);
            var filePromises = filesList.map(function (f) {
              return new Promise(function (resolve) {
                if (f.size < 10 * 1024 * 1024 && typeof FileReader !== "undefined") {
                  var r = new FileReader();
                  r.onload = function (evt) {
                    resolve({
                      file_name: f.name,
                      file_size: f.size,
                      file_type: f.type,
                      base64: evt.target ? evt.target.result : "",
                    });
                  };
                  r.onerror = function () {
                    resolve({ file_name: f.name, file_size: f.size, file_type: f.type });
                  };
                  r.readAsDataURL(f);
                } else {
                  resolve({ file_name: f.name, file_size: f.size, file_type: f.type });
                }
              });
            });

            Promise.all(filePromises).then(function (results) {
              if (!results || results.length === 0) return;
              var primary = results[0];
              var allNames = results.map(function (it) {
                return it.file_name;
              });
              postEvent({
                kind: "upload",
                timestamp: new Date().toISOString(),
                selector: fSel,
                text: allNames.join(", "),
                data: {
                  file_name: primary.file_name,
                  file_size: primary.file_size,
                  file_type: primary.file_type,
                  base64: primary.base64,
                  files: results,
                  file_names: allNames,
                },
              });
            });
          }
          return;
        }

        if (!("value" in target)) return;

        if (!pendingTypingTarget || pendingTypingTarget !== target) {
          pendingTypingTarget = target;
          pendingTypingSelector = getSelector(target);
          pendingTypingMasked = isPasswordField(target);
        }

        flushTyping();
      },
      true
    );

    setupAlertObserver();

    // Listen for SPA navigation (pushState, replaceState, popstate, hashchange)
    var lastRecordedUrl = getCurrentVirtualUrl();
    function checkUrlChange() {
      var current = getCurrentVirtualUrl();
      if (current !== lastRecordedUrl) {
        lastRecordedUrl = current;
        if (Date.now() - lastUserInteractionTime < 2000) {
          return;
        }
        postEvent({
          kind: "navigate",
          timestamp: new Date().toISOString(),
          url: current,
        });
      }
    }

    window.addEventListener("popstate", checkUrlChange);
    window.addEventListener("hashchange", checkUrlChange);


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

    if (isSubframe) {
      window.addEventListener("message", function (e) {
        if (!e.data || e.data.__suitest_recorder__ !== true) return;
        if (e.data.type === "suitest_set_assert_mode") {
          isAssertMode = Boolean(e.data.active);
          if (isAssertMode) {
            ensurePickerOverlay();
          } else if (pickerOverlay) {
            pickerOverlay.style.display = "none";
          }
          broadcastAssertMode(isAssertMode);
        }
      });
    }

    if (!isSubframe) {
      // Listen for events from child iframes so they appear immediately in top HUD
      window.addEventListener("message", function (e) {
        if (!e.data || e.data.__suitest_recorder__ !== true) return;
        if (e.data.type === "iframe_event" && e.data.event) {
          handleIncomingIframeEvent(e.data.event);
        }
        if (e.data.type === "suitest_set_assert_mode" && !e.data.active) {
          setAssertMode(false);
        }
        if (e.data.type === "suitest_open_assert_popover") {
          openAssertPopover(null, {
            selector: e.data.selector,
            text: e.data.text,
            frame_selector: e.data.frame_selector,
          });
        }
      });

      // Expose hook for Playwright evaluate bridge
      window.__suitest_on_iframe_event__ = function (evt) {
        if (!evt || !evt.kind) return;
        handleIncomingIframeEvent(evt);
      };
    }
  }

  // 8. Initialize on DOM Ready
  function start() {
    if (!isSubframe) {
      createHUD();
    }
    initListeners();

    if (isSubframe) {
      return;
    }

    function checkAndEmitInitialNavigate() {
      var currentUrl = getCurrentVirtualUrl();
      if (!currentUrl || currentUrl.startsWith("about:")) return;

      var lastNav = null;
      for (var i = capturedSteps.length - 1; i >= 0; i--) {
        if (capturedSteps[i] && capturedSteps[i].kind === "navigate") {
          lastNav = capturedSteps[i];
          break;
        }
      }
      if (lastNav && lastNav.url === currentUrl) {
        return;
      }
      postEvent({
        kind: "navigate",
        timestamp: new Date().toISOString(),
        url: currentUrl,
      });
    }

    // Hydrate existing steps from server first, then check if navigate event needs to be emitted
    syncStepsFromServer(function () {
      checkAndEmitInitialNavigate();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
