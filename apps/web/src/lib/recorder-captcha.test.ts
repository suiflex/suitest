import { describe, expect, it, beforeEach, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";

describe("Recorder Agent CAPTCHA Detection & Pairing", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    // Reset global recorder state flag
    // @ts-expect-error test cleanup
    delete window.__SUITEST_RECORDER_INITIALIZED__;
    // @ts-expect-error test cleanup
    delete window.__suitest_recorder_helpers__;

    const scriptContent = fs.readFileSync(
      path.resolve(__dirname, "../../public/recorder_agent.js"),
      "utf-8",
    );
    // Execute recorder_agent.js in jsdom context
    const fn = new Function(scriptContent);
    fn();
  });

  it("detects captcha input fields by name, id, placeholder, and aria-label", () => {
    // @ts-expect-error global helper
    const { isCaptchaField } = window.__suitest_recorder_helpers__;

    const inp1 = document.createElement("input");
    inp1.name = "captcha_code";
    expect(isCaptchaField(inp1)).toBe(true);

    const inp2 = document.createElement("input");
    inp2.id = "security-code";
    expect(isCaptchaField(inp2)).toBe(true);

    const inp3 = document.createElement("input");
    inp3.placeholder = "Masukkan Kode Keamanan";
    expect(isCaptchaField(inp3)).toBe(true);

    const inp4 = document.createElement("input");
    inp4.setAttribute("aria-label", "Verification code");
    expect(isCaptchaField(inp4)).toBe(true);

    const regularInput = document.createElement("input");
    regularInput.name = "username";
    regularInput.placeholder = "Your username";
    expect(isCaptchaField(regularInput)).toBe(false);

    const pwdInput = document.createElement("input");
    pwdInput.type = "password";
    pwdInput.name = "password";
    expect(isCaptchaField(pwdInput)).toBe(false);
  });

  it("finds and pairs nearest captcha img or canvas in the same container", () => {
    // @ts-expect-error global helper
    const { findNearestCaptchaImage } = window.__suitest_recorder_helpers__;

    const form = document.createElement("form");
    const logoImg = document.createElement("img");
    logoImg.id = "site-logo";
    logoImg.src = "/logo.png";

    const captchaImg = document.createElement("img");
    captchaImg.id = "captcha-img";
    captchaImg.src = "/api/captcha.png";

    const captchaInput = document.createElement("input");
    captchaInput.id = "captcha-input";
    captchaInput.placeholder = "Enter captcha";

    form.appendChild(logoImg);
    form.appendChild(captchaImg);
    form.appendChild(captchaInput);
    document.body.appendChild(form);

    const matched = findNearestCaptchaImage(captchaInput);
    expect(matched).toBe(captchaImg);
  });

  it("finds canvas element when captcha is rendered via canvas", () => {
    // @ts-expect-error global helper
    const { findNearestCaptchaImage } = window.__suitest_recorder_helpers__;

    const form = document.createElement("form");
    const captchaCanvas = document.createElement("canvas");
    captchaCanvas.id = "security-canvas";

    const captchaInput = document.createElement("input");
    captchaInput.name = "captcha";

    form.appendChild(captchaCanvas);
    form.appendChild(captchaInput);
    document.body.appendChild(form);

    const matched = findNearestCaptchaImage(captchaInput);
    expect(matched).toBe(captchaCanvas);
  });

  it("dispatches native value setter, input event, and change event when auto-filling", () => {
    const container = document.createElement("div");
    const input = document.createElement("input");
    input.id = "captcha";
    container.appendChild(input);
    document.body.appendChild(container);

    let inputFired = false;
    let changeFired = false;
    input.addEventListener("input", () => {
      inputFired = true;
    });
    input.addEventListener("change", () => {
      changeFired = true;
    });

    // @ts-expect-error global helper
    const { fillCaptchaValue } = window.__suitest_recorder_helpers__;
    fillCaptchaValue(input, "PRINGSEWU");

    expect(input.value).toBe("PRINGSEWU");
    expect(inputFired).toBe(true);
    expect(changeFired).toBe(true);
    document.body.removeChild(container);
  });

  it("extracts base64 dataURL from canvas element", () => {
    // @ts-expect-error global helper
    const { extractImageBase64 } = window.__suitest_recorder_helpers__;
    const canvas = document.createElement("canvas");
    canvas.toDataURL = () => "data:image/png;base64,mockCanvasData";

    const result = extractImageBase64(canvas);
    expect(result).toBe("data:image/png;base64,mockCanvasData");
  });

  it("handles live solve API call and fills input successfully", async () => {
    // @ts-expect-error global helper
    const { triggerLiveCaptchaSolve } = window.__suitest_recorder_helpers__;

    const img = document.createElement("img");
    img.id = "img-captcha";
    const input = document.createElement("input");
    input.id = "captcha";
    document.body.appendChild(img);
    document.body.appendChild(input);

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: "success", text: "PRINGSEWU" }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await triggerLiveCaptchaSolve(img, input, { captcha_type: "alphanumeric" });

    expect(input.value).toBe("PRINGSEWU");
    vi.unstubAllGlobals();
  });

  it("cancels auto-fill if user types manually before solver completes (user wins pre-emption)", () => {
    const input = document.createElement("input");
    input.id = "captcha";
    input.value = "user_manual_code";

    // @ts-expect-error global helper
    const { shouldApplySolvedText } = window.__suitest_recorder_helpers__;
    const shouldApply = shouldApplySolvedText(input, "PRINGSEWU", { userTyped: true });

    expect(shouldApply).toBe(false);
  });

  it("allows re-solve to overwrite field if it matches previous auto-solved value", () => {
    const input = document.createElement("input");
    input.id = "captcha";
    // @ts-expect-error test tracker
    input._suitest_last_solved_value = "SANGGAU";
    input.value = "SANGGAU";

    // @ts-expect-error global helper
    const { shouldApplySolvedText } = window.__suitest_recorder_helpers__;
    const shouldApply = shouldApplySolvedText(input, "BANDUNG", { userTyped: false });

    expect(shouldApply).toBe(true);
  });

  it("allows re-solve to overwrite field when force option is set", () => {
    const input = document.createElement("input");
    input.id = "captcha";
    input.value = "ANY_OLD_VALUE";

    // @ts-expect-error global helper
    const { shouldApplySolvedText } = window.__suitest_recorder_helpers__;
    const shouldApply = shouldApplySolvedText(input, "BANDUNG", { userTyped: false }, { force: true });

    expect(shouldApply).toBe(true);
  });

  it("successfully updates field on subsequent re-solve call", async () => {
    // @ts-expect-error global helper
    const { triggerLiveCaptchaSolve } = window.__suitest_recorder_helpers__;

    const img = document.createElement("img");
    img.id = "img-captcha-2";
    const input = document.createElement("input");
    input.id = "captcha-2";
    document.body.appendChild(img);
    document.body.appendChild(input);

    let solveCount = 0;
    const mockFetch = vi.fn().mockImplementation(async () => {
      solveCount++;
      return {
        ok: true,
        json: async () => ({ status: "success", text: solveCount === 1 ? "FIRST_SOLVE" : "SECOND_SOLVE" }),
      };
    });
    vi.stubGlobal("fetch", mockFetch);

    // Initial solve
    await triggerLiveCaptchaSolve(img, input, { force: true });
    expect(input.value).toBe("FIRST_SOLVE");

    // Second solve (re-solve)
    await triggerLiveCaptchaSolve(img, input, { force: true });
    expect(input.value).toBe("SECOND_SOLVE");

    vi.unstubAllGlobals();
    document.body.removeChild(img);
    document.body.removeChild(input);
  });
});

