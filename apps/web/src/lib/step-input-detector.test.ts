import { describe, expect, it } from "vitest";
import {
  detectInputSteps,
  applyStepInputUpdate,
  type StepLike,
} from "./step-input-detector";

describe("step-input-detector", () => {
  describe("detectInputSteps", () => {
    it("detects structured browser_type steps for text and password", () => {
      const steps: StepLike[] = [
        {
          id: "step-1",
          order: 1,
          action: "Type username into #user-input",
          code: JSON.stringify({
            tool: "browser_type",
            arguments: { target: "#user-input", text: "alice" },
          }),
        },
        {
          id: "step-2",
          order: 2,
          action: "Type secret into input#password",
          code: JSON.stringify({
            tool: "browser_type",
            arguments: { target: "input#password", text: "secret123" },
          }),
        },
      ];

      const detected = detectInputSteps(steps);
      expect(detected).toHaveLength(2);
      expect(detected[0]).toMatchObject({
        stepId: "step-1",
        type: "text",
        selector: "#user-input",
        currentValue: "alice",
        isPassword: false,
        isManual: false,
      });
      expect(detected[1]).toMatchObject({
        stepId: "step-2",
        type: "password",
        selector: "input#password",
        currentValue: "secret123",
        isPassword: true,
        isManual: false,
      });
    });

    it("detects structured browser_select_option and browser_navigate", () => {
      const steps: StepLike[] = [
        {
          id: "step-1",
          order: 1,
          action: "Navigate to home",
          code: JSON.stringify({
            tool: "browser_navigate",
            arguments: { url: "https://suitest.dev/login" },
          }),
        },
        {
          id: "step-2",
          order: 2,
          action: "Select country",
          code: JSON.stringify({
            tool: "browser_select_option",
            arguments: { target: "select#country", values: ["ID"] },
          }),
        },
      ];

      const detected = detectInputSteps(steps);
      expect(detected).toHaveLength(2);
      expect(detected[0]!.type).toBe("url");
      expect(detected[0]!.currentValue).toBe("https://suitest.dev/login");
      expect(detected[1]!.type).toBe("select");
      expect(detected[1]!.currentValue).toBe("ID");
    });

    it("detects structured browser_upload_file and browser_file_upload with paths (TC-2002 format)", () => {
      const steps: StepLike[] = [
        {
          id: "step-1",
          order: 1,
          action: "Upload invoice",
          code: JSON.stringify({
            tool: "browser_upload_file",
            arguments: {
              target: "input[type=file]",
              files: ["/uploads/inv1.pdf", "/uploads/inv2.pdf"],
            },
          }),
        },
        {
          id: "step-2",
          order: 2,
          action: "Upload multiple test documents",
          code: JSON.stringify({
            tool: "browser_file_upload",
            arguments: {
              paths: ["/Users/rohmnsa/.suitest/config.json", "/Users/rohmnsa/.suitest/update-check.json"],
            },
          }),
        },
      ];

      const detected = detectInputSteps(steps);
      expect(detected).toHaveLength(2);
      expect(detected[0]!.type).toBe("upload");
      expect(detected[0]!.files).toEqual(["/uploads/inv1.pdf", "/uploads/inv2.pdf"]);
      expect(detected[0]!.currentValue).toBe("/uploads/inv1.pdf, /uploads/inv2.pdf");

      expect(detected[1]!.type).toBe("upload");
      expect(detected[1]!.files).toEqual([
        "/Users/rohmnsa/.suitest/config.json",
        "/Users/rohmnsa/.suitest/update-check.json",
      ]);
    });

    it("falls back to heuristic regex on manual steps without JSON code", () => {
      const steps: StepLike[] = [
        {
          id: "step-1",
          order: 1,
          action: "Type 'john_doe' into #username-field",
          code: null,
        },
        {
          id: "step-2",
          order: 2,
          action: "Select 'VIP' from select#tier",
          code: null,
        },
        {
          id: "step-3",
          order: 3,
          action: "Upload file 'ktp.jpg' to #identity-upload",
          code: null,
        },
        {
          id: "step-4",
          order: 4,
          action: "Navigate to https://google.com",
          code: null,
        },
        {
          id: "step-5",
          order: 5,
          action: "Click on button#submit",
          code: null, // should NOT be detected as input step
        },
      ];

      const detected = detectInputSteps(steps);
      expect(detected).toHaveLength(4);
      expect(detected[0]).toMatchObject({
        stepId: "step-1",
        type: "text",
        currentValue: "john_doe",
        isManual: true,
      });
      expect(detected[1]).toMatchObject({
        stepId: "step-2",
        type: "select",
        currentValue: "VIP",
        isManual: true,
      });
      expect(detected[2]).toMatchObject({
        stepId: "step-3",
        type: "upload",
        currentValue: "ktp.jpg",
        isManual: true,
      });
      expect(detected[3]).toMatchObject({
        stepId: "step-4",
        type: "url",
        currentValue: "https://google.com",
        isManual: true,
      });
    });
  });

  describe("applyStepInputUpdate", () => {
    it("updates text in structured step and synchronizes action text", () => {
      const step: StepLike = {
        id: "step-1",
        order: 1,
        action: "Type 'old_user' into #username",
        code: JSON.stringify({
          tool: "browser_type",
          arguments: { target: "#username", text: "old_user" },
        }),
      };

      const updated = applyStepInputUpdate(step, "new_user");
      const parsed = JSON.parse(updated.code!);
      expect(parsed.arguments.text).toBe("new_user");
      expect(updated.action).toBe("Type 'new_user' into #username");
    });

    it("updates upload files in structured step and generates descriptive action and expected", () => {
      const step: StepLike = {
        id: "step-1",
        order: 1,
        action: "Upload old.pdf",
        expected: "Old file is attached",
        code: JSON.stringify({
          tool: "browser_upload_file",
          arguments: { target: "#file-drop", file: "/tmp/old.pdf" },
        }),
      };

      const updated = applyStepInputUpdate(step, "", ["/fixtures/doc1.pdf", "/fixtures/doc2.pdf"]);
      const parsed = JSON.parse(updated.code!);
      expect(parsed.arguments.files).toEqual(["/fixtures/doc1.pdf", "/fixtures/doc2.pdf"]);
      expect(updated.action).toBe("Upload 2 files (doc1.pdf, doc2.pdf) to #file-drop");
      expect(updated.expected).toBe("2 files are attached");
    });

    it("updates manual step prose action", () => {
      const step: StepLike = {
        id: "step-1",
        order: 1,
        action: "Type 'old_name' into input#name",
        code: null,
      };

      const updated = applyStepInputUpdate(step, "fresh_name");
      expect(updated.action).toBe("Type 'fresh_name' into input#name");
    });
  });
});
