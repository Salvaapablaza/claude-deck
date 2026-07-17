// Claude Deck Bridge: per-window HTTP endpoint so the claude-deck daemon can
// focus the exact terminal that hosts a Claude Code session.
//
// POST /focus {"pids": [...]}  -> reveals the terminal whose shell PID is in
//                                 the list; responds {"found": true/false}
// GET  /ping                   -> liveness
//
// The extension registers itself with the daemon (port + workspace info)
// every 20s so the daemon knows which windows exist.

const vscode = require("vscode");
const http = require("http");

const BROKER = "http://127.0.0.1:8642/register-window";

let server;
let registerTimer;

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

async function handleFocus(body, res) {
  let pids = [];
  try {
    pids = new Set(JSON.parse(body).pids || []);
  } catch (e) {
    res.writeHead(400);
    return res.end('{"error":"bad json"}');
  }
  const pairs = await terminalPids();
  const match = pairs.find(([pid]) => pids.has(pid));
  if (match) {
    match[1].show(false);
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end('{"found":true}');
  }
  res.writeHead(200, { "Content-Type": "application/json" });
  return res.end('{"found":false}');
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
  server = http.createServer((req, res) => {
    if (req.method === "GET" && req.url === "/ping") {
      res.writeHead(200);
      return res.end("ok");
    }
    if (req.method === "POST" && req.url === "/focus") {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => handleFocus(body, res));
      return;
    }
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
