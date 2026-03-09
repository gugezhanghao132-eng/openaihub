import path from "node:path";
import { exec } from "node:child_process";
import readline from "node:readline";
import fs from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { fileURLToPath } from "node:url";

const helperDir = path.dirname(fileURLToPath(import.meta.url));

async function pathExists(targetPath) {
  try {
    await fs.access(targetPath);
    return true;
  } catch (error) {
    return false;
  }
}

function buildPiAiOauthEntry(baseDir) {
  return path.join(
    baseDir,
    "node_modules",
    "openclaw",
    "node_modules",
    "@mariozechner",
    "pi-ai",
    "dist",
    "utils",
    "oauth",
    "openai-codex.js",
  );
}

function buildBundledOauthEntry(baseDir) {
  return path.join(baseDir, "oauth", "openai-codex.js");
}

const configuredModuleEntry = String(process.env.OPENCLAW_LOGIN_MODULE_ENTRY || "").trim();
const candidateModuleEntries = [
  configuredModuleEntry,
  buildBundledOauthEntry(path.join(helperDir, "bundled_runtime")),
  buildPiAiOauthEntry(path.join(helperDir, "bundled_runtime")),
  buildBundledOauthEntry(path.join(helperDir, "runtime")),
  buildPiAiOauthEntry(path.join(helperDir, "runtime")),
  buildPiAiOauthEntry(path.join(process.env.APPDATA || "", "npm")),
].filter(Boolean);

let openclawRoot = "";
for (const candidate of candidateModuleEntries) {
  if (await pathExists(candidate)) {
    openclawRoot = candidate;
    break;
  }
}

if (!openclawRoot) {
  throw new Error("找不到 openclaw 登录模块，请检查 bundled runtime 或本机 npm 安装是否完整");
}

const moduleUrl = pathToFileURL(openclawRoot).href;
const { loginOpenAICodex } = await import(moduleUrl);

function decodeJwt(token) {
  try {
    const parts = String(token || "").split(".");
    if (parts.length !== 3) return null;
    const payload = parts[1]
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .padEnd(Math.ceil(parts[1].length / 4) * 4, "=");
    return JSON.parse(Buffer.from(payload, "base64").toString("utf8"));
  } catch {
    return null;
  }
}

function getEmail(accessToken) {
  const payload = decodeJwt(accessToken);
  const profile = payload?.["https://api.openai.com/profile"];
  return typeof profile?.email === "string" ? profile.email : "";
}

function openBrowser(url) {
  if (process.platform === "win32") {
    exec(`start "" "${url}"`);
    return;
  }
  exec(`xdg-open "${url}" || open "${url}"`);
}

function readManualInput() {
  return new Promise((resolve, reject) => {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stderr,
    });
    rl.question("如果浏览器没有自动完成，或者最后出现错误页，请把地址栏里的完整回调链接或授权码粘贴到这里后回车：\n> ", (answer) => {
      rl.close();
      resolve(String(answer || "").trim());
    });
    rl.on("SIGINT", () => {
      rl.close();
      reject(new Error("manual input cancelled"));
    });
  });
}

const creds = await loginOpenAICodex({
  onAuth: ({ url, instructions }) => {
    if (instructions) console.error(instructions);
    console.error("请在浏览器中打开下面这个链接完成登录：");
    console.error(url);
    console.error("如果浏览器最后出现超时或错误页，请把地址栏里的完整回调链接复制回终端。\n");
    openBrowser(url);
  },
  onPrompt: async ({ message }) => {
    process.stderr.write(`请粘贴回调地址或授权码： `);
    const chunks = [];
    for await (const chunk of process.stdin) chunks.push(chunk);
    return Buffer.concat(chunks).toString("utf8").trim();
  },
  onProgress: (message) => {
    console.error(message);
  },
  onManualCodeInput: async () => readManualInput(),
});

const result = { ...creds, email: getEmail(creds.access) };
const outputPath = process.env.OPENCODE_LOGIN_OUTPUT_PATH;
if (outputPath) {
  await fs.writeFile(outputPath, `${JSON.stringify(result)}\n`, "utf8");
} else {
  process.stdout.write(`${JSON.stringify(result)}\n`);
}
