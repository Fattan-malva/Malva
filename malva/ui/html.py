"""
malva.ui.html — Floating pill page for Malva (single self-contained HTML string).

Contents:
  * CSS: solid black, monochrome palette; accents only for state.
  * Markup: compact statusbar + expandable panel (Chat, Transkrip, Catatan,
    Latihan, Setelan).
  * Script: defines every window.<name> function that app.py calls, and calls
    api.ui_ready() once the pywebview bridge is available.

Safety rules for this page:
  * Text from the transcript, the model, or the file system is written with
    textContent or esc(); innerHTML only receives escaped markup.
  * Markdown from the model is rendered with raw HTML and images disabled, and
    only http/https/mailto links are kept.

Spectrum: five real FFT band levels per source, pushed by Python (updateBars).

tests/test_ui_contract.py checks that every window function app.py calls is
defined here, that every api method the page calls exists on MalvaAPI, and that
the inline script parses (node --check).
"""

PILL_HTML = r"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<title>Malva</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
/* ==========================================================================
   RESET & SOLID BLACK THEME (No Glass, No Purple, Zero White Edges)
   ========================================================================== */
*, *::before, *::after {
  margin: 0; padding: 0; box-sizing: border-box;
}

:root {
  --bg-main: #000000;
  --bg-card: #0d0d0f;
  --bg-elevated: #16161a;
  --bg-hover: #1f1f24;

  --border-subtle: #222226;
  --border-strong: #33333a;

  --text-primary: #f8fafc;
  --text-secondary: #a1a1aa;
  --text-muted: #71717a;
  --text-faint: #3f3f46;

  --accent-green: #22c55e;
  --accent-cyan: #06b6d4;
  --accent-amber: #f59e0b;
  --accent-red: #ef4444;
}

html, body {
  width: 100%;
  height: 100%;
  overflow: hidden;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #000000;
  color: var(--text-primary);
  user-select: none;
  -webkit-user-select: none;
  font-size: 13px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

/* ==========================================================================
   PILL SHELL (Solid Pure Black)
   ========================================================================== */
#pill {
  width: 100%;
  height: 100%;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

#pill.compact #panel,
#pill.sleeping #panel {
  display: none !important;
}

/* ==========================================================================
   STATUS BAR
   ========================================================================== */
#statusbar {
  height: 54px;
  min-height: 54px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  cursor: default;
  flex-shrink: 0;
  background: var(--bg-main);
}

/* Drag Grip */
.drag-grip {
  width: 30px;
  height: 30px;
  border-radius: 6px;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
  flex-shrink: 0;
}
.drag-grip:active { cursor: grabbing; background: var(--bg-hover); }
.drag-grip svg { width: 14px; height: 14px; stroke: var(--text-secondary); }

/* Mode Chip */
.mode-chip {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  padding: 3px 9px;
  border-radius: 4px;
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
  transition: background 0.15s, border-color 0.15s;
}
.mode-chip:hover {
  background: var(--bg-hover);
  border-color: var(--border-strong);
}

.mode-option {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
  cursor: pointer;
  transition: background 0.1s;
}
.mode-option:hover {
  background: var(--bg-hover);
}
.mode-option svg {
  width: 16px;
  height: 16px;
  stroke: var(--text-secondary);
  flex-shrink: 0;
}

/* State Dot */
.state-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--text-faint);
  transition: background 0.2s, box-shadow 0.2s;
}
.state-dot.listening  { background: var(--accent-green); box-shadow: 0 0 8px rgba(34, 197, 94, 0.6); }
.state-dot.processing { background: var(--accent-amber); box-shadow: 0 0 8px rgba(245, 158, 11, 0.6); }
.state-dot.paused     { background: var(--text-muted); }
.state-dot.error      { background: var(--accent-red); box-shadow: 0 0 8px rgba(239, 68, 68, 0.6); }

/* Track Sources */
.track-sources {
  display: flex;
  gap: 5px;
  align-items: center;
  flex-shrink: 0;
}
.source-pill {
  font-size: 9.5px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 3px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  letter-spacing: 0.03em;
}
.source-pill svg { width: 10px; height: 10px; }
.source-pill.mic {
  background: rgba(239, 68, 68, 0.12);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.3);
}
.source-pill.sys {
  background: rgba(6, 182, 212, 0.12);
  color: #38bdf8;
  border: 1px solid rgba(6, 182, 212, 0.3);
}

/* Feature Badges */
.feature-badge {
  font-size: 9.5px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 3px;
  display: none;
  align-items: center;
  gap: 4px;
}
.feature-badge.show { display: inline-flex; }
.feature-badge.focus {
  background: rgba(34, 197, 94, 0.12);
  color: #4ade80;
  border: 1px solid rgba(34, 197, 94, 0.3);
}
.feature-badge.hidden-active {
  background: var(--bg-hover);
  color: #f1f5f9;
  border: 1px solid var(--border-strong);
}

/* ==========================================================================
   5-BAR LIVE SPECTRUM VISUALIZER
   ========================================================================== */
#spectrum {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 36px;
  margin-left: auto;
  padding: 0 6px;
  flex-shrink: 0;
}
#spectrum .bar {
  width: 4px;
  height: 6px;
  min-height: 6px;
  border-radius: 2px;
  background: var(--text-faint);
  transition: height 0.05s linear, background-color 0.15s ease;
}
#spectrum.listening .bar {
  background: linear-gradient(to top, var(--accent-green), var(--accent-cyan));
}
#spectrum.speaking .bar {
  background: linear-gradient(to top, var(--accent-red), var(--accent-amber));
}

/* Action Icon Buttons */
.btn-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-card);
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.btn-icon:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--border-strong);
}
.btn-icon svg {
  width: 13px;
  height: 13px;
  stroke: currentColor;
  stroke-width: 1.75;
  fill: none;
}
.btn-icon.danger {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.25);
  color: #f87171;
}
.btn-icon.danger:hover {
  background: rgba(239, 68, 68, 0.2);
  color: #ffffff;
}

#expandBtn svg {
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
#pill.expanded #expandBtn svg {
  transform: rotate(180deg);
}

/* ==========================================================================
   PANEL (Solid Black Surface)
   ========================================================================== */
#panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-main);
}

/* Tabs */
.tab-row {
  display: flex;
  padding: 6px 10px 0;
  gap: 3px;
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
  background: var(--bg-main);
}
.tab-btn {
  font-size: 11px;
  font-weight: 500;
  padding: 6px 12px;
  border-radius: 6px 6px 0 0;
  cursor: pointer;
  color: var(--text-muted);
  border: 1px solid transparent;
  border-bottom: none;
  background: transparent;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: color 0.15s, background-color 0.15s;
}
.tab-btn svg { width: 12px; height: 12px; stroke: currentColor; stroke-width: 1.75; fill: none; }
.tab-btn:hover { color: var(--text-secondary); }
.tab-btn.active {
  color: var(--text-primary);
  background: var(--bg-card);
  border-color: var(--border-subtle);
}

/* Tab Viewport */
.tab-viewport {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  background: var(--bg-main);
}
.tab-viewport::-webkit-scrollbar { width: 4px; }
.tab-viewport::-webkit-scrollbar-thumb { background: var(--bg-elevated); border-radius: 2px; }
.tab-viewport::-webkit-scrollbar-track { background: transparent; }

/* Markdown Answer Area */
#answerArea {
  font-size: 12.5px;
  line-height: 1.6;
  color: #e2e8f0;
  word-break: break-word;
}
#answerArea p { margin-bottom: 6px; }
#answerArea strong { color: #f8fafc; font-weight: 600; }
#answerArea code {
  font-family: 'JetBrains Mono', Consolas, monospace;
  background: var(--bg-card);
  color: #fcd34d;
  padding: 1px 4px;
  border-radius: 4px;
  font-size: 11px;
}
#answerArea pre {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-left: 3px solid var(--text-secondary);
  padding: 8px 10px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 6px 0;
}
#answerArea pre code { background: none; color: inherit; padding: 0; }
#answerArea ul, #answerArea ol { padding-left: 18px; margin-bottom: 6px; }
#answerArea li { margin-bottom: 2px; }

/* Spinner */
.spinner-row {
  display: none;
  align-items: center;
  gap: 7px;
  font-size: 11px;
  color: var(--text-muted);
  padding: 4px 0 8px;
}
.spinner-row.show { display: flex; }
.spinner {
  width: 13px;
  height: 13px;
  animation: spin 0.9s linear infinite;
  stroke: var(--accent-amber);
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Cards & Lists */
.card-item {
  padding: 8px 10px;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  margin-bottom: 6px;
  font-size: 12px;
}
.meta-tag {
  font-size: 9px;
  text-transform: uppercase;
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}

/* Settings */
.settings-section-title {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin: 10px 0 4px;
}
.setting-row {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.select-input {
  font-family: inherit;
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 5px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  color: var(--text-primary);
  outline: none;
}
.toggle-switch {
  font-family: inherit;
  font-size: 10px;
  font-weight: 500;
  padding: 3px 10px;
  border-radius: 4px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  color: var(--text-muted);
  cursor: pointer;
}
.toggle-switch.on {
  background: rgba(34, 197, 94, 0.15);
  border-color: rgba(34, 197, 94, 0.35);
  color: #4ade80;
}

/* Model Row */
.model-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.model-card.active-model {
  border-color: var(--border-strong);
  background: var(--bg-elevated);
}
.model-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.status-pill {
  font-size: 9px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 3px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.status-pill.cached {
  background: rgba(34, 197, 94, 0.12);
  color: #4ade80;
  border: 1px solid rgba(34, 197, 94, 0.25);
}
.status-pill.active {
  background: rgba(255, 255, 255, 0.1);
  color: #f1f5f9;
  border: 1px solid var(--border-strong);
}
.status-pill.downloading {
  background: rgba(245, 158, 11, 0.15);
  color: #fcd34d;
  border: 1px solid rgba(245, 158, 11, 0.3);
}
.btn-action {
  font-family: inherit;
  font-size: 10px;
  font-weight: 500;
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  color: var(--text-primary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.btn-action:hover { background: var(--bg-hover); border-color: var(--border-strong); }

/* Bottom Control Row */
#bottomControls {
  padding: 8px 12px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 7px;
  background: var(--bg-main);
  flex-shrink: 0;
}
.input-box {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
}
.chat-field {
  width: 100%;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 6px 30px 6px 10px;
  font-size: 12px;
  font-family: inherit;
  color: var(--text-primary);
  outline: none;
}
.chat-field:focus { border-color: var(--border-strong); }
.send-btn {
  position: absolute;
  right: 4px;
  width: 22px;
  height: 22px;
  border-radius: 4px;
  border: none;
  background: #ffffff;
  color: #000000;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.send-btn svg { width: 12px; height: 12px; stroke: #000000; stroke-width: 2; fill: none; }

/* Sleep Viewport */
#sleepViewport {
  display: none;
  width: 100%;
  height: 100%;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  background: #000000;
}
#pill.sleeping #sleepViewport { display: flex; }
#pill.sleeping #statusbar { display: none !important; }
.moon-icon { width: 14px; height: 14px; stroke: var(--text-muted); fill: none; stroke-width: 1.75; }
/* ==========================================================================
   ADDITIONS (v2): notices, pending actions, quick controls, mode panels.
   Same solid-black palette and typography as the rest of the pill.
   ========================================================================== */
[hidden] { display: none !important; }

.btn-icon.active-toggle {
  background: rgba(34, 197, 94, 0.12);
  border-color: rgba(34, 197, 94, 0.35);
  color: #4ade80;
}
.btn-icon.sleep-btn svg { stroke-width: 1.75; }

.quick-chip {
  font-family: inherit;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.03em;
  padding: 4px 9px;
  border-radius: 5px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-card);
  color: var(--text-secondary);
  cursor: pointer;
  flex-shrink: 0;
  white-space: nowrap;
}
.quick-chip:hover { background: var(--bg-hover); color: var(--text-primary); }
.quick-chip.on {
  background: rgba(34, 197, 94, 0.12);
  border-color: rgba(34, 197, 94, 0.35);
  color: #4ade80;
}

/* Notice bar: one line of status above the input row */
#noticeBar {
  display: none;
  padding: 6px 12px;
  font-size: 11px;
  line-height: 1.4;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-card);
  color: var(--text-secondary);
  cursor: pointer;
  flex-shrink: 0;
}
#noticeBar.show { display: flex; align-items: center; gap: 8px; }
#noticeBar.info    { color: var(--text-secondary); }
#noticeBar.warning { color: #fcd34d; background: rgba(245, 158, 11, 0.07); }
#noticeBar.error   { color: #fca5a5; background: rgba(239, 68, 68, 0.08); }
#noticeText { flex: 1; min-width: 0; }
.notice-actions { display: flex; gap: 6px; flex-shrink: 0; }

/* Shared small buttons */
.btn-small {
  font-family: inherit;
  font-size: 10.5px;
  font-weight: 500;
  padding: 4px 9px;
  border-radius: 5px;
  border: 1px solid var(--border-strong);
  background: var(--bg-elevated);
  color: var(--text-primary);
  cursor: pointer;
  white-space: nowrap;
}
.btn-small:hover { background: var(--bg-hover); }
.btn-small.primary { background: #ffffff; color: #000000; border-color: #ffffff; }
.btn-small.primary:hover { background: #e4e4e7; }
.btn-small.ghost { background: transparent; border-color: var(--border-subtle); color: var(--text-secondary); }
.btn-small:disabled { opacity: 0.45; cursor: default; }

.section-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin: 12px 0 6px;
}
.section-label:first-child { margin-top: 0; }
.muted { font-size: 11px; color: var(--text-muted); }

/* Pending actions (speech never runs an action without approval) */
.pending-card {
  border: 1px solid var(--border-strong);
  border-left: 3px solid var(--accent-amber);
  border-radius: 6px;
  background: var(--bg-card);
  padding: 8px 10px;
  margin-bottom: 8px;
  font-size: 12px;
}
.pending-card .pending-title { font-weight: 600; color: var(--text-primary); margin-bottom: 2px; }
.pending-card .pending-args {
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 10.5px;
  color: var(--text-secondary);
  word-break: break-all;
  margin-bottom: 6px;
}
.pending-card .pending-origin { font-size: 10px; color: var(--text-muted); margin-bottom: 6px; }
.pending-card .pending-buttons { display: flex; gap: 6px; }
.pending-card.done { border-left-color: var(--text-faint); opacity: 0.8; }

/* Voice input cards */
.voice-card {
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  background: var(--bg-card);
  padding: 8px 10px;
  margin-bottom: 8px;
  font-size: 12.5px;
  color: #f1f5f9;
}
.voice-card .voice-buttons { display: flex; gap: 6px; margin-top: 6px; justify-content: flex-end; }

/* Mode-specific panels */
.panel-block {
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  background: var(--bg-card);
  padding: 10px;
  margin-bottom: 10px;
}
.panel-block h4 {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}
.field-row { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; }
.text-field {
  flex: 1;
  min-width: 120px;
  font-family: inherit;
  font-size: 12px;
  padding: 5px 8px;
  border-radius: 5px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
  outline: none;
}
.text-field:focus { border-color: var(--border-strong); }
.question-text { font-size: 13px; color: #f8fafc; line-height: 1.5; margin-bottom: 4px; }
.draft-text {
  font-size: 12px;
  color: var(--text-secondary);
  min-height: 34px;
  white-space: pre-wrap;
  word-break: break-word;
  border-left: 2px solid var(--border-strong);
  padding-left: 8px;
  margin: 6px 0;
}
.feedback-item { border-top: 1px solid var(--border-subtle); padding-top: 8px; margin-top: 8px; font-size: 12px; }
.feedback-item:first-child { border-top: none; margin-top: 0; padding-top: 0; }
.feedback-item .fb-q { color: var(--text-secondary); font-size: 11px; margin-bottom: 3px; }
.feedback-item .fb-a { color: #e2e8f0; margin-bottom: 4px; white-space: pre-wrap; }
.summary-text { font-size: 12.5px; line-height: 1.6; color: #e2e8f0; }
.summary-text p { margin-bottom: 6px; }
.summary-text ul, .summary-text ol { padding-left: 18px; margin-bottom: 6px; }
.report-section + .report-section { margin-top: 12px; }
.report-section h5 {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.report-list { padding-left: 16px; font-size: 12px; color: #e2e8f0; }
.report-list li { margin-bottom: 4px; }
details.transcript-full { margin-top: 8px; font-size: 11px; color: var(--text-secondary); }
details.transcript-full summary { cursor: pointer; color: var(--text-muted); }
details.transcript-full pre { white-space: pre-wrap; font-family: 'JetBrains Mono', Consolas, monospace; font-size: 10.5px; margin-top: 6px; }

/* Privacy block */
.privacy-status { font-size: 11px; color: var(--text-secondary); line-height: 1.5; }
.privacy-status strong { color: var(--text-primary); }
.privacy-warning { color: #fcd34d; }
.seg-text { color: #f1f5f9; line-height: 1.4; }
.pywebview-drag-region { cursor: move; }
.live-line {
  font-size: 12.5px;
  line-height: 1.45;
  color: var(--text-secondary);
  font-style: italic;
  padding: 6px 8px;
  margin-bottom: 8px;
  border-left: 2px solid #22c55e;
  background: var(--bg-card);
  border-radius: 0 5px 5px 0;
  word-break: break-word;
}
.live-line[hidden] { display: none; }
</style>
</head>
<body>

<div id="pill" class="compact">

  <!-- SLEEP WIDGET (175px solid black strip) -->
  <div id="sleepViewport" class="pywebview-drag-region" title="Klik untuk membangunkan Malva. Seret untuk memindahkan." onclick="window._wake()">
    <svg class="moon-icon" viewBox="0 0 24 24"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>
    <span style="font-size:11px;font-weight:500;color:var(--text-muted)">Malva Tertidur</span>
  </div>

  <!-- STATUSBAR -->
  <div id="statusbar" class="pywebview-drag-region">
    <div class="drag-grip" id="dragGrip" title="Seret untuk memindahkan">
      <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M5 9h14M5 15h14"/></svg>
    </div>

    <span id="modeChip" class="mode-chip" onclick="window._toggleModeDropdown(event)" style="cursor:pointer;position:relative" title="Ganti mode">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="m4.93 4.93 4.24 4.24"/><path d="m14.83 9.17 4.24-4.24"/><path d="m14.83 14.83 4.24 4.24"/><path d="m9.17 14.83-4.24 4.24"/></svg>
      <span id="modeText">Asisten</span>
      <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
    </span>

    <div id="modeDropdown" style="display:none;position:absolute;top:50px;left:42px;z-index:9999;background:var(--bg-elevated);border:1px solid var(--border-strong);border-radius:8px;min-width:200px;box-shadow:0 8px 24px rgba(0,0,0,0.6);overflow:hidden">
      <div class="mode-option" onclick="window._selectMode('assistant')" data-mode="assistant">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="m4.93 4.93 4.24 4.24"/></svg>
        <span>Asisten Umum</span>
      </div>
      <div class="mode-option" onclick="window._selectMode('meeting')" data-mode="meeting">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/></svg>
        <span>Meeting Intelligence</span>
      </div>
      <div class="mode-option" onclick="window._selectMode('interview_practice')" data-mode="interview_practice">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
        <span>Latihan Wawancara</span>
      </div>
      <div class="mode-option" onclick="window._selectMode('interview_notes')" data-mode="interview_notes">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        <span>Catatan Wawancara</span>
      </div>
      <div class="mode-option" onclick="window._selectMode('voice_input')" data-mode="voice_input">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg>
        <span>Input Suara Saja</span>
      </div>
    </div>

    <div id="stateDot" class="state-dot" title="Status sesi"></div>

    <div class="track-sources">
      <span id="badgeMic" class="source-pill mic" style="display:none" title="Mikrofon aktif">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/></svg>
        MIC
      </span>
      <span id="badgeSys" class="source-pill sys" style="display:none" title="Audio sistem aktif">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
        SYS
      </span>
    </div>

    <span id="badgeFocus" class="feature-badge focus" title="Focus Mode aktif">FOKUS</span>
    <span id="badgeHidden" class="feature-badge hidden-active" title="Capture exclusion">HIDDEN</span>

    <div id="spectrum" class="listening" title="Level audio real-time dari sumber aktif">
      <div class="bar"></div>
      <div class="bar"></div>
      <div class="bar"></div>
      <div class="bar"></div>
      <div class="bar"></div>
    </div>

    <button id="sleepBtn" class="btn-icon sleep-btn" onclick="window._requestSleep()" title="Tidurkan Malva (jeda capture)">
      <svg viewBox="0 0 24 24"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>
    </button>

    <button id="expandBtn" class="btn-icon" onclick="window._togglePanel()" title="Buka / tutup panel">
      <svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>
    </button>
  </div>

  <!-- EXPANDED PANEL -->
  <div id="panel">

    <div class="tab-row" role="tablist">
      <button class="tab-btn active" onclick="window._showTab('chat')" data-tab="chat">Chat</button>
      <button class="tab-btn" onclick="window._showTab('transcript')" data-tab="transcript">Transkrip</button>
      <button class="tab-btn" onclick="window._showTab('notes')" data-tab="notes">Catatan</button>
      <button id="tabPractice" class="tab-btn" onclick="window._showTab('practice')" data-tab="practice" hidden>Latihan</button>
      <button class="tab-btn" onclick="window._showTab('settings')" data-tab="settings">Setelan</button>
    </div>

    <div id="tabContent" class="tab-viewport">

      <!-- CHAT / ASSISTANT / VOICE INPUT -->
      <div id="viewChat">
        <div id="spinnerRow" class="spinner-row">
          <svg class="spinner" viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
          <span id="spinnerLabel">Memproses…</span>
        </div>
        <div id="liveLine" class="live-line" hidden></div>
        <div id="pendingArea"></div>
        <div id="voiceArea"></div>
        <div id="answerArea"></div>
      </div>

      <!-- TRANSKRIP -->
      <div id="viewTranscript" style="display:none">
        <div id="liveLineT" class="live-line" hidden></div>
        <div id="transcriptList" data-empty="1">
          <div class="muted" style="text-align:center;padding:24px 0">Belum ada transkrip pada sesi ini.</div>
        </div>
      </div>

      <!-- CATATAN: meeting summary, decisions, action items, reports -->
      <div id="viewNotes" style="display:none">
        <div id="meetingReportArea">
          <div class="muted" style="padding:4px 0">Ringkasan meeting muncul di sini setelah sesi Meeting berhenti.</div>
        </div>
        <div id="reportArea"></div>
      </div>

      <!-- LATIHAN WAWANCARA -->
      <div id="viewPractice" style="display:none">
        <div class="panel-block">
          <h4>Latihan Wawancara</h4>
          <div class="field-row">
            <input id="practiceTopic" class="text-field" type="text" placeholder="Topik, mis. backend Java" autocomplete="off">
            <select id="practiceType" class="select-input">
              <option value="behavioral">Behavioral</option>
              <option value="technical">Teknis</option>
              <option value="coding">Coding</option>
              <option value="situational">Situasional</option>
            </select>
          </div>
          <div class="field-row">
            <button class="btn-small primary" onclick="window._startPractice()">Mulai pertanyaan</button>
            <span class="muted">Jawab lewat mikrofon, lalu tekan Selesai menjawab.</span>
          </div>
        </div>

        <div class="panel-block" id="practiceCurrent" hidden>
          <div class="muted" id="practiceQuestionNo" style="margin-bottom:4px"></div>
          <div class="question-text" id="practiceQuestion"></div>
          <div class="section-label">Jawaban Anda (live)</div>
          <div class="draft-text" id="practiceDraft">Belum ada jawaban terekam.</div>
          <div class="field-row">
            <button id="practiceSubmit" class="btn-small primary" onclick="window._submitAnswer()">Selesai menjawab</button>
            <button id="practiceNext" class="btn-small" onclick="window._nextQuestion()">Pertanyaan berikutnya</button>
            <button id="practiceFinish" class="btn-small ghost" onclick="window._finishPractice()">Akhiri &amp; buat laporan</button>
          </div>
        </div>

        <div class="section-label">Umpan balik</div>
        <div id="feedbackList"><div class="muted">Belum ada umpan balik.</div></div>
      </div>

      <!-- SETELAN -->
      <div id="viewSettings" style="display:none">

        <div class="settings-section-title">Mode operasi</div>
        <div class="setting-row">
          <div>
            <div style="font-size:12px;font-weight:500">Profil sesi</div>
            <div class="muted">Sumber audio mengikuti profil</div>
          </div>
          <select id="modeSelect" class="select-input" onchange="window._changeMode(this.value)">
            <option value="assistant">Asisten Umum</option>
            <option value="meeting">Meeting Intelligence</option>
            <option value="interview_practice">Latihan Wawancara</option>
            <option value="interview_notes">Catatan Wawancara</option>
            <option value="voice_input">Input Suara Saja</option>
          </select>
        </div>

        <div class="settings-section-title">Bahasa pengenalan ucapan</div>
        <div class="setting-row">
          <div>
            <div style="font-size:12px;font-weight:500">Mode bahasa</div>
            <div class="muted">Auto mendeteksi per ucapan; Manual mengunci bahasa</div>
          </div>
          <select id="langSelect" class="select-input" onchange="window.pywebview.api.set_asr_language(this.value)">
            <option value="auto">Auto</option>
            <option value="id">Bahasa Indonesia</option>
            <option value="en">English</option>
          </select>
        </div>

        <div class="settings-section-title">Model ASR lokal (Whisper)</div>
        <div id="modelsContainer"></div>
        <div id="asrGlobalStatus" class="muted" style="margin:4px 0 10px"></div>

        <div class="settings-section-title">Privasi</div>
        <div class="setting-row" style="align-items:flex-start">
          <div style="flex:1">
            <div style="font-size:12px;font-weight:500">Izinkan cloud</div>
            <div id="cloudStatus" class="privacy-status" style="margin-top:3px"></div>
          </div>
          <button id="cloudToggleBtn" class="toggle-switch" onclick="window._toggleCloud()">Nonaktif</button>
        </div>

        <div class="settings-section-title">Kontrol sesi</div>
        <div class="setting-row">
          <div>
            <div style="font-size:12px;font-weight:500">Focus Mode</div>
            <div class="muted">Jaga sesi tetap aktif dan cegah tidur otomatis</div>
          </div>
          <button id="focusToggleBtn" class="toggle-switch" onclick="window._toggleFocus()">Nonaktif</button>
        </div>
        <div class="setting-row">
          <div>
            <div style="font-size:12px;font-weight:500">Hidden Mode</div>
            <div id="hiddenStatusText" class="muted">Nonaktif</div>
          </div>
          <button id="hiddenToggleBtn" class="toggle-switch" onclick="window._toggleHidden()">Nonaktif</button>
        </div>
        <div class="setting-row">
          <div>
            <div style="font-size:12px;font-weight:500">Audio sistem</div>
            <div class="muted">Loopback WASAPI, track terpisah dari mikrofon</div>
          </div>
          <button id="sysAudioToggleBtn" class="toggle-switch" onclick="window._toggleSysAudio()">Nonaktif</button>
        </div>

      </div>

    </div>

    <div id="noticeBar"><span id="noticeText"></span><span class="notice-actions" id="noticeActions"></span></div>

    <div id="bottomControls">
      <div class="input-box">
        <input id="chatInput" type="text" class="chat-field"
               placeholder="Ketik instruksi atau pertanyaan…"
               onkeydown="if(event.key==='Enter')window._submitText()" autocomplete="off">
        <button class="send-btn" onclick="window._submitText()" title="Kirim">
          <svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
        </button>
      </div>

      <button id="focusQuick" class="quick-chip" onclick="window._toggleFocus()" title="Focus Mode: jaga sesi tetap aktif">FOKUS</button>

      <button id="pauseBtn" class="btn-icon" onclick="window._togglePause()" title="Jeda / lanjutkan audio">
        <svg id="pauseIcon" viewBox="0 0 24 24"><rect width="4" height="16" x="6" y="4" rx="1"/><rect width="4" height="16" x="14" y="4" rx="1"/></svg>
      </button>

      <button class="btn-icon danger" onclick="window._emergencyStop()" title="Hentikan sesi">
        <svg viewBox="0 0 24 24"><rect width="14" height="14" x="5" y="5" rx="2"/></svg>
      </button>
    </div>

  </div>

</div>

<script>
// ==========================================================================
// STATE & HELPERS
// ==========================================================================
const S = {
  mode: 'assistant', state: 'idle', expanded: false, sleeping: false, paused: false,
  focusMode: false, hiddenStatus: 'disabled', sources: [], sourceStates: {}, sysAudio: false,
  cloud: false, answerRaw: '', modelsCatalog: [], activeModelInfo: {}, practiceQuestion: ''
};

const $ = (id) => document.getElementById(id);
const pill = $('pill'), stateDot = $('stateDot'), modeText = $('modeText');
const badgeMic = $('badgeMic'), badgeSys = $('badgeSys'), badgeFocus = $('badgeFocus'), badgeHidden = $('badgeHidden');
const answerArea = $('answerArea'), spinnerRow = $('spinnerRow'), spinnerLabel = $('spinnerLabel');
const transcriptList = $('transcriptList'), spectrum = $('spectrum'), bars = spectrum.querySelectorAll('.bar');
const expandBtn = $('expandBtn'), noticeBar = $('noticeBar'), noticeText = $('noticeText'), noticeActions = $('noticeActions');
const pendingArea = $('pendingArea'), voiceArea = $('voiceArea'), tabContent = $('tabContent');
const modelsContainer = $('modelsContainer'), asrGlobalStatus = $('asrGlobalStatus'), pauseIcon = $('pauseIcon');

function esc(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

// Markdown from the model is rendered with raw HTML, images and non-web links
// disabled, so model output can never run script inside the pill.
function renderMarkdown(text) {
  const raw = String(text == null ? '' : text);
  if (typeof marked !== 'undefined') {
    try {
      if (!renderMarkdown._ready) {
        marked.use({
          renderer: {
            html(token) { return esc(typeof token === 'string' ? token : (token.text || token.raw || '')); },
            image(token) { return esc(typeof token === 'string' ? token : (token.text || '')); },
            link(token) {
              const href = typeof token === 'string' ? token : (token.href || '');
              const label = typeof token === 'string' ? arguments[2] : (token.text || href);
              if (!/^(https?:|mailto:)/i.test(href)) return esc(label || '');
              return '<a href="' + esc(href) + '" rel="noopener">' + esc(label || href) + '</a>';
            }
          }
        });
        renderMarkdown._ready = true;
      }
      return marked.parse(raw);
    } catch (e) { /* fall through to plain text */ }
  }
  return esc(raw).replace(/\n/g, '<br>');
}

function api() { return (window.pywebview && window.pywebview.api) ? window.pywebview.api : null; }

function call(method, ...args) {
  const a = api();
  if (!a || typeof a[method] !== 'function') {
    showNotice('error', 'Jembatan Malva belum siap. Coba lagi sebentar lagi.');
    return undefined;
  }
  try {
    const result = a[method](...args);
    if (result && typeof result.catch === 'function') {
      result.catch((err) => showNotice('error', String(err)));
    }
    return result;
  } catch (err) {
    showNotice('error', String(err));
    return undefined;
  }
}

// ==========================================================================
// NOTICES (one line above the controls; errors stay until dismissed)
// ==========================================================================
let _noticeTimer = null;

function hideNotice() {
  clearTimeout(_noticeTimer);
  noticeBar.className = '';
  noticeActions.innerHTML = '';
}

window.showNotice = function(kind, message, actions) {
  if (!message) return;
  clearTimeout(_noticeTimer);
  noticeBar.className = 'show ' + (kind || 'info');
  noticeText.textContent = message;
  noticeActions.innerHTML = '';
  if (actions && actions.length) {
    actions.forEach((a) => {
      const b = document.createElement('button');
      b.className = 'btn-small' + (a.primary ? ' primary' : ' ghost');
      b.textContent = a.label;
      b.onclick = (e) => { e.stopPropagation(); hideNotice(); a.onClick(); };
      noticeActions.appendChild(b);
    });
  } else {
    if (kind === 'info') _noticeTimer = setTimeout(hideNotice, 6000);
    if (kind === 'warning') _noticeTimer = setTimeout(hideNotice, 12000);
  }
  if (kind === 'error') expandBtn.style.boxShadow = '0 0 0 2px rgba(239,68,68,0.6)';
};

noticeText.addEventListener('click', hideNotice);

// ==========================================================================
// 5-BAR SPECTRUM — real band levels from Python, tagged by source
// ==========================================================================
const sourceLevels = {};

function paintBars() {
  const combined = [0, 0, 0, 0, 0];
  Object.keys(sourceLevels).forEach((src) => {
    if (!S.sources.includes(src)) return;
    sourceLevels[src].forEach((v, i) => { if (v > combined[i]) combined[i] = v; });
  });
  let loud = false;
  for (let i = 0; i < bars.length; i++) {
    bars[i].style.height = (6 + combined[i] * 26).toFixed(1) + 'px';
    if (combined[i] > 0.12) loud = true;
  }
  spectrum.classList.toggle('speaking', loud);
}

function resetBars() {
  Object.keys(sourceLevels).forEach((k) => delete sourceLevels[k]);
  paintBars();
}

window.updateBars = function(source, levels) {
  if (!Array.isArray(levels) || levels.length !== 5) return;
  sourceLevels[source] = levels.map((v) => {
    const n = Number(v);
    return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : 0;
  });
  paintBars();
};

// ==========================================================================
// PANEL / TABS / MODE CHIP
// ==========================================================================
window._togglePanel = function() {
  S.expanded = !S.expanded;
  pill.classList.toggle('expanded', S.expanded);
  pill.classList.toggle('compact', !S.expanded);
  if (S.expanded) expandBtn.style.boxShadow = '';
  call('set_panel_state', S.expanded ? 'expanded' : 'compact');
};

window._showTab = function(name) {
  const views = { chat: 'viewChat', transcript: 'viewTranscript', notes: 'viewNotes', practice: 'viewPractice', settings: 'viewSettings' };
  document.querySelectorAll('.tab-btn').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  Object.keys(views).forEach((k) => { $(views[k]).style.display = k === name ? '' : 'none'; });
};

window._toggleModeDropdown = function(e) {
  if (e) e.stopPropagation();
  const d = $('modeDropdown');
  d.style.display = d.style.display === 'block' ? 'none' : 'block';
};

document.addEventListener('click', (e) => {
  const d = $('modeDropdown');
  if (d && d.style.display === 'block' && !d.contains(e.target)) d.style.display = 'none';
});

window._selectMode = function(mode) {
  $('modeDropdown').style.display = 'none';
  call('change_mode', mode);
};

window._changeMode = function(mode) { call('change_mode', mode); };

window.updateMode = function(mode) {
  S.mode = mode;
  const labels = {
    assistant: 'Asisten', meeting: 'Meeting', interview_practice: 'Latihan Wawancara',
    interview_notes: 'Catatan Wawancara', voice_input: 'Input Suara'
  };
  modeText.textContent = labels[mode] || mode;
  document.querySelectorAll('#modeDropdown .mode-option').forEach((opt) => {
    opt.style.background = opt.dataset.mode === mode ? 'var(--bg-hover)' : '';
  });
  $('modeSelect').value = mode;
  $('tabPractice').hidden = mode !== 'interview_practice';
  if (mode !== 'interview_practice') $('viewPractice').style.display = 'none';
  $('sysAudioToggleBtn').disabled = (mode === 'voice_input' || mode === 'interview_practice');
};

// ==========================================================================
// SESSION STATE
// ==========================================================================
window.updateState = function(state) {
  const prev = S.state;
  S.state = state;
  stateDot.className = 'state-dot ' + state;
  spectrum.classList.toggle('listening', state === 'listening');
  spinnerRow.classList.toggle('show', state === 'processing');
  S.paused = state === 'paused';
  pauseIcon.innerHTML = S.paused
    ? '<polygon points="5 3 19 12 5 21 5 3"/>'
    : '<rect width="4" height="16" x="6" y="4" rx="1"/><rect width="4" height="16" x="14" y="4" rx="1"/>';
  if (state === 'paused' || state === 'sleeping' || state === 'idle' || state === 'error') resetBars();
  if (state === 'listening' && prev !== 'listening') _spawnFx();
};

window.onSessionStarted = function(p) {
  window.updateSourceStates({ states: (p && p.source_states) || {}, active: (p && p.sources) || [] });
};

window.updateSourceStates = function(p) {
  p = p || {};
  const states = p.states || {};
  const active = Array.isArray(p.active)
    ? p.active
    : Object.keys(states).filter((k) => states[k] === 'active' || states[k] === 'paused');
  S.sources = active;
  S.sourceStates = states;
  badgeMic.style.display = active.includes('microphone') ? 'inline-flex' : 'none';
  badgeSys.style.display = active.includes('system_audio') ? 'inline-flex' : 'none';
  S.sysAudio = active.includes('system_audio');
  const b = $('sysAudioToggleBtn');
  b.textContent = S.sysAudio ? 'Aktif' : 'Nonaktif';
  b.className = S.sysAudio ? 'toggle-switch on' : 'toggle-switch';
  Object.keys(sourceLevels).forEach((src) => { if (!active.includes(src)) delete sourceLevels[src]; });
  paintBars();
};

window.onSessionEnded = function() {
  spinnerRow.classList.remove('show');
  S.sources = [];
  resetBars();
  window.updateState('idle');
  showNotice('info', 'Sesi dihentikan. Laporan dibuat di tab Catatan bila tersedia.');
};

window._togglePause = function() {
  call(S.paused ? 'resume_session' : 'pause_session');
};

window._emergencyStop = function() {
  call('emergency_stop');
  spinnerRow.classList.remove('show');
};

window._toggleSysAudio = function() {
  call(S.sysAudio ? 'disable_system_audio' : 'enable_system_audio');
};

// ==========================================================================
// SLEEP / FOCUS / HIDDEN / PRIVACY
// ==========================================================================
window.setSleeping = function(isSleeping) {
  S.sleeping = !!isSleeping;
  pill.classList.toggle('sleeping', S.sleeping);
  if (S.sleeping) {
    pill.classList.remove('expanded');
    pill.classList.add('compact');
    S.expanded = false;
    resetBars();
  }
};

window._requestSleep = function() {
  const result = call('sleep_now', false);
  if (result && typeof result.then === 'function') {
    result.then((res) => {
      if (res && res.status === 'needs_confirmation') {
        showNotice('warning', res.message, [
          { label: 'Tidurkan', primary: true, onClick: () => call('sleep_now', true) },
          { label: 'Batal', primary: false, onClick: () => {} }
        ]);
      }
    }).catch(() => {});
  }
};

window._wake = function() { call('wake_from_sleep'); };

window.updateFocusMode = function(active) {
  S.focusMode = !!active;
  badgeFocus.classList.toggle('show', S.focusMode);
  const q = $('focusQuick');
  q.classList.toggle('on', S.focusMode);
  q.textContent = S.focusMode ? 'FOKUS ON' : 'FOKUS';
  const b = $('focusToggleBtn');
  b.textContent = S.focusMode ? 'Aktif' : 'Nonaktif';
  b.className = S.focusMode ? 'toggle-switch on' : 'toggle-switch';
};

window._toggleFocus = function() {
  call(S.focusMode ? 'disable_focus_mode' : 'enable_focus_mode');
};

const HIDDEN_LABELS = {
  active: 'Capture Exclusion Aktif',
  unsupported: 'Tidak didukung di Windows ini',
  failed: 'Gagal diterapkan',
  disabled: 'Nonaktif'
};

window.updateHiddenMode = function(status) {
  S.hiddenStatus = status;
  const on = status === 'active';
  badgeHidden.classList.toggle('show', on);
  const b = $('hiddenToggleBtn');
  b.textContent = on ? 'Aktif' : 'Nonaktif';
  b.className = on ? 'toggle-switch on' : 'toggle-switch';
  $('hiddenStatusText').textContent = HIDDEN_LABELS[status] || status;
};

window._toggleHidden = function() {
  call(S.hiddenStatus === 'active' ? 'disable_hidden_mode' : 'enable_hidden_mode');
};

window.updatePrivacy = function(p) {
  S.cloud = !!(p && p.cloud_processing);
  $('cloudStatus').innerHTML = S.cloud
    ? '<strong>Cloud diizinkan.</strong> <span class="privacy-warning">Audio dan transkrip bisa dikirim ke Google Speech dan endpoint AI jarak jauh.</span>'
    : '<strong>Lokal saja.</strong> Audio dan teks tidak dikirim ke luar komputer ini.';
  const b = $('cloudToggleBtn');
  b.textContent = S.cloud ? 'Aktif' : 'Nonaktif';
  b.className = S.cloud ? 'toggle-switch on' : 'toggle-switch';
};

window._toggleCloud = function() {
  if (S.cloud) { call('set_cloud_processing', false); return; }
  showNotice('warning', 'Aktifkan cloud? Audio dan teks bisa dikirim ke layanan pihak ketiga.', [
    { label: 'Aktifkan', primary: true, onClick: () => call('set_cloud_processing', true) },
    { label: 'Batal', primary: false, onClick: () => {} }
  ]);
};

// ==========================================================================
// SOUND CUES (WebAudio; no external files)
// ==========================================================================
let _audioCtx = null, _wasListening = false;
function _audio() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!_audioCtx && Ctx) _audioCtx = new Ctx();
    if (_audioCtx && _audioCtx.state === 'suspended') _audioCtx.resume();
    return _audioCtx;
  } catch (_) { return null; }
}
function _tone(freq, end, delay, duration, gain, type) {
  const c = _audio(); if (!c) return;
  const t = c.currentTime + delay, o = c.createOscillator(), g = c.createGain();
  o.type = type || 'sine';
  o.frequency.setValueAtTime(freq, t);
  if (end) o.frequency.exponentialRampToValueAtTime(end, t + duration);
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(gain, t + 0.03);
  g.gain.exponentialRampToValueAtTime(0.0001, t + duration);
  o.connect(g); g.connect(c.destination);
  o.start(t); o.stop(t + duration + 0.05);
}
function _spawnFx() { if (!_wasListening) { _tone(260, 1400, 0, 0.42, 0.10, 'sine'); _tone(390, 2100, 0, 0.42, 0.04, 'triangle'); } _wasListening = true; }
function _completeFx() { _tone(1047, 0, 0, 0.22, 0.12); _tone(1568, 0, 0.12, 0.32, 0.14); }
document.addEventListener('pointerdown', () => { _audio(); }, true);

// ==========================================================================
// CHAT / ASSISTANT
// ==========================================================================
window._submitText = function() {
  const input = $('chatInput');
  const val = (input.value || '').trim();
  if (!val) return;
  input.value = '';
  window._showTab('chat');
  call('send_text', val);
};

window.startAnswer = function() {
  S.answerRaw = '';
  answerArea.innerHTML = '<span class="muted">…</span>';
};

window.appendAnswer = function(chunk) {
  S.answerRaw += String(chunk || '');
  answerArea.innerHTML = renderMarkdown(S.answerRaw);
  tabContent.scrollTop = tabContent.scrollHeight;
};

window.endAnswer = function() {
  answerArea.innerHTML = renderMarkdown(S.answerRaw);
  if (S.answerRaw) _completeFx();
  tabContent.scrollTop = tabContent.scrollHeight;
};

// Pending actions from speech: nothing runs until the user approves.
window.addPendingAction = function(a) {
  if (!a || !a.id) return;
  const card = document.createElement('div');
  card.className = 'pending-card';
  card.dataset.id = a.id;
  card.innerHTML =
    '<div class="pending-title">Usulan aksi: ' + esc(a.tool) + '</div>' +
    '<div class="pending-origin">' + (a.origin === 'speech' ? 'Dari ucapan. Perlu persetujuan Anda.' : 'Dari instruksi Anda.') + '</div>' +
    '<div class="pending-args">' + esc(JSON.stringify(a.args || {})) + '</div>' +
    '<div class="pending-buttons">' +
      '<button class="btn-small primary" data-act="ok">Jalankan</button>' +
      '<button class="btn-small ghost" data-act="no">Batalkan</button>' +
    '</div>';
  card.querySelector('[data-act="ok"]').onclick = function() {
    this.disabled = true; call('approve_action', a.id);
  };
  card.querySelector('[data-act="no"]').onclick = function() { call('reject_action', a.id); };
  pendingArea.prepend(card);
  window._showTab('chat');
};

window.resolvePendingAction = function(r) {
  const card = Array.from(pendingArea.children).find((el) => el.dataset.id === String(r.id));
  if (!card) return;
  card.classList.add('done');
  card.querySelector('.pending-buttons').innerHTML =
    '<span class="muted">' + esc(r.message || (r.ok ? 'Selesai' : 'Gagal')) + '</span>';
  setTimeout(() => card.remove(), 8000);
};

function copyText(text, btn) {
  const done = () => {
    btn.textContent = 'Tersalin';
    setTimeout(() => { btn.textContent = 'Salin'; }, 1500);
  };
  const fallback = () => {
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
    ta.remove();
    if (ok) done(); else showNotice('error', 'Gagal menyalin teks.');
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(fallback);
  } else {
    fallback();
  }
}

// Voice Input: recognised text, copy only (no automatic insertion into other apps).
window.showVoiceText = function(text) {
  if (!text) return;
  const card = document.createElement('div');
  card.className = 'voice-card';
  const body = document.createElement('div');
  body.textContent = text;
  const row = document.createElement('div');
  row.className = 'voice-buttons';
  const copy = document.createElement('button');
  copy.className = 'btn-small primary';
  copy.textContent = 'Salin';
  copy.onclick = () => copyText(text, copy);
  const del = document.createElement('button');
  del.className = 'btn-small ghost';
  del.textContent = 'Hapus';
  del.onclick = () => card.remove();
  row.append(copy, del);
  card.append(body, row);
  voiceArea.prepend(card);
  while (voiceArea.children.length > 20) voiceArea.lastElementChild.remove();
};

// ==========================================================================
// TRANSCRIPT
// ==========================================================================
// Live text: one line per panel, replaced on every update, cleared when the final
// segment for that source is ingested (the backend sends an empty text).
window.showPartialTranscript = function(source, text) {
  const t = String(text || '');
  const label = source === 'system_audio' ? 'SYS' : (source === 'microphone' ? 'MIC' : '');
  document.querySelectorAll('.live-line').forEach((el) => {
    el.textContent = '';
    if (t) {
      if (label) {
        const tag = document.createElement('span');
        tag.className = 'meta-tag';
        tag.textContent = label;
        el.append(tag, ' ');
      }
      el.append(document.createTextNode(t));
    }
    el.hidden = !t;
  });
};

window.addTranscriptSegment = function(seg) {
  if (!seg || !seg.text) return;
  if (transcriptList.dataset.empty === '1') {
    transcriptList.innerHTML = '';
    transcriptList.dataset.empty = '0';
  }
  const when = seg.timestamp ? new Date(seg.timestamp * 1000) : new Date();
  const timeStr = when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const src = seg.source_type === 'system_audio' ? 'SYS' : (seg.source_type === 'microphone' ? 'MIC' : '');
  const card = document.createElement('div');
  card.className = 'card-item';
  card.innerHTML =
    '<div style="display:flex;gap:6px;align-items:center;margin-bottom:2px">' +
      '<span style="font-size:10px;color:var(--text-muted);font-family:monospace">' + esc(timeStr) + '</span>' +
      (src ? '<span class="meta-tag">' + src + '</span>' : '') +
      (seg.language ? '<span class="meta-tag">' + esc(seg.language) + '</span>' : '') +
    '</div>' +
    '<div class="seg-text" style="color:#f1f5f9;line-height:1.4"></div>';
  card.querySelector('.seg-text').textContent = seg.text;
  transcriptList.appendChild(card);
  while (transcriptList.querySelectorAll('.card-item').length > 300) {
    transcriptList.querySelector('.card-item').remove();
  }
};

// ==========================================================================
// NOTES & REPORTS
// ==========================================================================
window.showMeetingReport = function(d) {
  d = d || {};
  const box = $('meetingReportArea');
  box.innerHTML = '';

  const sumSec = document.createElement('div');
  sumSec.className = 'report-section';
  sumSec.innerHTML = '<h5>Ringkasan</h5><div class="summary-text"></div>';
  sumSec.querySelector('.summary-text').innerHTML = renderMarkdown(d.summary || 'Tidak ada ringkasan.');
  box.appendChild(sumSec);

  const decSec = document.createElement('div');
  decSec.className = 'report-section';
  decSec.innerHTML = '<h5>Keputusan</h5>';
  const decs = Array.isArray(d.decisions) ? d.decisions : [];
  if (!decs.length) {
    decSec.insertAdjacentHTML('beforeend', '<div class="muted">Tidak ada keputusan tercatat.</div>');
  } else {
    const ul = document.createElement('ul');
    ul.className = 'report-list';
    decs.forEach((t) => { const li = document.createElement('li'); li.textContent = String(t); ul.appendChild(li); });
    decSec.appendChild(ul);
  }
  box.appendChild(decSec);

  const actSec = document.createElement('div');
  actSec.className = 'report-section';
  actSec.innerHTML = '<h5>Action items</h5>';
  const items = Array.isArray(d.action_items) ? d.action_items : [];
  if (!items.length) {
    actSec.insertAdjacentHTML('beforeend', '<div class="muted">Tidak ada action item.</div>');
  } else {
    items.forEach((item) => {
      const row = document.createElement('label');
      row.className = 'card-item';
      row.style.cssText = 'display:flex;gap:8px;align-items:flex-start;cursor:pointer';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.style.marginTop = '2px';
      cb.onchange = () => call('update_action_status', item.id, cb.checked ? 'done' : 'pending');
      const txt = document.createElement('div');
      txt.style.flex = '1';
      const main = document.createElement('div');
      main.textContent = item.text || '';
      txt.appendChild(main);
      if (item.owner || item.deadline) {
        const meta = document.createElement('div');
        meta.className = 'muted';
        meta.textContent = [item.owner ? '@' + item.owner : '', item.deadline || ''].filter(Boolean).join(' · ');
        txt.appendChild(meta);
      }
      row.append(cb, txt);
      actSec.appendChild(row);
    });
  }
  box.appendChild(actSec);
  window._showTab('notes');
};

window.showReport = function(d) {
  d = d || {};
  const box = $('reportArea');
  box.innerHTML = '';
  if (d.report_type === 'practice') {
    const sec = document.createElement('div');
    sec.className = 'report-section';
    sec.innerHTML = '<h5>Laporan latihan</h5>';
    const meta = document.createElement('div');
    meta.className = 'muted';
    meta.textContent = (d.questions_count || 0) + ' pertanyaan · ' + (d.answers_count || 0) + ' jawaban dinilai';
    const body = document.createElement('div');
    body.className = 'summary-text';
    body.innerHTML = renderMarkdown(d.report || '');
    sec.append(meta, body);
    box.appendChild(sec);
  } else if (d.report_type === 'notes') {
    const sum = document.createElement('div');
    sum.className = 'report-section';
    sum.innerHTML = '<h5>Ringkasan wawancara</h5><div class="summary-text"></div>';
    sum.querySelector('.summary-text').innerHTML = renderMarkdown(d.summary || '');
    box.appendChild(sum);

    const qa = document.createElement('div');
    qa.className = 'report-section';
    qa.innerHTML = '<h5>Pertanyaan &amp; jawaban (perkiraan AI)</h5>';
    const pairs = Array.isArray(d.qa_pairs) ? d.qa_pairs : [];
    if (!pairs.length) {
      qa.insertAdjacentHTML('beforeend', '<div class="muted">Belum ada pasangan terdeteksi.</div>');
    } else {
      pairs.forEach((p) => {
        const line = document.createElement('div');
        line.className = 'card-item';
        const q = document.createElement('div');
        q.style.fontWeight = '600';
        q.textContent = p.question || '(tanpa pertanyaan terdeteksi)';
        const a = document.createElement('div');
        a.style.color = 'var(--text-secondary)';
        a.textContent = p.answer || '';
        line.append(q, a);
        qa.appendChild(line);
      });
    }
    box.appendChild(qa);

    const fu = document.createElement('div');
    fu.className = 'report-section';
    fu.innerHTML = '<h5>Pertanyaan tindak lanjut</h5>';
    const follow = Array.isArray(d.follow_up_questions) ? d.follow_up_questions : [];
    if (follow.length) {
      const ul = document.createElement('ul');
      ul.className = 'report-list';
      follow.forEach((t) => { const li = document.createElement('li'); li.textContent = String(t); ul.appendChild(li); });
      fu.appendChild(ul);
    } else {
      fu.insertAdjacentHTML('beforeend', '<div class="muted">Tidak ada usulan.</div>');
    }
    box.appendChild(fu);

    const det = document.createElement('details');
    det.className = 'transcript-full';
    const sm = document.createElement('summary');
    sm.textContent = 'Transkrip lengkap';
    const pre = document.createElement('pre');
    pre.textContent = d.transcript || '';
    det.append(sm, pre);
    box.appendChild(det);
  }
  showNotice('info', 'Laporan siap di tab Catatan.');
  window._showTab('notes');
};

// ==========================================================================
// INTERVIEW PRACTICE
// ==========================================================================
window._startPractice = function() {
  const topic = ($('practiceTopic').value || '').trim() || 'general';
  call('start_practice', topic, $('practiceType').value);
};
window._submitAnswer = function() { call('submit_practice_answer'); };
window._nextQuestion = function() { call('next_practice_question'); };
window._finishPractice = function() { call('finish_practice'); };

let _questionNo = 0;
window.showInterviewQuestion = function(d) {
  const q = (d && d.question) || '';
  if (!q) return;
  _questionNo += 1;
  S.practiceQuestion = q;
  $('practiceCurrent').hidden = false;
  $('practiceQuestionNo').textContent = 'Pertanyaan ' + _questionNo;
  $('practiceQuestion').textContent = q;
  $('practiceDraft').textContent = 'Belum ada jawaban terekam.';
  $('practiceSubmit').disabled = false;
  $('practiceNext').disabled = false;
  $('viewPractice').style.display = '';
  window._showTab('practice');
};

window.showAnswerDraft = function(text) {
  $('practiceDraft').textContent = text || 'Belum ada jawaban terekam.';
};

window.showInterviewFeedback = function(d) {
  d = d || {};
  const list = $('feedbackList');
  if (list.dataset.empty !== '0') { list.innerHTML = ''; list.dataset.empty = '0'; }
  const item = document.createElement('div');
  item.className = 'feedback-item';
  const q = document.createElement('div');
  q.className = 'fb-q';
  q.textContent = 'Q: ' + (d.question || '');
  const a = document.createElement('div');
  a.className = 'fb-a';
  a.textContent = d.answer || '';
  const f = document.createElement('div');
  f.className = 'summary-text';
  f.innerHTML = renderMarkdown(d.feedback || '');
  item.append(q, a, f);
  list.prepend(item);
  $('practiceDraft').textContent = 'Belum ada jawaban terekam.';
};


// ==========================================================================
// ASR MODEL MANAGEMENT
// ==========================================================================
window.updateASRStatus = function(payload) {
  if (!payload) return;
  S.activeModelInfo = payload.info || {};
  S.modelsCatalog = payload.catalog || [];
  $('langSelect').value = S.activeModelInfo.language_setting || 'auto';
  renderModels();
  const isLocal = !!S.activeModelInfo.is_local;
  const modelName = S.activeModelInfo.model || 'Belum ada model lokal';
  asrGlobalStatus.innerHTML = 'Model aktif: <strong></strong> (' + (isLocal ? 'lokal di CPU' : 'belum lokal') + ')';
  asrGlobalStatus.querySelector('strong').textContent = modelName;
};

window.onASRStatusUpdate = function(data) {
  if (!data) return;
  if (data.status === 'downloading' || data.status === 'loading') {
    spinnerLabel.textContent = data.message || 'Memuat model ASR…';
    spinnerRow.classList.add('show');
  } else {
    spinnerRow.classList.remove('show');
  }
  if (data.status === 'error' && data.message) showNotice('error', data.message);
};

function renderModels() {
  modelsContainer.innerHTML = '';
  S.modelsCatalog.forEach((m) => {
    const card = document.createElement('div');
    card.className = 'model-card' + (m.is_active ? ' active-model' : '');
    let badge;
    if (m.is_active) badge = '<span class="status-pill active">Aktif</span>';
    else if (m.is_loading) badge = '<span class="status-pill downloading">Memuat…</span>';
    else if (m.is_cached) badge = '<span class="status-pill cached">Tersimpan</span>';
    else badge = '<span class="status-pill" style="color:var(--text-muted);border:1px solid var(--border-subtle)">Belum diunduh</span>';

    let btn;
    if (m.is_active) btn = '<span style="font-size:10px;color:var(--text-muted);font-weight:600">Digunakan</span>';
    else if (m.is_cached) btn = '<button class="btn-action" data-model="' + esc(m.id) + '">Gunakan</button>';
    else btn = '<button class="btn-action" data-model="' + esc(m.id) + '">Unduh (' + esc(m.size_mb) + ' MB)</button>';

    card.innerHTML =
      '<div class="model-card-header"><div style="font-size:12px;font-weight:600;color:#f1f5f9">' + esc(m.name) +
      (m.recommended ? ' <span style="font-size:9px;padding:1px 4px;border-radius:3px;background:#1a1a1e;color:#a1a1aa;border:1px solid #333338">Rekomendasi</span>' : '') +
      '</div>' + badge + '</div>' +
      '<div style="display:flex;align-items:center;justify-content:space-between;font-size:10px;color:var(--text-muted);margin-top:2px">' +
      '<span>' + esc(m.desc) + '</span>' + btn + '</div>';
    const action = card.querySelector('[data-model]');
    if (action) action.onclick = () => call('download_and_load_model', m.id);
    modelsContainer.appendChild(card);
  });
}

$('langSelect').value = 'auto';

// ==========================================================================
// BOOT: wait for the Python bridge, then tell Python the page is ready
// ==========================================================================
let _readySent = false;
function sendReady() {
  const a = api();
  if (!_readySent && a && typeof a.ui_ready === 'function') {
    _readySent = true;
    a.ui_ready();
  }
}
window.addEventListener('pywebviewready', sendReady);
window.addEventListener('load', () => {
  window.updateHiddenMode('disabled');
  window.updatePrivacy({ cloud_processing: false });
  sendReady();
});

</script>
</body>
</html>

"""
