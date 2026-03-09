/**
 * OpenAI Codex (ChatGPT OAuth) flow
 *
 * NOTE: This module uses Node.js crypto and http for the OAuth callback.
 * It is only intended for CLI use, not browser environments.
 */
// NEVER convert to top-level imports - breaks browser/Vite builds (web-ui)
let _randomBytes = null;
let _http = null;
if (typeof process !== "undefined" && (process.versions?.node || process.versions?.bun)) {
    import("node:crypto").then((m) => {
        _randomBytes = m.randomBytes;
    });
    import("node:http").then((m) => {
        _http = m;
    });
}
import { generatePKCE } from "./pkce.js";
const CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann";
const AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize";
const TOKEN_URL = "https://auth.openai.com/oauth/token";
const REDIRECT_URI = "http://localhost:1455/auth/callback";
const SCOPE = "openid profile email offline_access";
const JWT_CLAIM_PATH = "https://api.openai.com/auth";
const SUCCESS_HTML = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Authentication successful</title>
</head>
<body>
  <p>Authentication successful. Return to your terminal to continue.</p>
</body>
</html>`;
function createState() {
    if (!_randomBytes) {
        throw new Error("OpenAI Codex OAuth is only available in Node.js environments");
    }
    return _randomBytes(16).toString("hex");
}
function parseAuthorizationInput(input) {
    const value = input.trim();
    if (!value)
        return {};
    try {
        const url = new URL(value);
        return {
            code: url.searchParams.get("code") ?? undefined,
            state: url.searchParams.get("state") ?? undefined,
        };
    }
    catch {
        // not a URL
    }
    if (value.includes("#")) {
        const [code, state] = value.split("#", 2);
        return { code, state };
    }
    if (value.includes("code=")) {
        const params = new URLSearchParams(value);
        return {
            code: params.get("code") ?? undefined,
            state: params.get("state") ?? undefined,
        };
    }
    return { code: value };
}
function decodeJwt(token) {
    try {
        const parts = token.split(".");
        if (parts.length !== 3)
            return null;
        const payload = parts[1] ?? "";
        const decoded = atob(payload);
        return JSON.parse(decoded);
    }
    catch {
        return null;
    }
}
async function exchangeAuthorizationCode(code, verifier, redirectUri = REDIRECT_URI) {
    const response = await fetch(TOKEN_URL, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
            grant_type: "authorization_code",
            client_id: CLIENT_ID,
            code,
            code_verifier: verifier,
            redirect_uri: redirectUri,
        }),
    });
    if (!response.ok) {
        const text = await response.text().catch(() => "");
        console.error("[openai-codex] code->token failed:", response.status, text);
        return { type: "failed" };
    }
    const json = (await response.json());
    if (!json.access_token || !json.refresh_token || typeof json.expires_in !== "number") {
        console.error("[openai-codex] token response missing fields:", json);
        return { type: "failed" };
    }
    return {
        type: "success",
        access: json.access_token,
        refresh: json.refresh_token,
        expires: Date.now() + json.expires_in * 1000,
    };
}
async function refreshAccessToken(refreshToken) {
    try {
        const response = await fetch(TOKEN_URL, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: new URLSearchParams({
                grant_type: "refresh_token",
                refresh_token: refreshToken,
                client_id: CLIENT_ID,
            }),
        });
        if (!response.ok) {
            const text = await response.text().catch(() => "");
            console.error("[openai-codex] Token refresh failed:", response.status, text);
            return { type: "failed" };
        }
        const json = (await response.json());
        if (!json.access_token || !json.refresh_token || typeof json.expires_in !== "number") {
            console.error("[openai-codex] Token refresh response missing fields:", json);
            return { type: "failed" };
        }
        return {
            type: "success",
            access: json.access_token,
            refresh: json.refresh_token,
            expires: Date.now() + json.expires_in * 1000,
        };
    }
    catch (error) {
        console.error("[openai-codex] Token refresh error:", error);
        return { type: "failed" };
    }
}
async function createAuthorizationFlow(originator = "pi") {
    const { verifier, challenge } = await generatePKCE();
    const state = createState();
    const url = new URL(AUTHORIZE_URL);
    url.searchParams.set("response_type", "code");
    url.searchParams.set("client_id", CLIENT_ID);
    url.searchParams.set("redirect_uri", REDIRECT_URI);
    url.searchParams.set("scope", SCOPE);
    url.searchParams.set("code_challenge", challenge);
    url.searchParams.set("code_challenge_method", "S256");
    url.searchParams.set("state", state);
    url.searchParams.set("id_token_add_organizations", "true");
    url.searchParams.set("codex_cli_simplified_flow", "true");
    url.searchParams.set("originator", originator);
    return { verifier, state, url: url.toString() };
}
function startLocalOAuthServer(state) {
    if (!_http) {
        throw new Error("OpenAI Codex OAuth is only available in Node.js environments");
    }
    let lastCode = null;
    let cancelled = false;
    const server = _http.createServer((req, res) => {
        try {
            const url = new URL(req.url || "", "http://localhost");
            if (url.pathname !== "/auth/callback") {
                res.statusCode = 404;
                res.end("Not found");
                return;
            }
            if (url.searchParams.get("state") !== state) {
                res.statusCode = 400;
                res.end("State mismatch");
                return;
            }
            const code = url.searchParams.get("code");
            if (!code) {
                res.statusCode = 400;
                res.end("Missing authorization code");
                return;
            }
            res.statusCode = 200;
            res.setHeader("Content-Type", "text/html; charset=utf-8");
            res.end(SUCCESS_HTML);
            lastCode = code;
        }
        catch {
            res.statusCode = 500;
            res.end("Internal error");
        }
    });
    return new Promise((resolve) => {
        server
            .listen(1455, "127.0.0.1", () => {
            resolve({
                close: () => server.close(),
                cancelWait: () => {
                    cancelled = true;
                },
                waitForCode: async () => {
                    const sleep = () => new Promise((r) => setTimeout(r, 100));
                    for (let i = 0; i < 600; i += 1) {
                        if (lastCode)
                            return { code: lastCode };
                        if (cancelled)
                            return null;
                        await sleep();
                    }
                    return null;
                },
            });
        })
            .on("error", (err) => {
            console.error("[openai-codex] Failed to bind http://127.0.0.1:1455 (", err.code, ") Falling back to manual paste.");
            resolve({
                close: () => {
                    try {
                        server.close();
                    }
                    catch {
                    }
                },
                cancelWait: () => { },
                waitForCode: async () => null,
            });
        });
    });
}
function getAccountId(accessToken) {
    const payload = decodeJwt(accessToken);
    const auth = payload?.[JWT_CLAIM_PATH];
    const accountId = auth?.chatgpt_account_id;
    return typeof accountId === "string" && accountId.length > 0 ? accountId : null;
}
export async function loginOpenAICodex(options) {
    const { verifier, state, url } = await createAuthorizationFlow(options.originator);
    const server = await startLocalOAuthServer(state);
    options.onAuth({ url, instructions: "A browser window should open. Complete login to finish." });
    let code;
    try {
        if (options.onManualCodeInput) {
            let manualCode;
            let manualError;
            const manualPromise = options.onManualCodeInput()
                .then((value) => {
                manualCode = value;
            })
                .catch((error) => {
                manualError = error;
            });
            const browserResult = await server.waitForCode();
            if (browserResult?.code) {
                server.cancelWait();
                code = browserResult.code;
            }
            else {
                await manualPromise;
                if (manualError) {
                    throw manualError;
                }
                const parsed = parseAuthorizationInput(manualCode ?? "");
                if (parsed.state && parsed.state !== state) {
                    throw new Error("Pasted authorization response does not match the current login session");
                }
                code = parsed.code;
            }
        }
        else {
            const browserResult = await server.waitForCode();
            if (browserResult?.code) {
                code = browserResult.code;
            }
            else if (options.onPrompt) {
                const input = await options.onPrompt({ message: "Paste the callback URL or code from the browser" });
                const parsed = parseAuthorizationInput(input);
                if (parsed.state && parsed.state !== state) {
                    throw new Error("Pasted authorization response does not match the current login session");
                }
                code = parsed.code;
            }
        }
    }
    finally {
        server.close();
    }
    if (!code) {
        throw new Error("Login cancelled or timed out");
    }
    options.onProgress?.("Exchanging authorization code...");
    const token = await exchangeAuthorizationCode(code, verifier);
    if (token.type !== "success") {
        throw new Error("Authorization exchange failed");
    }
    const accountId = getAccountId(token.access);
    if (!accountId) {
        throw new Error("Could not extract account ID from access token");
    }
    return {
        access: token.access,
        refresh: token.refresh,
        expires: token.expires,
        accountId,
    };
}
export async function refreshOpenAICodexAccess(refreshToken) {
    return refreshAccessToken(refreshToken);
}
