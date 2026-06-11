#!/usr/bin/env python3
"""
BRIDGE v2 — Phone ↔ PC Clipboard + File Transfer
Run on your PC. Open the URL on your phone browser.
Works over phone hotspot — no WiFi router needed.

Install once:  pip install flask pyperclip qrcode pillow
Run:           python bridge_pc.py
"""

import os, sys, json, socket, datetime, threading, subprocess, base64, mimetypes
from pathlib import Path

# ── Auto-install dependencies ──────────────────────────────────
def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

for pkg, imp in [("flask","flask"), ("pyperclip","pyperclip"), ("qrcode","qrcode"), ("pillow","PIL")]:
    try:
        __import__(imp)
    except ImportError:
        print(f"Installing {pkg}...")
        install(pkg)

from flask import Flask, request, jsonify, send_file, Response
import pyperclip
import qrcode
import io

# ── Config ─────────────────────────────────────────────────────
PORT     = 5757
PIN      = ""        # Set a PIN like "1234" to lock Bridge, or leave "" for open
SAVE_DIR = Path.home() / "Downloads" / "Bridge"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)

# ── State ──────────────────────────────────────────────────────
state = {"text": "", "source": "", "time": ""}
HISTORY = []
MAX_HIST = 50
HAS_CLIPBOARD = True

try:
    pyperclip.paste()
except:
    HAS_CLIPBOARD = False
    print("⚠ pyperclip clipboard unavailable — auto-copy disabled")

# ── Helpers ────────────────────────────────────────────────────
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def check_pin():
    if not PIN:
        return True
    return request.headers.get("X-Bridge-PIN") == PIN or \
           request.args.get("pin") == PIN or \
           (request.json or {}).get("pin") == PIN

# ── Device detection ────────────────────────────────────────────
def is_mobile():
    ua = request.headers.get("User-Agent", "").lower()
    return any(x in ua for x in ["android", "iphone", "ipad", "mobile", "phone"])

# ── QR Code route ──────────────────────────────────────────────
@app.route("/qr")
def qr_code():
    ip  = get_local_ip()
    url = f"http://{ip}:{PORT}"
    if PIN:
        url += f"?pin={PIN}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

# ── HTML UI ────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Bridge</title>

<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0d0d0f; --surface: #16161a; --border: #2a2a30;
    --accent: #7c6aff; --accent2: #3de0a0; --text: #e8e6f0;
    --muted: #6b6880; --danger: #ff5c5c; --warn: #f5a623;
    --mono: Consolas, monospace; --sans: system-ui, sans-serif;
  }
  html, body { height: 100%; background: var(--bg); color: var(--text); font-family: var(--sans); font-size: 14px; -webkit-font-smoothing: antialiased; }
  .shell { min-height: 100vh; display: flex; flex-direction: column; max-width: 680px; margin: 0 auto; padding: 0 16px 60px; }

  /* Header */
  header { display: flex; align-items: center; justify-content: space-between; padding: 20px 0 24px; border-bottom: 1px solid var(--border); margin-bottom: 28px; }
  .logo { font-family: var(--mono); font-size: 18px; font-weight: 600; letter-spacing: -0.5px; }
  .logo span { color: var(--accent); }
  .status { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted); font-family: var(--mono); }
  .pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent2); animation: pulse 2s infinite; }
  @keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(61,224,160,0.4)} 70%{box-shadow:0 0 0 8px rgba(61,224,160,0)} 100%{box-shadow:0 0 0 0 rgba(61,224,160,0)} }

  /* Tabs */
  .tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid var(--border); }
  .tab { background: none; border: none; color: var(--muted); padding: 10px 16px; font-family: var(--mono); font-size: 12px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; transition: color 0.15s; }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
  .tab-pane { display: none; } .tab-pane.active { display: block; }

  /* Panel */
  .panel { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 20px; overflow: hidden; }
  .panel-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid var(--border); }
  .panel-label { font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); font-family: var(--mono); }
  .panel-label.send { color: var(--accent); } .panel-label.recv { color: var(--accent2); } .panel-label.file { color: var(--warn); }

  /* Textarea */
  textarea { width: 100%; min-height: 140px; background: transparent; border: none; outline: none; resize: vertical; padding: 14px 16px; font-family: var(--mono); font-size: 13px; line-height: 1.6; color: var(--text); caret-color: var(--accent); }
  textarea::placeholder { color: var(--muted); }

  /* Receive box */
  .recv-content { padding: 14px 16px; font-family: var(--mono); font-size: 13px; line-height: 1.6; color: var(--text); white-space: pre-wrap; word-break: break-word; min-height: 60px; }
  .recv-empty { color: var(--muted); font-style: italic; }

  /* Buttons */
  .btn-row { display: flex; gap: 8px; padding: 10px 16px 14px; flex-wrap: wrap; }
  button { display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; border: none; border-radius: 6px; font-family: var(--sans); font-size: 13px; font-weight: 500; cursor: pointer; transition: opacity 0.15s, transform 0.1s; }
  button:active { transform: scale(0.97); }
  .btn-primary { background: var(--accent); color: #fff; }
  .btn-secondary { background: var(--border); color: var(--text); }
  .btn-copy { background: var(--border); color: var(--accent2); }
  .btn-warn { background: rgba(245,166,35,0.15); color: var(--warn); border: 1px solid rgba(245,166,35,0.3); }
  button:disabled { opacity: 0.35; cursor: not-allowed; }

  /* File upload zone */
  .drop-zone { border: 2px dashed var(--border); border-radius: 8px; margin: 12px 16px; padding: 28px 16px; text-align: center; cursor: pointer; transition: border-color 0.2s, background 0.2s; }
  .drop-zone:hover, .drop-zone.drag-over { border-color: var(--warn); background: rgba(245,166,35,0.05); }
  .drop-zone p { font-size: 13px; color: var(--muted); margin-top: 8px; }
  .drop-icon { font-size: 28px; display: block; }
  #file-input { display: none; }

  /* File list */
  .file-item { display: flex; align-items: center; gap: 10px; padding: 10px 16px; border-bottom: 1px solid var(--border); }
  .file-item:last-child { border-bottom: none; }
  .file-icon { font-size: 18px; flex-shrink: 0; }
  .file-info { flex: 1; min-width: 0; }
  .file-name { font-family: var(--mono); font-size: 12px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .file-size { font-size: 11px; color: var(--muted); font-family: var(--mono); margin-top: 2px; }
  .file-dl { font-size: 12px; color: var(--accent2); text-decoration: none; font-family: var(--mono); flex-shrink: 0; }
  .file-dl:hover { text-decoration: underline; }
  .file-empty { padding: 16px; font-size: 13px; color: var(--muted); font-style: italic; text-align: center; }

  /* Progress */
  .progress-wrap { padding: 0 16px 12px; display: none; }
  .progress-bar-bg { background: var(--border); border-radius: 4px; height: 4px; overflow: hidden; }
  .progress-bar { background: var(--warn); height: 100%; width: 0%; transition: width 0.2s; border-radius: 4px; }
  .progress-label { font-size: 11px; color: var(--muted); font-family: var(--mono); margin-top: 6px; }

  /* History */
  .hist-item { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; margin-bottom: 8px; display: flex; gap: 10px; align-items: flex-start; }
  .hist-dir { font-size: 10px; font-family: var(--mono); padding: 2px 6px; border-radius: 4px; white-space: nowrap; flex-shrink: 0; margin-top: 2px; }
  .hist-dir.from-phone { background: rgba(124,106,255,0.15); color: var(--accent); }
  .hist-dir.from-pc { background: rgba(61,224,160,0.12); color: var(--accent2); }
  .hist-dir.file-up { background: rgba(245,166,35,0.12); color: var(--warn); }
  .hist-text { font-family: var(--mono); font-size: 12px; color: var(--muted); white-space: pre-wrap; word-break: break-word; flex: 1; line-height: 1.5; }
  .hist-time { font-size: 10px; color: #3a3a45; font-family: var(--mono); flex-shrink: 0; margin-top: 2px; }
  .char-count { font-size: 11px; font-family: var(--mono); color: var(--muted); }

  /* PIN prompt */
  .pin-screen { min-height: 100vh; display: flex; align-items: center; justify-content: center; }
  .pin-box { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 32px; text-align: center; max-width: 300px; width: 100%; }
  .pin-box h2 { font-family: var(--mono); font-size: 16px; margin-bottom: 8px; }
  .pin-box p { font-size: 13px; color: var(--muted); margin-bottom: 20px; }
  .pin-box input { width: 100%; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 10px 14px; color: var(--text); font-family: var(--mono); font-size: 16px; text-align: center; letter-spacing: 0.2em; outline: none; }
  .pin-box input:focus { border-color: var(--accent); }
  .pin-error { color: var(--danger); font-size: 12px; margin-top: 10px; display: none; }

  /* QR Modal */
  .modal-bg { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.8); z-index: 100; align-items: center; justify-content: center; }
  .modal-bg.open { display: flex; }
  .modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 24px; text-align: center; }
  .modal img { width: 200px; height: 200px; border-radius: 8px; background: white; padding: 8px; }
  .modal p { font-size: 12px; color: var(--muted); font-family: var(--mono); margin-top: 12px; }
  .modal button { margin-top: 16px; }

  /* Toast */
  #toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%) translateY(80px); background: #1e1e26; border: 1px solid var(--border); color: var(--text); padding: 10px 20px; border-radius: 8px; font-size: 13px; font-family: var(--mono); transition: transform 0.25s cubic-bezier(0.34,1.56,0.64,1); z-index: 99; white-space: nowrap; }
  #toast.show { transform: translateX(-50%) translateY(0); }

  /* Clipboard intercept banner */
  #clip-banner { position: fixed; bottom: 0; left: 0; right: 0; background: #1a1a24; border-top: 2px solid var(--accent); padding: 14px 16px 20px; z-index: 200; transform: translateY(100%); transition: transform 0.3s cubic-bezier(0.34,1.2,0.64,1); }
  #clip-banner.show { transform: translateY(0); }
  #clip-banner-label { font-size: 10px; font-family: var(--mono); color: var(--accent); letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 6px; }
  #clip-banner-preview { font-family: var(--mono); font-size: 12px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 12px; opacity: 0.85; max-width: 100%; }
  #clip-banner-btns { display: flex; gap: 8px; }
  #clip-banner-btns button { flex: 1; padding: 10px; font-size: 13px; border-radius: 6px; }

  @media (max-width: 400px) { .shell { padding: 0 12px 60px; } textarea { font-size: 12px; } }
</style>
</head>
<body>

<!-- PIN Screen (shown by JS if PIN required and not provided) -->
<div id="pin-screen" class="pin-screen" style="display:none">
  <div class="pin-box">
    <h2>B<span style="color:var(--accent)">ridge</span></h2>
    <p>Enter your PIN to continue</p>
    <input type="password" id="pin-input" placeholder="••••" maxlength="8" onkeydown="if(event.key==='Enter')submitPin()" autofocus />
    <div class="pin-error" id="pin-error">Wrong PIN</div>
    <div style="margin-top:16px">
      <button class="btn-primary" onclick="submitPin()">Unlock</button>
    </div>
  </div>
</div>

<!-- Main App -->
<div id="main-app" style="display:none">
<div class="shell">

  <header>
    <div class="logo">B<span>ridge</span></div>
    <div style="display:flex;align-items:center;gap:12px">
      <button class="btn-secondary" style="padding:6px 10px;font-size:12px" onclick="document.getElementById('qr-modal').classList.add('open')">QR</button>
      <div class="status"><div class="pulse-dot"></div><span id="status-text">online</span></div>
    </div>
  </header>

  <!-- Tabs -->
  <div class="tabs">
    <button class="tab active" onclick="switchTab('text', this)">Text</button>
    <button class="tab" onclick="switchTab('files', this)">Files</button>
    <button class="tab" onclick="switchTab('history', this)">History</button>
  </div>

  <!-- TEXT TAB -->
  <div id="tab-text" class="tab-pane active">
    <!-- Send: Phone → PC -->
    <div class="panel">
      <div class="panel-header">
        <span class="panel-label send">↑ Phone → PC</span>
        <span class="char-count" id="char-count">0 chars</span>
      </div>
      <textarea id="send-box" placeholder="Paste code, text, notes here — tap Send to copy to PC clipboard"></textarea>
      <div class="btn-row">
        <button class="btn-primary" onclick="sendText()">Send to PC</button>
        <button class="btn-secondary" onclick="clearSend()">Clear</button>
      </div>
    </div>

    <!-- Receive: PC → Phone -->
    <div class="panel">
      <div class="panel-header">
        <span class="panel-label recv">↓ PC → Phone</span>
        <button class="btn-copy" onclick="copyReceived()" id="copy-btn" disabled>Copy</button>
      </div>
      <div class="recv-content recv-empty" id="recv-box">Nothing yet — copy something on your PC</div>
      <div class="btn-row">
        <button class="btn-secondary" onclick="poll()">Refresh</button>
        <button class="btn-secondary" onclick="clearReceived()">Clear</button>
      </div>
    </div>
  </div>

  <!-- FILES TAB -->
  <div id="tab-files" class="tab-pane">
    <!-- Upload: Phone → PC -->
    <div class="panel">
      <div class="panel-header">
        <span class="panel-label file">↑ Phone → PC</span>
        <span style="font-size:11px;color:var(--muted);font-family:var(--mono)">Saves to Downloads/Bridge</span>
      </div>
      <div class="drop-zone" id="drop-zone" onclick="document.getElementById('file-input').click()" ondragover="dragOver(event)" ondragleave="dragLeave(event)" ondrop="dropFile(event)">
        <span class="drop-icon">📁</span>
        <strong style="font-size:14px">Tap to pick a file</strong>
        <p>Any file type — code, images, documents</p>
      </div>
      <input type="file" id="file-input" onchange="uploadFile(this.files[0])" />
      <div class="progress-wrap" id="progress-wrap">
        <div class="progress-bar-bg"><div class="progress-bar" id="progress-bar"></div></div>
        <div class="progress-label" id="progress-label">Uploading…</div>
      </div>
    </div>

    <!-- Download: PC → Phone -->
    <div class="panel">
      <div class="panel-header">
        <span class="panel-label recv">↓ PC → Phone</span>
        <button class="btn-secondary" style="padding:5px 10px;font-size:12px" onclick="loadFiles()">Refresh</button>
      </div>
      <div id="file-list"><div class="file-empty">No files from PC yet</div></div>
    </div>
  </div>

  <!-- HISTORY TAB -->
  <div id="tab-history" class="tab-pane">
    <div id="history-list"><div class="file-empty">No history yet</div></div>
  </div>

</div>
</div>

<!-- QR Modal -->
<div class="modal-bg" id="qr-modal" onclick="if(event.target===this)this.classList.remove('open')">
  <div class="modal">
    <img src="/qr" alt="QR Code for Bridge URL" />
    <p>Scan to open Bridge on your phone</p>
    <button class="btn-secondary" onclick="document.getElementById('qr-modal').classList.remove('open')">Close</button>
  </div>
</div>

<!-- Clipboard intercept banner (mobile only) -->
<div id="clip-banner">
  <div id="clip-banner-label">📋 Phone clipboard detected</div>
  <div id="clip-banner-preview"></div>
  <div id="clip-banner-btns">
    <button class="btn-primary" onclick="clipBannerSend()">Send to PC</button>
    <button class="btn-secondary" onclick="clipBannerDismiss()">Dismiss</button>
  </div>
</div>

<div id="toast"></div>

<script>
  let lastRecv = "";
  let pollTimer;
  let sessionPin = "";
  const PIN_REQUIRED = BRIDGE_PIN_REQUIRED;
  const IS_MOBILE    = BRIDGE_IS_MOBILE;

  // ── Adapt UI labels based on device ─────────────────────────
  function adaptUI() {
    if (IS_MOBILE) {
      // Phone: send UP to PC, receive DOWN from PC — labels already correct
      document.querySelector(".panel-label.send").textContent = "↑ Phone → PC";
      document.querySelector("#tab-text .btn-primary").textContent  = "Send to PC";
    } else {
      // PC browser: flip the perspective
      document.querySelector(".panel-label.send").textContent = "↑ Type here → Phone";
      document.querySelector(".panel-label.recv").textContent = "↓ From Phone (auto-copied)";
      document.querySelector("#tab-text .btn-primary").textContent  = "Send to Phone";
    }
  }

  // ── PIN ──────────────────────────────────────────────────────
  function init() {
    adaptUI();
    if (!PIN_REQUIRED) {
      document.getElementById("main-app").style.display = "block";
      startPolling();
    } else {
      const saved = sessionStorage.getItem("bridge-pin");
      if (saved) { sessionPin = saved; verifyPin(saved); }
      else { document.getElementById("pin-screen").style.display = "flex"; }
    }
  }

  function submitPin() {
    const val = document.getElementById("pin-input").value;
    sessionPin = val;
    verifyPin(val);
  }

  async function verifyPin(pin) {
    try {
      const r = await fetch("/ping?pin=" + encodeURIComponent(pin));
      const d = await r.json();
      if (d.ok) {
        sessionStorage.setItem("bridge-pin", pin);
        document.getElementById("pin-screen").style.display = "none";
        document.getElementById("main-app").style.display = "block";
        startPolling();
      } else {
        document.getElementById("pin-error").style.display = "block";
      }
    } catch(e) {
      document.getElementById("pin-error").style.display = "block";
    }
  }

  function getHeaders() {
    return {"Content-Type": "application/json", "X-Bridge-PIN": sessionPin};
  }

  // ── Tabs ─────────────────────────────────────────────────────
  function switchTab(name, el) {
    document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.getElementById("tab-" + name).classList.add("active");
    el.classList.add("active");
    if (name === "files") loadFiles();
  }

  // ── Send text ────────────────────────────────────────────────
  document.getElementById("send-box").addEventListener("input", function() {
    document.getElementById("char-count").textContent = this.value.length.toLocaleString() + " chars";
  });

  async function sendText() {
    const text = document.getElementById("send-box").value.trim();
    if (!text) { toast("Nothing to send"); return; }
    try {
      const r = await fetch("/send", { method:"POST", headers: getHeaders(), body: JSON.stringify({text, source:"phone"}) });
      const d = await r.json();
      if (d.ok) { toast("✓ Sent — copied to PC clipboard"); addHistory("from-phone", text); }
      else       { toast("⚠ " + (d.error || "Send failed")); }
    } catch(e) { toast("⚠ Connection error"); }
  }

  // ── Poll PC → Phone ──────────────────────────────────────────
  async function poll() {
    try {
      const r = await fetch("/latest?pin=" + encodeURIComponent(sessionPin));
      const d = await r.json();
      if (d.text && d.text !== lastRecv) {
        lastRecv = d.text;
        const box = document.getElementById("recv-box");
        box.textContent = d.text;
        box.classList.remove("recv-empty");
        document.getElementById("copy-btn").disabled = false;
        toast("↓ New content from PC");
        addHistory("from-pc", d.text);
      }
    } catch(e) {}
  }

  function startPolling() { poll(); pollTimer = setInterval(poll, 2000); startPhoneClipWatcher(); }

  // ── Phone clipboard watcher (mobile only) ────────────────────
  let lastPhoneClip = "";
  let clipBannerPending = "";
  let phoneClipTimer = null;

  async function readPhoneClipboard() {
    try {
      const text = await navigator.clipboard.readText();
      if (text && text !== lastPhoneClip && text !== clipBannerPending) {
        lastPhoneClip = text;
        showClipBanner(text);
      }
    } catch(e) {
      // Permission denied or not supported — stop trying silently
      if (e.name === "NotAllowedError") stopPhoneClipWatcher();
    }
  }

  function startPhoneClipWatcher() {
    if (!IS_MOBILE) return;
    if (!navigator.clipboard || !navigator.clipboard.readText) return;
    phoneClipTimer = setInterval(readPhoneClipboard, 2000);
  }

  function stopPhoneClipWatcher() {
    if (phoneClipTimer) { clearInterval(phoneClipTimer); phoneClipTimer = null; }
  }

  function showClipBanner(text) {
    clipBannerPending = text;
    document.getElementById("clip-banner-preview").textContent = text.length > 80 ? text.slice(0, 80) + "…" : text;
    document.getElementById("clip-banner").classList.add("show");
  }

  function clipBannerDismiss() {
    document.getElementById("clip-banner").classList.remove("show");
    clipBannerPending = "";
  }

  async function clipBannerSend() {
    const text = clipBannerPending;
    clipBannerDismiss();
    if (!text) return;
    try {
      const r = await fetch("/send", { method:"POST", headers: getHeaders(), body: JSON.stringify({text, source:"phone"}) });
      const d = await r.json();
      if (d.ok) { toast("✓ Sent to PC clipboard"); addHistory("from-phone", text); }
      else       { toast("⚠ " + (d.error || "Send failed")); }
    } catch(e) { toast("⚠ Connection error"); }
  }

  function copyReceived() {
    const text = document.getElementById("recv-box").textContent;
    if (!text || text === "Nothing yet — copy something on your PC") return;
    navigator.clipboard.writeText(text).then(() => toast("✓ Copied")).catch(() => {
      const ta = document.createElement("textarea"); ta.value = text;
      document.body.appendChild(ta); ta.select(); document.execCommand("copy");
      document.body.removeChild(ta); toast("✓ Copied");
    });
  }

  function clearSend() { document.getElementById("send-box").value = ""; document.getElementById("char-count").textContent = "0 chars"; }
  function clearReceived() {
    const box = document.getElementById("recv-box");
    box.textContent = "Nothing yet — copy something on your PC";
    box.classList.add("recv-empty");
    document.getElementById("copy-btn").disabled = true;
    lastRecv = "";
    fetch("/clear", {method:"POST", headers: getHeaders()});
  }

  // ── File upload ──────────────────────────────────────────────
  function dragOver(e) { e.preventDefault(); document.getElementById("drop-zone").classList.add("drag-over"); }
  function dragLeave(e) { document.getElementById("drop-zone").classList.remove("drag-over"); }
  function dropFile(e) { e.preventDefault(); dragLeave(e); const f = e.dataTransfer.files[0]; if (f) uploadFile(f); }

  async function uploadFile(file) {
    if (!file) return;
    const wrap = document.getElementById("progress-wrap");
    const bar  = document.getElementById("progress-bar");
    const lbl  = document.getElementById("progress-label");
    wrap.style.display = "block"; bar.style.width = "0%";
    lbl.textContent = "Reading " + file.name + "…";

    const reader = new FileReader();
    reader.onload = async function(e) {
      const b64 = e.target.result.split(",")[1];
      bar.style.width = "40%";
      lbl.textContent = "Uploading…";
      try {
        const r = await fetch("/upload", {
          method: "POST",
          headers: {"Content-Type":"application/json","X-Bridge-PIN": sessionPin},
          body: JSON.stringify({name: file.name, size: file.size, type: file.type, data: b64})
        });
        const d = await r.json();
        bar.style.width = "100%";
        if (d.ok) {
          lbl.textContent = "✓ Saved to PC: " + d.path;
          toast("✓ File saved to PC");
          addHistory("file-up", file.name + " (" + fmtSize(file.size) + ")");
        } else {
          lbl.textContent = "⚠ " + (d.error || "Upload failed");
          toast("⚠ Upload failed");
        }
      } catch(err) {
        lbl.textContent = "⚠ Connection error";
        toast("⚠ Connection error");
      }
      setTimeout(() => { wrap.style.display = "none"; }, 3000);
    };
    reader.readAsDataURL(file);
  }

  // ── File list (PC → Phone) ───────────────────────────────────
  async function loadFiles() {
    try {
      const r = await fetch("/files?pin=" + encodeURIComponent(sessionPin));
      const d = await r.json();
      const list = document.getElementById("file-list");
      if (!d.files || !d.files.length) {
        list.innerHTML = '<div class="file-empty">No files from PC yet<br><span style="font-size:11px;color:#3a3a45">Copy files into Downloads/Bridge on your PC</span></div>';
        return;
      }
      list.innerHTML = d.files.map(f => `
        <div class="file-item">
          <span class="file-icon">${fileIcon(f.name)}</span>
          <div class="file-info">
            <div class="file-name">${esc(f.name)}</div>
            <div class="file-size">${fmtSize(f.size)}</div>
          </div>
          <a class="file-dl" href="/download/${encodeURIComponent(f.name)}?pin=${encodeURIComponent(sessionPin)}" download="${esc(f.name)}">↓ get</a>
        </div>`).join("");
    } catch(e) { toast("⚠ Could not load files"); }
  }

  function fileIcon(name) {
    const ext = name.split(".").pop().toLowerCase();
    if (["py","js","ts","html","css","json","sh","cpp","c","java","rs"].includes(ext)) return "📄";
    if (["png","jpg","jpeg","gif","webp","svg"].includes(ext)) return "🖼";
    if (["mp4","mov","avi","mkv"].includes(ext)) return "🎬";
    if (["mp3","wav","ogg","flac"].includes(ext)) return "🎵";
    if (["zip","tar","gz","rar"].includes(ext)) return "📦";
    if (["pdf"].includes(ext)) return "📕";
    return "📁";
  }

  function fmtSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + " KB";
    return (bytes/(1024*1024)).toFixed(1) + " MB";
  }

  // ── History ──────────────────────────────────────────────────
  function addHistory(dir, text) {
    const list = document.getElementById("history-list");
    if (list.innerHTML.includes("No history")) list.innerHTML = "";
    const preview = text.length > 100 ? text.slice(0, 100) + "…" : text;
    const now = new Date().toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});
    const labels = {"from-phone":"phone→pc","from-pc":"pc→phone","file-up":"file→pc"};
    const el = document.createElement("div");
    el.className = "hist-item";
    el.innerHTML = `<span class="hist-dir ${dir}">${labels[dir]||dir}</span><span class="hist-text">${esc(preview)}</span><span class="hist-time">${now}</span>`;
    list.insertBefore(el, list.firstChild);
    while (list.children.length > 20) list.removeChild(list.lastChild);
  }

  function esc(s) { return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

  // ── Toast ────────────────────────────────────────────────────
  let toastTimer;
  function toast(msg) {
    const el = document.getElementById("toast");
    el.textContent = msg; el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2500);
  }

  init();
</script>
</body>
</html>"""

# ── Routes ─────────────────────────────────────────────────────

@app.route("/")
def index():
    mobile = is_mobile()
    html = HTML.replace("BRIDGE_PIN_REQUIRED", "true" if PIN else "false")
    html = html.replace("BRIDGE_IS_MOBILE", "true" if mobile else "false")
    return Response(html, mimetype="text/html")

@app.route("/ping")
def ping():
    if not check_pin():
        return jsonify({"ok": False, "error": "Wrong PIN"})
    return jsonify({"ok": True})

@app.route("/send", methods=["POST"])
def receive_from_phone():
    if not check_pin():
        return jsonify({"ok": False, "error": "Wrong PIN"})
    data   = request.get_json(force=True)
    text   = data.get("text", "")
    source = data.get("source", "phone")
    state.update({"text": text, "source": source, "time": str(datetime.datetime.now())})
    if HAS_CLIPBOARD and source == "phone":
        try:
            pyperclip.copy(text)
            print(f"\n📋 Copied to clipboard ({len(text)} chars)")
        except Exception as e:
            print(f"⚠ Clipboard error: {e}")
    HISTORY.insert(0, {"text": text, "source": source, "time": state["time"]})
    if len(HISTORY) > MAX_HIST: HISTORY.pop()
    print(f"[{source.upper()}→PC] {text[:80]}{'...' if len(text)>80 else ''}")
    return jsonify({"ok": True})

@app.route("/latest")
def latest():
    if not check_pin():
        return jsonify({"ok": False, "error": "Wrong PIN"})
    return jsonify(state)

@app.route("/clear", methods=["POST"])
def clear():
    if not check_pin(): return jsonify({"ok": False})
    state.update({"text": "", "source": ""})
    return jsonify({"ok": True})

@app.route("/upload", methods=["POST"])
def upload():
    if not check_pin(): return jsonify({"ok": False, "error": "Wrong PIN"})
    data = request.get_json(force=True)
    name = Path(data.get("name", "file")).name  # strip any path traversal
    b64  = data.get("data", "")
    try:
        raw  = base64.b64decode(b64)
        dest = SAVE_DIR / name
        # Auto-rename if file exists
        counter = 1
        while dest.exists():
            stem = Path(name).stem
            suf  = Path(name).suffix
            dest = SAVE_DIR / f"{stem}_{counter}{suf}"
            counter += 1
        dest.write_bytes(raw)
        print(f"[FILE] Saved: {dest} ({len(raw)} bytes)")
        return jsonify({"ok": True, "path": str(dest)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/files")
def list_files():
    if not check_pin(): return jsonify({"ok": False, "error": "Wrong PIN"})
    files = []
    for f in sorted(SAVE_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file():
            files.append({"name": f.name, "size": f.stat().st_size})
    return jsonify({"files": files})

@app.route("/download/<filename>")
def download(filename):
    if not check_pin(): return "Unauthorized", 403
    path = SAVE_DIR / Path(filename).name
    if not path.exists(): return "Not found", 404
    return send_file(path, as_attachment=True)

@app.route("/history")
def history():
    if not check_pin(): return jsonify({"ok": False})
    return jsonify(HISTORY)

# ── PC Clipboard Watcher ────────────────────────────────────────
def watch_clipboard():
    if not HAS_CLIPBOARD: return
    last = ""
    import time
    while True:
        try:
            current = pyperclip.paste()
            if current and current != last and current != state.get("text", ""):
                last = current
                if state.get("source") != "phone" or current != state.get("text", ""):
                    state.update({"text": current, "source": "pc", "time": str(datetime.datetime.now())})
                    print(f"[AUTO] PC clipboard → phone ({len(current)} chars)")
        except: pass
        time.sleep(1.5)

# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    ip  = get_local_ip()
    url = f"http://{ip}:{PORT}"

    print("")
    print("  ╔══════════════════════════════════════╗")
    print("  ║        BRIDGE v2 — Phone ↔ PC        ║")
    print("  ╚══════════════════════════════════════╝")
    print("")
    print(f"  Open on your phone browser:")
    print(f"      {url}")
    print(f"")
    print(f"  Or scan the QR code at: {url}/qr")
    print(f"  (bookmark it — IP stays the same on hotspot)")
    print(f"")
    print(f"  HTTP  : ON  — works on all phones, no certificate warnings")
    print(f"  PIN   : {'ON' if PIN else 'OFF'}")
    print(f"  Files : {SAVE_DIR}")
    print(f"")
    print(f"  Ctrl+C to stop")
    print(f"  ─────────────────────────────────────────")
    print("")

    if HAS_CLIPBOARD:
        t = threading.Thread(target=watch_clipboard, daemon=True)
        t.start()

    try:
        import webbrowser
        webbrowser.open(url)
    except: pass

    app.run(host="0.0.0.0", port=PORT, debug=False)
