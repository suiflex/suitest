"use strict";

/**
 * Minimal arrow-key + type-to-filter picker, stdlib only (readline raw mode).
 * Stands in for inquire::Select from the jira reference — no dependency.
 */

const readline = require("node:readline");

/**
 * @param {string} prompt
 * @param {{value:string,label:string,hint?:string}[]} items
 * @returns {Promise<string>} chosen value (rejects on cancel / no TTY)
 */
function select(prompt, items) {
  const stdin = process.stdin;
  const stdout = process.stdout;

  if (!stdin.isTTY) {
    return Promise.reject(
      new Error("no TTY for interactive picker — pass --client <target>"),
    );
  }

  return new Promise((resolve, reject) => {
    let filter = "";
    let index = 0;

    // Align the second column so hints line up like the jira picker.
    const labelWidth = Math.max(...items.map((i) => i.label.length)) + 2;

    const visible = () =>
      filter
        ? items.filter((i) =>
            i.label.toLowerCase().includes(filter.toLowerCase()),
          )
        : items;

    let lastLines = 0;

    function render() {
      const rows = visible();
      if (index >= rows.length) index = Math.max(0, rows.length - 1);

      const lines = [];
      lines.push(`? ${prompt}${filter ? `  (filter: ${filter})` : ""}`);
      for (let i = 0; i < rows.length; i++) {
        const it = rows[i];
        const marker = i === index ? ">" : " ";
        const label = it.label.padEnd(labelWidth);
        const hint = it.hint ? `(${it.hint})` : "";
        lines.push(`${marker} ${label}${hint}`);
      }
      lines.push("[↑↓ to move, enter to select, type to filter]");

      // Redraw in place: move cursor up over the previous block and clear.
      if (lastLines > 0) {
        readline.moveCursor(stdout, 0, -lastLines);
      }
      readline.cursorTo(stdout, 0);
      readline.clearScreenDown(stdout);
      stdout.write(lines.join("\n") + "\n");
      lastLines = lines.length;
    }

    function cleanup() {
      stdin.removeListener("keypress", onKeypress);
      if (stdin.isTTY) stdin.setRawMode(false);
      stdin.pause();
    }

    function onKeypress(str, key) {
      if (!key) return;
      const rows = visible();

      if (key.ctrl && key.name === "c") {
        cleanup();
        stdout.write("\n");
        return reject(new Error("selection cancelled"));
      }
      if (key.name === "escape") {
        cleanup();
        stdout.write("\n");
        return reject(new Error("selection cancelled"));
      }
      if (key.name === "up") {
        index = index > 0 ? index - 1 : Math.max(0, rows.length - 1);
        return render();
      }
      if (key.name === "down") {
        index = rows.length ? (index + 1) % rows.length : 0;
        return render();
      }
      if (key.name === "return") {
        if (!rows.length) return; // nothing matches the filter
        const chosen = rows[index];
        cleanup();
        return resolve(chosen.value);
      }
      if (key.name === "backspace") {
        filter = filter.slice(0, -1);
        index = 0;
        return render();
      }
      // printable char -> extend filter
      if (str && str.length === 1 && !key.ctrl && !key.meta) {
        filter += str;
        index = 0;
        return render();
      }
    }

    readline.emitKeypressEvents(stdin);
    stdin.setRawMode(true);
    stdin.resume();
    stdin.on("keypress", onKeypress);
    render();
  });
}

module.exports = { select };
