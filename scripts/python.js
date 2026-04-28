// Runs the backend's venv python with whatever args you pass.
// Cross-platform: picks .venv/Scripts/python.exe on Windows, .venv/bin/python elsewhere.
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const isWin = process.platform === "win32";
const py = isWin
  ? path.join(root, "backend", ".venv", "Scripts", "python.exe")
  : path.join(root, "backend", ".venv", "bin", "python");

if (!fs.existsSync(py)) {
  console.error(
    `\nVenv python not found at ${py}\n` +
      `Run \`npm run setup\` first to create it.\n`,
  );
  process.exit(1);
}

const args = process.argv.slice(2);
const child = spawn(py, args, {
  stdio: "inherit",
  cwd: path.join(root, "backend"),
  env: {
    ...process.env,
    // Force UTF-8 mode on Windows so seed/test output with ↑ → emojis doesn't
    // crash the cp1252 console.
    PYTHONUTF8: "1",
    PYTHONIOENCODING: "utf-8",
  },
});
child.on("exit", (code) => process.exit(code ?? 0));
