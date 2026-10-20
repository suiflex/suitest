import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

interface CapturedRecorderEvent {
  kind: string;
  selector?: string;
  data?: Record<string, unknown>;
  [key: string]: unknown;
}

test.describe("Live CAPTCHA Recorder Assistant (Simulation)", () => {
  test("auto-detects captcha, auto-fills on focus, and records solve_captcha step", async ({ page }) => {
    const recordedEvents: CapturedRecorderEvent[] = [];

    // Intercept solve-captcha API
    await page.route("**/api/v1/generators/recorder/sessions/*/solve-captcha*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "success",
          text: "PRINGSEWU",
          source: "client_canvas",
        }),
      });
    });

    // Intercept recorder events API
    await page.route("**/api/v1/generators/recorder/sessions/*/events*", async (route) => {
      const postData = route.request().postDataJSON();
      if (postData) {
        recordedEvents.push(postData);
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ count: recordedEvents.length }),
      });
    });

    // Load mock login DOM page
    const loginHtml = `
      <!DOCTYPE html>
      <html>
        <head>
          <title>Portal Login</title>
          <style>
            body { font-family: sans-serif; background: #f1f5f9; padding: 20px; }
            .login-card { background: white; padding: 24px; border-radius: 8px; width: 340px; margin: auto; }
            .input-group { margin-bottom: 12px; }
            input { width: 100%; padding: 8px; box-sizing: border-box; }
            .captcha-container { display: flex; align-items: center; gap: 8px; }
            #img-captcha { cursor: pointer; border: 1px solid #ccc; width: 120px; height: 38px; }
          </style>
        </head>
        <body>
          <div class="login-card">
            <h2>Masuk ke Akun</h2>
            <form id="loginForm">
              <div class="input-group">
                <input type="text" id="username" name="username" placeholder="Username" />
              </div>
              <div class="input-group">
                <input type="password" id="password" name="password" placeholder="Password" />
              </div>
              <div class="input-group captcha-container">
                <img id="img-captcha" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" alt="CAPTCHA" onClick="this.dataset.refreshed='true'" />
                <input type="text" id="captcha" name="captcha" placeholder="Masukkan Kode CAPTCHA" />
              </div>
              <button type="submit" id="submitBtn">Masuk</button>
            </form>
          </div>
        </body>
      </html>
    `;

    await page.setContent(loginHtml);

    page.on("console", (msg) => console.log("[PAGE CONSOLE]", msg.text()));

    // Read recorder_agent.js
    const scriptPath = path.resolve(__dirname, "../public/recorder_agent.js");
    const scriptContent = fs.readFileSync(scriptPath, "utf-8");

    // Inject configuration script tag and recorder_agent.js
    await page.addScriptTag({
      content: `
        window.__SUITEST_SESSION_ID__ = "sess_sim_e2e_123";
        window.__SUITEST_API_URL__ = "http://localhost:3000/api/v1";
        window.__SUITEST_WORKSPACE_ID__ = "ws_test";
      `,
    });

    await page.addScriptTag({ content: scriptContent });

    // 1. HUD element is created
    const hud = page.locator("#suitest-recorder-hud");
    await expect(hud).toBeVisible();

    // 2. CAPTCHA Notice Toast in HUD is displayed
    const captchaNotice = page.locator("#suitest-hud-captcha-notice");
    await expect(captchaNotice).toBeVisible();
    await expect(captchaNotice).toContainText("#img-captcha");

    // 3. User focuses on the CAPTCHA field
    const captchaInput = page.locator("#captcha");
    await captchaInput.focus();

    // 4. Input receives auto-fill text
    await expect(captchaInput).toHaveValue("PRINGSEWU", { timeout: 5000 });

    // 5. Toast displays Solved status
    await expect(captchaNotice).toContainText('Solved: "PRINGSEWU"');

    // 6. solve_captcha event is recorded in the events queue
    await page.waitForTimeout(500);
    const solveEvent = recordedEvents.find((e) => e.kind === "solve_captcha");
    expect(solveEvent).toBeDefined();
    expect(solveEvent.selector).toBe("#img-captcha");
    expect(solveEvent.data.input_selector).toBe("#captcha");

    // 7. Clicking the CAPTCHA image triggers smart re-solve and records refresh_target
    const captchaImg = page.locator("#img-captcha");
    await captchaImg.click();

    await page.waitForTimeout(1000);
    const refreshEvent = recordedEvents
      .filter((e) => e.kind === "solve_captcha")
      .find((e) => e.data && e.data.refresh_target === "#img-captcha");
    expect(refreshEvent).toBeDefined();
    expect(refreshEvent.data.refresh_target).toBe("#img-captcha");
  });
});
