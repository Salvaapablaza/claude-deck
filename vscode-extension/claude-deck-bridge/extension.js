// Claude Deck Bridge: per-window HTTP endpoints so the claude-deck daemon can
// focus terminals, create Claude sessions, inject commands, and target the
// last-active terminal for actions like /compact.
//
// Endpoints:
//   GET  /ping                     -> liveness
//   POST /focus {pids}             -> reveal terminal whose shell PID matches
//   POST /terminal-name {pids}     -> name of the terminal owning a PID
//   POST /create-terminal {name}   -> create+reveal a terminal, return {id, processId}
//   POST /send-terminal {target, text, bracketed, submit}
//                                  -> inject text into a terminal (target = id
//                                     from create-terminal, or "active")
//   GET  /active-terminal          -> {id, processId, name} of the last-active terminal
//   POST /notify {level, message}  -> show a VS Code notification
//
// The extension registers with the daemon (port + workspace) every 20s.

const vscode = require("vscode");
const http = require("http");

const BROKER = "http://127.0.0.1:8642/register-window";
const BRACKET_START = "\x1b[200~";
const BRACKET_END = "\x1b[201~";

let server;
let registerTimer;

const createdTerminals = new Map();
let terminalCounter = 0;
let lastActiveTerminal = vscode.window.activeTerminal || null;

async function terminalPids() {
  const pairs = [];
  for (const term of vscode.window.terminals) {
    try {
      const pid = await term.processId;
      if (pid) pairs.push([pid, term]);
    } catch (e) {
      /* terminal died */
    }
  }
  return pairs;
}

function sendJson(res, obj, code = 200) {
  res.writeHead(code, { "Content-Type": "application/json" });
  res.end(JSON.stringify(obj));
}

function readBody(req, cb) {
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", () => {
    try {
      cb(body ? JSON.parse(body) : {});
    } catch (e) {
      cb(null);
    }
  });
}

async function handleFocus(data, res) {
  const pids = new Set((data && data.pids) || []);
  const match = (await terminalPids()).find(([pid]) => pids.has(pid));
  if (match) match[1].show(false);
  sendJson(res, { found: !!match });
}

async function handleTerminalName(data, res) {
  const pids = new Set((data && data.pids) || []);
  const match = (await terminalPids()).find(([pid]) => pids.has(pid));
  sendJson(res, { name: match ? match[1].name : null });
}

async function handleCreateTerminal(data, res) {
  const name = (data && data.name) || "Claude";
  const term = vscode.window.createTerminal({ name });
  term.show(false);
  const id = `t${++terminalCounter}`;
  createdTerminals.set(id, term);
  let processId = null;
  try {
    processId = await term.processId;
  } catch (e) {
    /* not ready */
  }
  sendJson(res, { id, processId });
}

function resolveTarget(target) {
  if (target === "active") return lastActiveTerminal;
  return createdTerminals.get(target) || null;
}

function handleSendTerminal(data, res) {
  if (!data) return sendJson(res, { ok: false, error: "bad json" }, 400);
  const term = resolveTarget(data.target);
  if (!term) return sendJson(res, { ok: false, error: "no terminal" });
  const text = data.text != null ? String(data.text) : "";
  if (text.length) {
    const payload = data.bracketed ? BRACKET_START + text + BRACKET_END : text;
    term.sendText(payload, false);
  }
  if (data.submit) {
    // Explicit carriage return — a TUI reads \r as Enter; sendText("", true)
    // does not reliably produce a submit keypress.
    term.sendText("\r", false);
  }
  sendJson(res, { ok: true });
}

async function handleActiveTerminal(res) {
  const term = lastActiveTerminal;
  if (!term || term.exitStatus !== undefined) {
    return sendJson(res, { id: null, processId: null, name: null });
  }
  let processId = null;
  try {
    processId = await term.processId;
  } catch (e) {
    /* died */
  }
  let id = null;
  for (const [k, v] of createdTerminals) if (v === term) id = k;
  sendJson(res, { id, processId, name: term.name });
}

function handleNotify(data, res) {
  const msg = (data && data.message) || "";
  const level = (data && data.level) || "info";
  if (msg) {
    if (level === "error") vscode.window.showErrorMessage(msg);
    else vscode.window.showInformationMessage(msg);
  }
  sendJson(res, { ok: true });
}

function registerWithBroker(port) {
  const folders = (vscode.workspace.workspaceFolders || []).map(
    (f) => f.uri.fsPath
  );
  const payload = JSON.stringify({
    port,
    name: vscode.workspace.name || "",
    folders,
    extension_pid: process.pid,
  });
  const req = http.request(BROKER, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    timeout: 2000,
  });
  req.on("error", () => {});
  req.end(payload);
}

function activate(context) {
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTerminal((term) => {
      if (term) lastActiveTerminal = term;
    }),
    vscode.window.onDidCloseTerminal((term) => {
      if (term === lastActiveTerminal) lastActiveTerminal = null;
      for (const [k, v] of createdTerminals) if (v === term) createdTerminals.delete(k);
    })
  );

  server = http.createServer((req, res) => {
    const { method, url } = req;
    if (method === "GET" && url === "/ping") return res.end("ok");
    if (method === "GET" && url === "/active-terminal")
      return handleActiveTerminal(res);
    if (method === "POST" && url === "/focus")
      return readBody(req, (d) => handleFocus(d, res));
    if (method === "POST" && url === "/terminal-name")
      return readBody(req, (d) => handleTerminalName(d, res));
    if (method === "POST" && url === "/create-terminal")
      return readBody(req, (d) => handleCreateTerminal(d, res));
    if (method === "POST" && url === "/send-terminal")
      return readBody(req, (d) => handleSendTerminal(d, res));
    if (method === "POST" && url === "/notify")
      return readBody(req, (d) => handleNotify(d, res));
    res.writeHead(404);
    res.end();
  });

  server.listen(0, "127.0.0.1", () => {
    const port = server.address().port;
    registerWithBroker(port);
    registerTimer = setInterval(() => registerWithBroker(port), 20000);
  });

  context.subscriptions.push({
    dispose() {
      if (registerTimer) clearInterval(registerTimer);
      if (server) server.close();
    },
  });
}

function deactivate() {
  if (registerTimer) clearInterval(registerTimer);
  if (server) server.close();
}

module.exports = { activate, deactivate };
