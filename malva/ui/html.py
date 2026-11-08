"""
malva.ui.html — Floating pill HTML/CSS/JS for Malva.

Design System & Standards:
- Solid deep black (#000000), zero glassmorphism, zero white edge residue
- Zero emojis / unicode symbol hacks — 100% stroke vector SVG icons
- Zero purple / violet tones — clean monochromatic neutral palette with functional accents
- 5-bar live responsive spectrum visualizer driven by PyAudio RMS levels
- Native DWM rounded window compatibility
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
</style>
</head>
<body>

<div id="pill" class="compact">

  <!-- SLEEP MODE WIDGET (175px solid black strip) -->
  <div id="sleepViewport" title="Klik untuk membangunkan Malva" onclick="window.pywebview.api.wake_from_sleep()">
    <svg class="moon-icon" viewBox="0 0 24 24"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>
    <span style="font-size:11px;font-weight:500;color:var(--text-muted)">Malva Tertidur</span>
  </div>

  <!-- STATUSBAR (Solid Black) -->
  <div id="statusbar">
    <!-- Drag Grip -->
    <div class="drag-grip" id="dragGrip" title="Seret untuk memindahkan">
      <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M5 9h14M5 15h14"/></svg>
    </div>

    <!-- Mode Chip -->
    <span id="modeChip" class="mode-chip">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="m4.93 4.93 4.24 4.24"/><path d="m14.83 9.17 4.24-4.24"/><path d="m14.83 14.83 4.24 4.24"/><path d="m9.17 14.83-4.24 4.24"/></svg>
      <span id="modeText">Asisten</span>
    </span>

    <!-- State Indicator Dot -->
    <div id="stateDot" class="state-dot" title="Status Sistem"></div>

    <!-- Source Track Badges -->
    <div class="track-sources">
      <span id="badgeMic" class="source-pill mic" style="display:none" title="Mikrofon Aktif">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/></svg>
        MIC
      </span>
      <span id="badgeSys" class="source-pill sys" style="display:none" title="Audio Sistem Aktif">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
        SYS
      </span>
    </div>

    <!-- Feature Indicators (Focus & Hidden) -->
    <span id="badgeFocus" class="feature-badge focus" title="Focus Mode Aktif">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="10" height="10"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>
      FOKUS
    </span>
    <span id="badgeHidden" class="feature-badge hidden-active" title="Capture Exclusion">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="10" height="10"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
      HIDDEN
    </span>

    <!-- 5-BAR LIVE SPECTRUM VISUALIZER -->
    <div id="spectrum" class="listening">
      <div class="bar"></div>
      <div class="bar"></div>
      <div class="bar"></div>
      <div class="bar"></div>
      <div class="bar"></div>
    </div>

    <!-- Expand Button -->
    <button id="expandBtn" class="btn-icon" onclick="window._togglePanel()" title="Buka / Tutup Panel">
      <svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>
    </button>
  </div>

  <!-- EXPANDED PANEL -->
  <div id="panel">

    <!-- Tabs -->
    <div class="tab-row" role="tablist">
      <button class="tab-btn active" onclick="window._showTab('chat')" data-tab="chat">
        <svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        Chat
      </button>
      <button class="tab-btn" onclick="window._showTab('transcript')" data-tab="transcript">
        <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/></svg>
        Transkrip
      </button>
      <button class="tab-btn" onclick="window._showTab('notes')" data-tab="notes">
        <svg viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
        Catatan
      </button>
      <button class="tab-btn" onclick="window._showTab('settings')" data-tab="settings">
        <svg viewBox="0 0 24 24"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/></svg>
        Setelan
      </button>
    </div>

    <!-- Viewport -->
    <div id="tabContent" class="tab-viewport">

      <!-- TAB 1: CHAT -->
      <div id="viewChat">
        <div id="spinnerRow" class="spinner-row">
          <svg class="spinner" viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
          <span id="spinnerLabel">Memproses respons…</span>
        </div>
        <div id="answerArea"></div>
      </div>

      <!-- TAB 2: TRANSKRIP -->
      <div id="viewTranscript" style="display:none">
        <div id="transcriptList">
          <div style="font-size:11px;color:var(--text-muted);text-align:center;padding:24px 0">
            Belum ada transkrip audio yang direkam pada sesi ini.
          </div>
        </div>
      </div>

      <!-- TAB 3: CATATAN -->
      <div id="viewNotes" style="display:none">
        <div style="font-size:10px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px">
          Keputusan
        </div>
        <div id="decisionsList">
          <div style="font-size:11px;color:var(--text-muted);padding:4px 0">Tidak ada keputusan tercatat.</div>
        </div>

        <div style="font-size:10px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;color:var(--text-muted);margin:14px 0 6px">
          Tindak Lanjut & Action Items
        </div>
        <div id="actionsList">
          <div style="font-size:11px;color:var(--text-muted);padding:4px 0">Tidak ada action item tertunda.</div>
        </div>
      </div>

      <!-- TAB 4: SETELAN & ASR MODEL MANAGER -->
      <div id="viewSettings" style="display:none">

        <div class="settings-section-title">Mode Operasi</div>
        <div class="setting-row">
          <div>
            <div style="font-size:12px;font-weight:500">Profil Sesi</div>
            <div style="font-size:10.5px;color:var(--text-muted)">Konteks pemrosesan audio</div>
          </div>
          <select id="modeSelect" class="select-input" onchange="window._changeMode(this.value)">
            <option value="assistant">Asisten Umum</option>
            <option value="meeting">Meeting Intelligence</option>
            <option value="interview_practice">Latihan Wawancara</option>
            <option value="interview_notes">Catatan Wawancara</option>
            <option value="voice_input">Input Suara Saja</option>
          </select>
        </div>

        <div class="settings-section-title">Bahasa Pengenalan Ucapan</div>
        <div class="setting-row">
          <div>
            <div style="font-size:12px;font-weight:500">Mode Bahasa</div>
            <div style="font-size:10.5px;color:var(--text-muted)">Deteksi otomatis atau kunci</div>
          </div>
          <select id="langSelect" class="select-input" onchange="window.pywebview.api.set_asr_language(this.value)">
            <option value="auto">Auto (Deteksi Otomatis)</option>
            <option value="id">Bahasa Indonesia</option>
            <option value="en">English</option>
          </select>
        </div>

        <div class="settings-section-title">Model ASR Lokal (Whisper)</div>
        <div id="modelsContainer"></div>
        <div id="asrGlobalStatus" style="font-size:10.5px;color:var(--text-muted);margin:4px 0 10px"></div>

        <div class="settings-section-title">Kontrol Privasi & Integrasi</div>
        <div class="setting-row">
          <div>
            <div style="font-size:12px;font-weight:500">Focus Mode</div>
            <div style="font-size:10.5px;color:var(--text-muted)">Jaga sesi tetap aktif & redam sleep</div>
          </div>
          <button id="focusToggleBtn" class="toggle-switch" onclick="window._toggleFocus()">Nonaktif</button>
        </div>
        <div class="setting-row">
          <div>
            <div style="font-size:12px;font-weight:500">Hidden Mode (Capture Exclusion)</div>
            <div style="font-size:10.5px;color:var(--text-muted)">Kecualikan dari perekam layar Windows</div>
          </div>
          <button id="hiddenToggleBtn" class="toggle-switch" onclick="window._toggleHidden()">Nonaktif</button>
        </div>
        <div class="setting-row">
          <div>
            <div style="font-size:12px;font-weight:500">Audio Sistem (Stereo Mix)</div>
            <div style="font-size:10.5px;color:var(--text-muted)">Rekam audio laptop sebagai track terpisah</div>
          </div>
          <button id="sysAudioToggleBtn" class="toggle-switch" onclick="window._toggleSysAudio()">Nonaktif</button>
        </div>

      </div>

    </div>

    <!-- BOTTOM ROW -->
    <div id="bottomControls">
      <div class="input-box">
        <input id="chatInput" type="text" class="chat-field"
               placeholder="Ketik instruksi atau pertanyaan…"
               onkeydown="if(event.key==='Enter')window._submitText()" autocomplete="off">
        <button class="send-btn" onclick="window._submitText()" title="Kirim">
          <svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
        </button>
      </div>

      <button id="pauseBtn" class="btn-icon" onclick="window._togglePause()" title="Jeda / Lanjutkan Audio">
        <svg id="pauseIcon" viewBox="0 0 24 24"><rect width="4" height="16" x="6" y="4" rx="1"/><rect width="4" height="16" x="14" y="4" rx="1"/></svg>
      </button>

      <button class="btn-icon danger" onclick="window._emergencyStop()" title="Hentikan Sesi">
        <svg viewBox="0 0 24 24"><rect width="14" height="14" x="5" y="5" rx="2"/></svg>
      </button>
    </div>

  </div>

</div>

<script>
const S = {
  expanded: false,
  sleeping: false,
  paused: false,
  focusMode: false,
  hiddenMode: false,
  sysAudio: false,
  state: 'idle',
  answerRaw: '',
  modelsCatalog: [],
  activeModelInfo: {}
};

const pill            = document.getElementById('pill');
const stateDot        = document.getElementById('stateDot');
const modeText        = document.getElementById('modeText');
const badgeMic        = document.getElementById('badgeMic');
const badgeSys        = document.getElementById('badgeSys');
const badgeFocus      = document.getElementById('badgeFocus');
const badgeHidden     = document.getElementById('badgeHidden');
const answerArea      = document.getElementById('answerArea');
const spinnerRow      = document.getElementById('spinnerRow');
const spinnerLabel    = document.getElementById('spinnerLabel');
const transcriptList  = document.getElementById('transcriptList');
const pauseIcon       = document.getElementById('pauseIcon');
const modelsContainer = document.getElementById('modelsContainer');
const asrGlobalStatus = document.getElementById('asrGlobalStatus');
const spectrum        = document.getElementById('spectrum');
const bars            = spectrum.querySelectorAll('.bar');

// ==========================================================================
// 5-BAR SPECTRUM (LIVE REAL-TIME LEVELS FROM PYTHON RMS)
// ==========================================================================
window.updateBars = function(levels) {
  if (!levels || !levels.length) return;
  let isSpeaking = false;
  for (let i = 0; i < bars.length; i++) {
    const val = levels[i] || 6;
    if (val > 10) isSpeaking = true;
    bars[i].style.height = Math.max(6, Math.min(32, val)) + 'px';
  }
  spectrum.classList.toggle('speaking', isSpeaking);
};

// ==========================================================================
// WINDOW RESIZE & EXPAND
// ==========================================================================
window._togglePanel = function() {
  S.expanded = !S.expanded;
  pill.classList.toggle('expanded', S.expanded);
  pill.classList.toggle('compact', !S.expanded);

  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.set_panel_state(S.expanded ? 'expanded' : 'compact');
  }
};

window._showTab = function(tabName) {
  document.querySelectorAll('.tab-btn').forEach(t => t.classList.toggle('active', t.dataset.tab === tabName));
  document.getElementById('viewChat').style.display       = tabName === 'chat' ? '' : 'none';
  document.getElementById('viewTranscript').style.display = tabName === 'transcript' ? '' : 'none';
  document.getElementById('viewNotes').style.display      = tabName === 'notes' ? '' : 'none';
  document.getElementById('viewSettings').style.display   = tabName === 'settings' ? '' : 'none';
};

// ==========================================================================
// PYTHON STATE HANDLERS
// ==========================================================================
window.updateState = function(state) {
  S.state = state;
  stateDot.className = 'state-dot ' + state;
  spectrum.classList.toggle('listening', state === 'listening');
  spinnerRow.classList.toggle('show', state === 'processing');
};

window.updateMode = function(mode) {
  const labels = {
    assistant: 'Asisten',
    meeting: 'Meeting',
    interview_practice: 'Latihan Wawancara',
    interview_notes: 'Catatan Wawancara',
    voice_input: 'Input Suara'
  };
  modeText.textContent = labels[mode] || mode;
  document.getElementById('modeSelect').value = mode;
};

window.updateSources = function(sources) {
  badgeMic.style.display = sources.includes('microphone') ? 'inline-flex' : 'none';
  badgeSys.style.display = sources.includes('system_audio') ? 'inline-flex' : 'none';
};

window.updateFocusMode = function(active) {
  S.focusMode = active;
  badgeFocus.classList.toggle('show', active);
  const btn = document.getElementById('focusToggleBtn');
  btn.textContent = active ? 'Aktif' : 'Nonaktif';
  btn.className = active ? 'toggle-switch on' : 'toggle-switch';
};

window.updateHiddenMode = function(status) {
  const btn = document.getElementById('hiddenToggleBtn');
  badgeHidden.className = 'feature-badge';
  if (status === 'active') {
    badgeHidden.className = 'feature-badge show hidden-active';
    badgeHidden.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="10" height="10"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg> HIDDEN';
    btn.textContent = 'Aktif';
    btn.className = 'toggle-switch on';
  } else {
    btn.textContent = 'Nonaktif';
    btn.className = 'toggle-switch';
  }
};

// ==========================================================================
// ASR MODEL MANAGEMENT
// ==========================================================================
window.updateASRStatus = function(payload) {
  if (!payload) return;
  S.activeModelInfo = payload.info || {};
  S.modelsCatalog = payload.catalog || [];

  renderModels();

  const isLocal = S.activeModelInfo.is_local;
  const modelName = S.activeModelInfo.model || 'Cloud';
  asrGlobalStatus.innerHTML = `Model aktif: <strong>${modelName}</strong> (${isLocal ? 'Lokal di CPU' : 'Fallback Cloud'})`;
};

window.onASRStatusUpdate = function(data) {
  if (data.status === 'downloading' || data.status === 'loading') {
    spinnerLabel.textContent = data.message || 'Memuat model ASR…';
    spinnerRow.classList.add('show');
  } else {
    spinnerRow.classList.remove('show');
  }
};

function renderModels() {
  if (!modelsContainer) return;
  modelsContainer.innerHTML = '';

  S.modelsCatalog.forEach(m => {
    const card = document.createElement('div');
    card.className = 'model-card' + (m.is_active ? ' active-model' : '');

    let badge = '';
    if (m.is_active) {
      badge = `<span class="status-pill active">Aktif</span>`;
    } else if (m.is_loading) {
      badge = `<span class="status-pill downloading">Memuat…</span>`;
    } else if (m.is_cached) {
      badge = `<span class="status-pill cached">Tersimpan</span>`;
    } else {
      badge = `<span class="status-pill" style="color:var(--text-muted);border:1px solid var(--border-subtle)">Belum Diunduh</span>`;
    }

    let btn = '';
    if (m.is_active) {
      btn = `<span style="font-size:10px;color:var(--text-muted);font-weight:600">Digunakan</span>`;
    } else if (m.is_cached) {
      btn = `<button class="btn-action" onclick="window._loadModel('${m.id}')">Gunakan</button>`;
    } else {
      btn = `<button class="btn-action" onclick="window._loadModel('${m.id}')">Unduh (${m.size_mb} MB)</button>`;
    }

    card.innerHTML = `
      <div class="model-card-header">
        <div style="font-size:12px;font-weight:600;color:#f1f5f9">${m.name} ${m.recommended ? '<span style="font-size:9px;padding:1px 4px;border-radius:3px;background:#1a1a1e;color:#a1a1aa;border:1px solid #333338">Rekomendasi</span>' : ''}</div>
        ${badge}
      </div>
      <div style="display:flex;align-items:center;justify-content:space-between;font-size:10px;color:var(--text-muted);margin-top:2px">
        <span>${m.desc}</span>
        ${btn}
      </div>
    `;
    modelsContainer.appendChild(card);
  });
}

window._loadModel = function(modelId) {
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.download_and_load_model(modelId);
  }
};

// ==========================================================================
// CHAT & TRANSCRIPTS
// ==========================================================================
window.startAnswer = function() {
  S.answerRaw = '';
  answerArea.innerHTML = '<span style="color:var(--text-muted)">…</span>';
};

window.appendAnswer = function(chunk) {
  S.answerRaw += chunk;
  answerArea.innerHTML = (typeof marked !== 'undefined') ? marked.parse(S.answerRaw) : S.answerRaw.replace(/\n/g, '<br>');
  document.getElementById('tabContent').scrollTop = 99999;
};

window.endAnswer = function() {
  answerArea.innerHTML = (typeof marked !== 'undefined') ? marked.parse(S.answerRaw) : S.answerRaw.replace(/\n/g, '<br>');
  document.getElementById('tabContent').scrollTop = 99999;
};

window.addTranscriptSegment = function(seg) {
  if (!seg || !seg.text) return;
  if (transcriptList.querySelector('div[style*="text-align:center"]')) {
    transcriptList.innerHTML = '';
  }
  const card = document.createElement('div');
  card.className = 'card-item';
  const timeStr = new Date(seg.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  card.innerHTML = `
    <div style="display:flex;gap:6px;align-items:center;margin-bottom:2px">
      <span style="font-size:10px;color:var(--text-muted);font-family:monospace">${timeStr}</span>
      <span class="meta-tag">${seg.source_type === 'microphone' ? 'MIC' : 'SYS'}</span>
      ${seg.language ? `<span class="meta-tag">${seg.language}</span>` : ''}
    </div>
    <div style="color:#f1f5f9;line-height:1.4">${seg.text}</div>
  `;
  transcriptList.appendChild(card);
};

window.addDecision = function(text) {
  const list = document.getElementById('decisionsList');
  if (list.querySelector('div[style*="padding:4px 0"]')) list.innerHTML = '';
  const div = document.createElement('div');
  div.className = 'card-item';
  div.innerHTML = `<span style="color:var(--accent-green)">✓</span> ${text}`;
  list.appendChild(div);
};

window.addActionItem = function(item) {
  const list = document.getElementById('actionsList');
  if (list.querySelector('div[style*="padding:4px 0"]')) list.innerHTML = '';
  const div = document.createElement('div');
  div.className = 'card-item';
  div.style = 'display:flex;gap:8px;align-items:flex-start';
  div.innerHTML = `
    <input type="checkbox" onchange="window.pywebview.api.update_action_status('${item.id}', this.checked ? 'done' : 'pending')" style="margin-top:2px">
    <div style="flex:1">
      <div>${item.text}</div>
      ${item.owner ? `<div style="font-size:10px;color:var(--text-muted)">@${item.owner}</div>` : ''}
    </div>
  `;
  list.appendChild(div);
};

// ==========================================================================
// CONTROLS
// ==========================================================================
window._submitText = function() {
  const input = document.getElementById('chatInput');
  const val = (input.value || '').trim();
  if (!val) return;
  input.value = '';
  window._showTab('chat');
  window.startAnswer();
  window.pywebview.api.send_text(val);
};

window._togglePause = function() {
  S.paused = !S.paused;
  pauseIcon.innerHTML = S.paused
    ? '<polygon points="5 3 19 12 5 21 5 3"/>'
    : '<rect width="4" height="16" x="6" y="4" rx="1"/><rect width="4" height="16" x="14" y="4" rx="1"/>';
  window.pywebview.api[S.paused ? 'pause_session' : 'resume_session']();
};

window._emergencyStop = function() {
  window.pywebview.api.emergency_stop();
  spinnerRow.classList.remove('show');
  answerArea.innerHTML = '<span style="color:var(--accent-red)">Sesi dihentikan.</span>';
};

window._changeMode = function(mode) {
  window.pywebview.api.change_mode(mode);
};

window._toggleFocus = function() {
  window.pywebview.api[S.focusMode ? 'disable_focus_mode' : 'enable_focus_mode']();
};

window._toggleHidden = function() {
  const btn = document.getElementById('hiddenToggleBtn');
  if (btn.classList.contains('on')) {
    window.pywebview.api.disable_hidden_mode();
  } else {
    window.pywebview.api.enable_hidden_mode();
  }
};

window._toggleSysAudio = function() {
  S.sysAudio = !S.sysAudio;
  const btn = document.getElementById('sysAudioToggleBtn');
  btn.textContent = S.sysAudio ? 'Aktif' : 'Nonaktif';
  btn.className = S.sysAudio ? 'toggle-switch on' : 'toggle-switch';
  window.pywebview.api[S.sysAudio ? 'enable_system_audio' : 'disable_system_audio']();
};

window.setSleeping = function(isSleeping) {
  S.sleeping = isSleeping;
  pill.classList.toggle('sleeping', isSleeping);
  if (isSleeping) {
    pill.classList.remove('expanded');
    pill.classList.add('compact');
  }
};

// Drag
document.getElementById('dragGrip').addEventListener('mousedown', () => {
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.start_drag().catch(() => {});
  }
});

// Init
window.addEventListener('load', () => {
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.ui_ready();
  }
});
</script>
</body>
</html>
"""
