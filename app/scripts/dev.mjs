// Starts the carrier mock (4010), the API (4000) and the Vite dev server (5173) together.
import { spawn } from "node:child_process";

const services = [
  { name: "mock", workspace: "@parcel/carrier-mock", script: "start" },
  { name: "api", workspace: "@parcel/api", script: "start" },
  { name: "web", workspace: "@parcel/web", script: "dev" },
];

const children = services.map(({ name, workspace, script }) => {
  const child = spawn("npm", ["run", script, "--workspace", workspace], { stdio: ["ignore", "pipe", "pipe"] });
  const prefix = (chunk) =>
    String(chunk)
      .split("\n")
      .filter(Boolean)
      .forEach((line) => console.log(`[${name}] ${line}`));
  child.stdout.on("data", prefix);
  child.stderr.on("data", prefix);
  child.on("exit", (code) => {
    console.log(`[${name}] exited with code ${code}`);
    stop(code ?? 1);
  });
  return child;
});

function stop(code) {
  for (const child of children) child.kill("SIGTERM");
  process.exit(code);
}

for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => stop(0));
