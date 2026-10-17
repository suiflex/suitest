export type DetectedInputType = "text" | "password" | "select" | "upload" | "url";

export interface DetectedInputStep {
  stepId: string;
  order: number;
  type: DetectedInputType;
  label: string;
  selector: string;
  currentValue: string;
  files?: string[];
  isPassword?: boolean;
  isManual?: boolean;
  originalAction: string;
  originalCode: string | null;
}

export interface StepLike {
  id: string;
  order: number;
  action: string;
  expected?: string;
  code: string | null;
  mcp_provider?: string;
  target_kind?: string;
}

/**
 * Checks if a selector or action text indicates a sensitive password/credential field.
 */
function isPasswordField(selector: string, action: string): boolean {
  const s = selector.toLowerCase();
  const a = action.toLowerCase();
  return (
    s.includes("password") ||
    s.includes("passwd") ||
    s.includes("pass") ||
    s.includes("pwd") ||
    a.includes("password") ||
    a.includes("kata sandi")
  );
}

/**
 * Clean target element string for human friendly label.
 */
function cleanLabel(target: string, fallback: string): string {
  if (!target) return fallback;
  return target.length > 35 ? `${target.slice(0, 32)}...` : target;
}

/**
 * Detect input steps from step code or action description.
 */
export function detectInputSteps(steps: StepLike[]): DetectedInputStep[] {
  const detected: DetectedInputStep[] = [];

  for (const step of steps) {
    let parsedCode: { tool?: string; action?: string; arguments?: Record<string, unknown> } | null = null;
    if (step.code) {
      try {
        parsedCode = JSON.parse(step.code);
      } catch {
        parsedCode = null;
      }
    }

    if (parsedCode) {
      const tool = String(parsedCode.tool || parsedCode.action || "").toLowerCase();
      const args = parsedCode.arguments || {};
      const target = String(args.target || args.selector || args.element || "");

      // 1. File Upload
      const isUploadTool =
        tool === "browser_upload_file" ||
        tool === "browser.upload_file" ||
        tool === "browser_file_upload" ||
        tool === "browser.file_upload" ||
        (tool === "browser_type" && (args.file || args.files || args.paths || args.path) && !args.text);

      if (isUploadTool) {
        const files: string[] = [];
        if (Array.isArray(args.files)) {
          files.push(...args.files.map(String));
        } else if (Array.isArray(args.paths)) {
          files.push(...args.paths.map(String));
        } else if (args.file) {
          files.push(String(args.file));
        } else if (args.path) {
          files.push(String(args.path));
        }

        detected.push({
          stepId: step.id,
          order: step.order,
          type: "upload",
          label: cleanLabel(target, "File Upload"),
          selector: target,
          currentValue: files.join(", "),
          files,
          isManual: false,
          originalAction: step.action,
          originalCode: step.code,
        });
        continue;
      }

      // 2. Text / Password Type
      if (tool === "browser_type" || tool === "browser.type") {
        const textVal = args.text !== undefined ? String(args.text) : args.value !== undefined ? String(args.value) : "";
        const isPass = isPasswordField(target, step.action);

        detected.push({
          stepId: step.id,
          order: step.order,
          type: isPass ? "password" : "text",
          isPassword: isPass,
          label: cleanLabel(target, isPass ? "Password Field" : "Input Field"),
          selector: target,
          currentValue: textVal,
          isManual: false,
          originalAction: step.action,
          originalCode: step.code,
        });
        continue;
      }

      // 3. Dropdown / Select Option
      if (
        tool === "browser_select_option" ||
        tool === "browser.select_option" ||
        tool === "browser_select" ||
        tool === "browser.select"
      ) {
        let selectVal = "";
        if (Array.isArray(args.values) && args.values.length > 0) {
          selectVal = String(args.values[0]);
        } else if (args.value !== undefined) {
          selectVal = String(args.value);
        } else if (args.option !== undefined) {
          selectVal = String(args.option);
        }

        detected.push({
          stepId: step.id,
          order: step.order,
          type: "select",
          label: cleanLabel(target, "Dropdown Select"),
          selector: target,
          currentValue: selectVal,
          isManual: false,
          originalAction: step.action,
          originalCode: step.code,
        });
        continue;
      }

      // 4. URL Navigation
      if (tool === "browser_navigate" || tool === "browser.navigate") {
        const urlVal = String(args.url || "");
        detected.push({
          stepId: step.id,
          order: step.order,
          type: "url",
          label: "Page Navigation",
          selector: "URL",
          currentValue: urlVal,
          isManual: false,
          originalAction: step.action,
          originalCode: step.code,
        });
        continue;
      }
    }

    // Tier 2: Heuristics on step.action for manual steps or plain code
    const action = step.action.trim();
    if (!action) continue;

    // Type / Enter / Fill heuristic
    const typeMatch = action.match(
      /(?:type|enter|input|fill)\s+["']?([^"']+)["']?\s+(?:into|in|to)\s+(.+)/i,
    );
    if (typeMatch && typeMatch[1] && typeMatch[2]) {
      const textVal = typeMatch[1].trim();
      const target = typeMatch[2].trim();
      const isPass = isPasswordField(target, action);

      detected.push({
        stepId: step.id,
        order: step.order,
        type: isPass ? "password" : "text",
        isPassword: isPass,
        label: cleanLabel(target, isPass ? "Password Field" : "Input Field"),
        selector: target,
        currentValue: textVal,
        isManual: true,
        originalAction: step.action,
        originalCode: step.code,
      });
      continue;
    }

    // Select heuristic
    const selectMatch = action.match(
      /(?:select|choose)\s+["']?([^"']+)["']?\s+(?:from|in)\s+(.+)/i,
    );
    if (selectMatch && selectMatch[1] && selectMatch[2]) {
      const selectVal = selectMatch[1].trim();
      const target = selectMatch[2].trim();

      detected.push({
        stepId: step.id,
        order: step.order,
        type: "select",
        label: cleanLabel(target, "Dropdown Select"),
        selector: target,
        currentValue: selectVal,
        isManual: true,
        originalAction: step.action,
        originalCode: step.code,
      });
      continue;
    }

    // Upload heuristic
    const uploadMatch = action.match(
      /(?:upload|attach)\s+(?:file\s+|files\s+)?["']?([^"']+)["']?\s+(?:to|into)\s+(.+)/i,
    );
    const genericUploadMatch =
      !uploadMatch &&
      action.match(/(?:upload|attach)\s+(?:multiple\s+)?(?:test\s+)?(?:files|documents|file|document)?/i);

    if (uploadMatch && uploadMatch[1] && uploadMatch[2]) {
      const fileVal = uploadMatch[1].trim();
      const target = uploadMatch[2].trim();

      detected.push({
        stepId: step.id,
        order: step.order,
        type: "upload",
        label: cleanLabel(target, "File Upload"),
        selector: target,
        currentValue: fileVal,
        files: [fileVal],
        isManual: true,
        originalAction: step.action,
        originalCode: step.code,
      });
      continue;
    } else if (genericUploadMatch) {
      detected.push({
        stepId: step.id,
        order: step.order,
        type: "upload",
        label: "File Upload",
        selector: "input[type='file']",
        currentValue: "",
        files: [],
        isManual: true,
        originalAction: step.action,
        originalCode: step.code,
      });
      continue;
    }

    // Navigate URL heuristic
    const navMatch = action.match(
      /(?:navigate|go|open|visit)\s+(?:to\s+)?(https?:\/\/[^\s]+)/i,
    );
    if (navMatch && navMatch[1]) {
      const urlVal = navMatch[1].trim();
      detected.push({
        stepId: step.id,
        order: step.order,
        type: "url",
        label: "Page Navigation",
        selector: "URL",
        currentValue: urlVal,
        isManual: true,
        originalAction: step.action,
        originalCode: step.code,
      });
      continue;
    }
  }

  return detected;
}

/**
 * Apply updated input values to a step, synchronizing both code and action.
 */
export function applyStepInputUpdate<T extends StepLike>(
  step: T,
  newValue: string,
  newFiles?: string[],
): T {
  let updatedCode = step.code;
  let updatedAction = step.action;
  let updatedExpected = step.expected;

  if (step.code) {
    try {
      const parsed = JSON.parse(step.code);
      const tool = String(parsed.tool || parsed.action || "").toLowerCase();
      parsed.arguments = parsed.arguments || {};

      const isUploadTool =
        tool === "browser_upload_file" ||
        tool === "browser.upload_file" ||
        tool === "browser_file_upload" ||
        tool === "browser.file_upload" ||
        (tool === "browser_type" &&
          (parsed.arguments.file || parsed.arguments.files || parsed.arguments.paths || parsed.arguments.path) &&
          !parsed.arguments.text);

      if (isUploadTool) {
        const filesToSet = newFiles && newFiles.length > 0 ? newFiles : newValue ? [newValue] : [];
        if (parsed.arguments.files || filesToSet.length > 1) {
          parsed.arguments.files = filesToSet;
          if (filesToSet.length > 0) parsed.arguments.file = filesToSet[0];
        } else {
          parsed.arguments.file = filesToSet[0] || "";
          parsed.arguments.files = filesToSet;
        }
        if (parsed.arguments.paths) {
          parsed.arguments.paths = filesToSet;
        }

        const target = parsed.arguments.target || parsed.arguments.selector || "file input";
        const fileNames = filesToSet.map((p) => p.split("/").pop() || p);

        if (fileNames.length > 1) {
          updatedAction = `Upload ${fileNames.length} files (${fileNames.join(", ")}) to ${target}`;
          updatedExpected = `${fileNames.length} files are attached`;
        } else if (fileNames.length === 1) {
          updatedAction = `Upload file '${fileNames[0]}' to ${target}`;
          updatedExpected = `File '${fileNames[0]}' is attached`;
        }
      } else if (tool === "browser_type" || tool === "browser.type") {
        const oldVal = String(parsed.arguments.text ?? parsed.arguments.value ?? "");
        parsed.arguments.text = newValue;
        if (parsed.arguments.value !== undefined) {
          parsed.arguments.value = newValue;
        }

        // Auto-update action if oldVal is contained in action
        if (oldVal && updatedAction.includes(oldVal)) {
          updatedAction = updatedAction.replace(oldVal, newValue);
        }
      } else if (
        tool === "browser_select_option" ||
        tool === "browser.select_option" ||
        tool === "browser_select" ||
        tool === "browser.select"
      ) {
        let oldVal = "";
        if (Array.isArray(parsed.arguments.values) && parsed.arguments.values.length > 0) {
          oldVal = String(parsed.arguments.values[0]);
          parsed.arguments.values = [newValue];
        } else if (parsed.arguments.value !== undefined) {
          oldVal = String(parsed.arguments.value);
          parsed.arguments.value = newValue;
        } else {
          oldVal = String(parsed.arguments.option || "");
          parsed.arguments.option = newValue;
        }

        if (oldVal && updatedAction.includes(oldVal)) {
          updatedAction = updatedAction.replace(oldVal, newValue);
        }
      } else if (tool === "browser_navigate" || tool === "browser.navigate") {
        const oldUrl = String(parsed.arguments.url || "");
        parsed.arguments.url = newValue;
        if (oldUrl && updatedAction.includes(oldUrl)) {
          updatedAction = updatedAction.replace(oldUrl, newValue);
        }
      }

      updatedCode = JSON.stringify(parsed, null, 2);
    } catch {
      // If code parsing fails, leave code intact and just sync action
    }
  } else {
    // Manual step: heuristics on action
    const oldTypeMatch = updatedAction.match(
      /((?:type|enter|input|fill)\s+["']?)([^"']+)(["']?\s+(?:into|in|to)\s+.+)/i,
    );
    if (oldTypeMatch) {
      updatedAction = `${oldTypeMatch[1]}${newValue}${oldTypeMatch[3]}`;
    }

    const oldSelectMatch = updatedAction.match(
      /((?:select|choose)\s+["']?)([^"']+)(["']?\s+(?:from|in)\s+.+)/i,
    );
    if (oldSelectMatch) {
      updatedAction = `${oldSelectMatch[1]}${newValue}${oldSelectMatch[3]}`;
    }

    const oldUploadMatch = updatedAction.match(
      /((?:upload|attach)\s+(?:file\s+)?["']?)([^"']+)(["']?\s+(?:to|into)\s+.+)/i,
    );
    if (oldUploadMatch) {
      const fileNames = (newFiles && newFiles.length > 0 ? newFiles : [newValue]).map(
        (p) => p.split("/").pop() || p,
      );
      updatedAction = `${oldUploadMatch[1]}${fileNames.join(", ")}${oldUploadMatch[3]}`;
    }

    const oldNavMatch = updatedAction.match(
      /((?:navigate|go|open|visit)\s+(?:to\s+)?)(https?:\/\/[^\s]+)/i,
    );
    if (oldNavMatch) {
      updatedAction = `${oldNavMatch[1]}${newValue}`;
    }
  }

  return {
    ...step,
    code: updatedCode,
    action: updatedAction,
    expected: (updatedExpected ?? step.expected ?? "") as string,
  };
}
