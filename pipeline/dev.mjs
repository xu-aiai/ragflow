import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const venvPython = join(
  root,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const python = existsSync(venvPython) ? venvPython : "python";
const child = spawn(python, ["workbench.py", ...process.argv.slice(2)], {
  cwd: root,
  stdio: "inherit",
});

child.on("error", (error) => {
  console.error(`无法启动工作台：${error.message}`);
  process.exitCode = 1;
});
child.on("exit", (code) => {
  process.exitCode = code ?? 0;
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
