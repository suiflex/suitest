"use strict";

/**
 * Masked secret prompt for the CLI onboarding. Node's `readline` echoes input
 * verbatim, so API keys/passwords would print in the clear. This overrides the
 * interface's output writer to emit `*` per typed char instead of the raw byte.
 *
 * No dependency — the mute trick is stdlib readline (`ponytail:` no
 * inquirer/read). Returns the trimmed secret, or "" if the user just hits enter.
 */

const readline = require("node:readline");

function askSecret(question, { input = process.stdin, output = process.stdout } = {}) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input, output });
    let printed = false;
    // Called on every keystroke. Print the prompt once, then mask the rest.
    rl._writeToOutput = (chunk) => {
      if (!printed) {
        rl.output.write(question);
        printed = true;
        return;
      }
      // Preserve control sequences (enter/backspace redraw) but mask visible chars.
      if (chunk === "\r\n" || chunk === "\n" || chunk === "\r") {
        rl.output.write(chunk);
      } else {
        rl.output.write("*");
      }
    };
    rl.question(question, (answer) => {
      rl.output.write("\n");
      rl.close();
      resolve(answer.trim());
    });
  });
}

module.exports = { askSecret };
