# Malva Repository Audit & Agent Prompt v2

> **Audit date:** 2026-11-09  
> **Repository:** https://github.com/Fattan-malva/Nana  
> **Audited branch:** `master`  
> **Audited HEAD:** `c0df4f470606c5f881b71346f23ebd9bf084aa97` (`[ADD] Integrasi Awal`, 2026-11-08 23:29:22 UTC)  
> **Product target:** Malva — Private AI Desktop Copilot  
> **Blueprint:** [`BLUEPRINT.md`](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/BLUEPRINT.md)  
> **Important:** This is a source-code audit of the GitHub snapshot. It is not a Windows runtime test. Device capture, native dragging, WebView2 behavior, and visual results still require testing on the user's Windows machine.

---

# PART I — AUDIT REPORT

## 1. Executive summary

The repository already has a useful modular foundation. It is not an empty prototype: it contains an audio capture module, ASR router, session lifecycle, separate Meeting and Interview engines, SQLite storage, a desktop tool gateway, privacy manager, and a floating-pill UI.

However, several important paths are incomplete or disconnected:

1. **Audio capture is the highest-risk subsystem.** The current system-audio implementation imports `pyaudiowpatch` but does not use it to open a WASAPI loopback stream. It searches for devices named `Stereo Mix` or `loopback` through standard PyAudio, then can fall back to the default input device when no device is found. This is not a reliable system-audio capture implementation.
2. **The visualizer is not a true spectrum and only receives microphone levels.** Meeting Mode captures system audio, but that track has no level callback. The current five bars are calculated from five consecutive pieces of a time-domain waveform, not frequency bands.
3. **Mode infrastructure exists, but user-visible workflows are incomplete.** Meeting and Interview Notes send event types that the application-level UI event handler does not render. Interview Practice has question/evaluation methods, but the active session never calls them.
4. **Voice Input calls a missing JavaScript function.** `app.py` calls `window.showVoiceText(...)`, but that function is not defined in `malva/ui/html.py` in the audited snapshot.
5. **Sleep can interrupt active modes.** The idle timer only resets for `transcript_segment` and `ai_chunk`. Meeting and Interview Notes emit different event names. As a result, a live session can be auto-slept while it is actively capturing audio.
6. **Privacy settings are not enforced by the processing paths.** ASR automatically falls back to Google STT when a local model is unavailable or fails; the AI orchestrator defaults to an Ollama Cloud endpoint. `PrivacyManager.local_only` is not consulted by those components.
7. **Windows-MCP has not yet been integrated.** The current desktop gateway dispatches to the repository's own `malva.desktop.tools.runner` implementation.
8. **The existing UI theme should be preserved.** The current floating pill has a clear visual direction. The immediate need is better functional hierarchy, mode-specific controls, reliable states, and quick Sleep/Focus controls—not a complete visual redesign.

### Audit status overview

| Subsystem | Source-level status | Priority |
|---|---|---:|
| Microphone capture | Implemented but needs Windows device/runtime validation | P0 |
| System audio / WASAPI loopback | Incomplete / unreliable path | P0 |
| Audio spectrum | Partial; microphone-only, time-sliced RMS rather than true frequency bands | P0 |
| Audio-to-JS event bridge | Present; needs status, error, and shutdown handling | P0 |
| Assistant audio sources | Starts microphone only; does not start system audio by default | P0 |
| Meeting live transcript UI | Event type is not handled by app UI bridge | P0 |
| Interview Practice | Engine methods exist but are not wired into session workflow | P0 |
| Interview Notes live UI/report | Event and result schema mismatch | P1 |
| Voice Input UI | Calls missing JS function | P1 |
| Sleep idle behavior | Can auto-sleep active modes | P0 |
| Focus Mode | Basic backend and Settings toggle exist; not persistent across sessions | P1 |
| Manual Sleep control | No explicit sleep action in the UI/API; only automatic sleep and wake | P1 |
| Window dragging | Native helper and 30px drag grip exist; runtime behavior and error handling need testing | P1 |
| ASR local-first privacy | Automatic Google fallback conflicts with local-only expectation | P0 |
| LLM local/cloud privacy | Default points to Ollama Cloud; local-only policy is not enforced | P0 |
| Windows-MCP | Not found in source/dependencies; custom tools remain | P1/P2 |
| Test suite | No `tests/` directory or test files were present in the recursive repository tree | P0 before declaring fixes complete |

---

## 2. Repository snapshot

### Relevant structure found

```text
Nana/
├── .env.example
├── .gitignore
├── BLUEPRINT.md
├── HANDOFF.md
├── app.py
├── requirements.txt
└── malva/
    ├── ai/
    │   └── orchestrator.py
    ├── asr/
    │   └── router.py
    ├── audio/
    │   └── capture.py
    ├── desktop/
    │   ├── gateway.py
    │   └── tools/
    ├── interview/
    │   └── engine.py
    ├── meeting/
    │   └── engine.py
    ├── privacy/
    │   └── manager.py
    ├── shell/
    │   └── session.py
    ├── storage/
    │   └── db.py
    ├── transcript/
    │   └── core.py
    └── ui/
        └── html.py
```

The full recursive tree returned no `tests/` directory, test modules, or GitHub Actions workflow files in the audited snapshot.

### Recent commit

The audited `master` HEAD is `c0df4f470606c5f881b71346f23ebd9bf084aa97`, dated 2026-11-08 23:29:22 UTC. The commit message is `[ADD] Integrasi Awal`.

---

## 3. P0 findings — audio and session correctness

### P0.1 — System audio loopback path is not implemented robustly

**Evidence:**
- [`malva/audio/capture.py`, import section](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/audio/capture.py#L25-L35) imports `pyaudiowpatch` as `pyaudio_sys`.
- [`capture.py`, stream opening](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/audio/capture.py#L121-L153) creates the stream using `pyaudio.PyAudio()` and opens it as a normal input stream.
- [`capture.py`, device selection](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/audio/capture.py#L247-L278) scans standard PyAudio devices for names containing `stereo mix` or `loopback`.
- A repository code search found no use of `get_loopback_device_info_generator` or equivalent `pyaudio_sys` loopback APIs.

**Why this is a problem:**

`pyaudiowpatch` is imported but unused. The code is not explicitly selecting the default WASAPI loopback endpoint exposed by that package. If no device name matches, `_find_system_audio_device()` returns `None`; `_open_stream()` then opens an input stream with `input_device_index=None`, which selects the default input device. That can result in capturing the microphone instead of the laptop's system output, or failing depending on device/host API configuration.

**Required fix:**

- Implement a proper WASAPI loopback adapter using the available `pyaudiowpatch` API.
- Enumerate loopback endpoints and associate each with its corresponding output device.
- Make loopback selection explicit and visible in the UI.
- Do **not** fall back to the microphone/default input when the requested system loopback endpoint is missing.
- Return a clear `DEVICE_NOT_FOUND` or `LOOPBACK_UNAVAILABLE` error.
- Keep microphone capture and system capture as independent tracks.
- Handle stereo output capture and convert/downmix only after reading the real device format.
- Add device reconnection handling and stream cleanup.
- Test against at least the default Windows output device and one alternative output device.

### P0.2 — The five-bar visualizer does not compute frequency bands

**Evidence:**
- [`capture.py`, RMS and level calculation](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/audio/capture.py#L160-L194) splits the sample array into five consecutive slices and calculates RMS for each slice.
- [`capture.py`, AudioEngine callback assignment](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/audio/capture.py#L310-L374) assigns `on_levels` only to microphone tracks.
- [`html.py`, updateBars](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/ui/html.py#L792-L805) renders the received five values.
- [`app.py`, audio event forwarding](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/app.py#L255-L276) forwards `audio_levels` to `window.updateBars()`.

**Why this is a problem:**

The five slices are sections of the waveform in time, not frequency bands. The five values may look similar and do not represent bass/mid/high energy. The callback is restricted to microphone capture. In Meeting Mode the default source is system audio, so the visualizer receives no system-audio level updates.

**Required fix:**

- Implement a small, non-blocking analysis stage that consumes actual PCM frames.
- Prefer five meaningful frequency bands (for example low, low-mid, mid, high-mid, high), using an FFT/windowing method, if the UI is described as a spectrum.
- If only amplitude is intended, call it an audio-level meter rather than a spectrum.
- Support the active audio source: microphone, system audio, or both.
- Include source identity with the event, e.g. `{source, levels, timestamp}`.
- Normalize consistently to a documented `[0.0, 1.0]` or pixel-height contract.
- Use smoothing/attack/release to avoid flicker.
- Emit baseline/reset levels on stop, pause, sleep, stream error, and device loss.
- Rate-limit UI updates (start around 20–30 updates per second; tune with measurement).
- Never synthesize random visual motion or animate bars independently of real audio.
- Analysis must not block PCM capture or ASR.

### P0.3 — Assistant Mode starts only the microphone

**Evidence:** [`malva/shell/session.py`, mode startup](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/shell/session.py#L105-L122).

The `assistant` path calls `start_microphone()` but does not start system audio. This differs from the agreed product contract where Assistant Mode defaults to microphone + system audio as separate tracks.

**Required fix:**

- Assistant Mode should start both tracks by default, after proper system loopback capture is implemented.
- Let the user turn each source off independently.
- Keep each source separate through transcription and history.
- Meeting Mode remains system-audio-only by default.
- Voice Input must reject system audio in the backend, not just in the UI.
- Do not create duplicate tracks when toggling sources or switching modes.

### P0.4 — Meeting and Interview Notes transcript events do not reach the transcript UI

**Evidence:**
- [`meeting/engine.py`](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/meeting/engine.py#L32-L40) emits event type `segment`.
- [`interview/engine.py`](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/interview/engine.py#L154-L178) emits event type `notes_segment`.
- [`app.py`](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/app.py#L255-L300) handles `transcript_segment`, `ai_chunk`, `audio_levels`, `focus_mode`, `sleep_mode`, `voice_input_text`, `meeting_report`, and `interview_report`, but not `segment` or `notes_segment`.

**Required fix:**

- Define one canonical transcript event contract and use it across all modes.
- Render live transcript cards for Assistant, Meeting, Interview Notes, and any other transcript-producing mode.
- Preserve `source_type`, `timestamp`, `language`, and track metadata.
- Reset idle activity from canonical audio/session activity events, not only from assistant-only UI events.

### P0.5 — Session state can remain stuck at Processing

**Evidence:** [`malva/shell/session.py`, `_on_utterance`](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/shell/session.py#L211-L255).

The method emits `state_change=PROCESSING`, then several branches set `self.state = LISTENING` and return without emitting `state_change=LISTENING`:
- Empty ASR result.
- `voice_input`.
- `meeting` and `interview_notes`.

**Required fix:**

- Centralize state transitions in a helper or `try/finally` block.
- Ensure the UI receives a final state for every processing branch and error.
- Do not let a failed or empty transcription leave the UI stuck in Processing.
- Keep `PAUSED`, `SLEEPING`, `FOCUSED`, `ERROR`, and `LISTENING` state semantics consistent.

---

## 4. P0/P1 findings — modes and UI integration

### P0.6 — Interview Practice engine is not connected to the active session workflow

**Evidence:**
- [`interview/engine.py`, question generation](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/interview/engine.py#L60-L86) defines `get_next_question()`.
- [`interview/engine.py`, answer evaluation](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/interview/engine.py#L87-L120) defines `evaluate_answer()`.
- [`session.py`, setup and utterance routing](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/shell/session.py#L75-L120) creates the engine, but does not start the first question.
- [`session.py`, utterance routing](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/shell/session.py#L211-L255) routes interview-practice speech through generic `self._ai.ask()` rather than `self._interview.evaluate_answer()`.

**Required fix:**

Implement a real Practice state machine:
1. Configure topic and interview type.
2. Generate and display one interview question.
3. Capture the user's answer.
4. Use a clear answer-complete action or carefully defined VAD boundary.
5. Call `evaluate_answer()` with the current question and answer.
6. Display feedback.
7. Allow the user to ask for the next question.
8. Store the Q/A/feedback set and generate the final report.

Do not treat every utterance as a generic assistant question. Keep the feature transparent and designed for practice sessions.

### P1.1 — Interview Notes final report is not rendered correctly

**Evidence:**
- [`interview/engine.py`, `finalize_notes()`](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/interview/engine.py#L180-L211) returns `summary`, `transcript`, `qa_pairs`, and `follow_up_questions`. It does not return a top-level `report` field.
- [`app.py`, interview report handler](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/app.py#L288-L296) always reads `report.get('report', '')`.

**Required fix:**

Use a discriminated report schema. For practice, render the practice report. For notes, render summary, Q/A pairs, quotes, follow-up questions, and transcript links. Do not force both report types into one optional `report` string.

### P1.2 — Voice Input calls a missing JS function

**Evidence:**
- [`app.py`, voice input event handler](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/app.py#L278-L286) calls `window.showVoiceText(...)`.
- A repository-wide code search in the audited snapshot found `showVoiceText` only in `app.py`; it is not implemented in `malva/ui/html.py`.

**Required fix:**

Implement and test the Voice Input UI result handler. The UI must show the recognized text with a copy action and, if the existing safe text-injection flow supports it, a clearly controlled insert action. It must not pass system audio into the Voice Input pipeline.

### P1.3 — Meeting final summary is not surfaced clearly

`MeetingEngine.finalize()` persists a summary, decisions, and action items. The app-level handler currently renders decisions and action items but does not send the summary to a dedicated summary view. Provide a visible Meeting report view and preserve links to the transcript/timestamps.

### P1.4 — Mode selection is buried in Settings

The mode selector is currently inside `viewSettings` in the expanded panel (`malva/ui/html.py`, around lines 675–691). The user should be able to switch modes quickly from a small, well-organized mode menu without expanding a large settings form. Keep the main pill compact.

### P1.5 — Real UI mode-specific workflows are missing

The current UI has general Chat, Transcript, Notes, and Settings tabs. It does not provide a sufficiently distinct flow for:
- Interview Practice question/answer/evaluation.
- Interview Notes report review.
- Meeting summary and action-item review.
- Voice Input preview/copy/insert.
- Source selection and status feedback.

Implement these as contextual panel content, not a collection of unrelated dashboard cards.

---

## 5. P0 privacy finding — local-only is not enforced

### Evidence

- [`ASR router`](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/asr/router.py#L240-L310): when the local model is unavailable, `transcribe()` calls `_transcribe_cloud()`. `_transcribe_local()` also falls back to cloud on exceptions. `_transcribe_cloud()` uses Google STT.
- [`AI orchestrator`](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/ai/orchestrator.py#L20-L31): default LLM endpoint is `https://ollama.com/v1/chat/completions` and default model is `gemma4:31b-cloud`.
- [`Privacy manager`](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/privacy/manager.py#L35-L80): it stores `local_only=True` / `cloud_processing=False`, but repository code search found these flags only in `privacy/manager.py`; they are not wired into ASR or AI requests.

**Risk:**

Audio/transcript text can be sent to a cloud provider automatically even though the privacy manager defaults to local-only. The user is not being given the promised explicit cloud opt-in behavior.

**Required fix:**

- Create one explicit processing policy shared by ASR and AI orchestration.
- If `local_only=True`, do not call Google STT, Ollama Cloud, or any other remote inference endpoint.
- If local ASR is unavailable, surface a local-model-required status and explain how to download/select a model. Do not silently upload audio.
- Cloud processing must require an explicit user opt-in that is visible and persisted.
- Show provider/destination before enabling cloud processing.
- Make the UI accurately show whether current audio and text are processed locally or remotely.
- Add tests proving that local-only mode cannot reach remote endpoints, including fallback/error cases.

---

## 6. Sleep, Focus, and draggable window audit

### P0.7 — Idle sleep can interrupt active Meeting / Notes / Voice Input sessions

**Evidence:**
- [`app.py`, idle activity reset and monitor](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/app.py#L320-L355) resets activity on `transcript_segment` and `ai_chunk`.
- Meeting emits `segment`; Interview Notes emits `notes_segment`; Voice Input emits `voice_input_text`. Those do not reset the timer in the current handler.
- [`app.py`, startup ordering](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/app.py#L382-L396) calls `sync_sources()` before `session.start()`.

**Required fix:**

- Do not auto-sleep while a capture session is actively listening, processing, or recording.
- Use authoritative session/audio activity, not whether a UI text chunk arrived.
- Make auto-sleep apply only when no protected active session exists and the user has enabled auto-sleep.
- Add explicit manual Sleep and Wake actions.
- If the user requests manual Sleep during a live recording, clearly explain/confirm that audio capture will pause.
- Sleep must stop or pause streams cleanly and drain/close buffers; do not leave an open stream stuck while the capture loop stops reading.
- After Wake, verify the stream can resume or reopen cleanly and update source statuses.

### P1.6 — Focus Mode is only a session-level flag

`MalvaSession` initializes `focus_mode=False`, and `_create_session()` creates a new session when the user changes mode. Therefore Focus resets when modes change.

**Required fix:**

- Treat Focus as an app-level preference/state.
- Preserve it across mode switches until the user turns it off.
- Keep Focus independent from paused/sleeping/error states.
- Do not let disabling Focus force a paused/sleeping/error session back to Listening.
- Provide a friendly labeled toggle in the quick panel, with clear ON/OFF state and tooltip.
- Keep the pill compact; status badge is sufficient in collapsed mode.

### P1.7 — Sleep has no direct UI action

Current `MalvaAPI` exposes `wake_from_sleep()` but no explicit `sleep_now()` action. The UI has a sleeping viewport that can wake Malva, but the user cannot request Sleep from a normal active UI.

**Required fix:**

- Add a clearly labeled Sleep button/action in the expanded quick panel.
- Provide a simple Wake action while sleeping.
- Show a short explanation of what will pause.
- Preserve keyboard accessibility and visible state.

### P1.8 — Window drag exists, but requires verification and better errors

**Evidence:**
- [`app.py`, native drag helper](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/app.py#L145-L168) uses Win32 `ReleaseCapture` and `SendMessageW`.
- [`html.py`, drag grip](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/ui/html.py#L560-L570) provides a 30×30 grip.
- [`html.py`, JS drag event](https://github.com/Fattan-malva/Nana/blob/c0df4f470606c5f881b71346f23ebd9bf084aa97/malva/ui/html.py#L1068-L1080) calls `start_drag()` on `mousedown`.
- `start_drag()` silently catches all exceptions.

**Required fix:**

- Do not rewrite the entire drag system before testing the current native implementation.
- Test in actual pywebview/WebView2 on Windows.
- Make the grip easier to discover without making the UI larger.
- Return/log native drag failures instead of swallowing them silently.
- Verify dragging from both compact and expanded states.
- Add remembered position and multi-monitor-safe restore only if practical with the current framework.
- Ensure interactive buttons/input fields are not draggable.

---

## 7. ASR capability gaps

Current ASR (`malva/asr/router.py`) supports Faster-Whisper model sizes (`tiny`, `base`, `small`, `medium`) and a Google STT fallback.

Gaps relative to the Blueprint:

- The UI language selector only exposes Auto, Indonesian, and English.
- Auto language detection is done per transcription request/utterance through the Whisper `info.language`; it is not true language switching at every segment inside a multilingual utterance.
- The capture system accumulates an utterance until a VAD silence boundary or maximum duration. This is not streaming partial transcription.
- The model router currently does not include Qwen3-ASR.
- The UI's "Model ASR Lokal" label is not sufficient if the active fallback is cloud.
- Model performance has not been benchmarked on target hardware.

**Recommended sequence:**

1. Fix capture and session stability first.
2. Add explicit local-only enforcement.
3. Benchmark current Faster-Whisper as a baseline.
4. Add Qwen3-ASR as a model-router candidate only after verifying Windows runtime and hardware constraints.
5. Evaluate chunking/partial-result architecture separately.
6. Add additional manual languages based on tested model support.
7. Treat code-switching as a benchmark requirement, not a marketing claim.

---

## 8. Windows-MCP integration gap

The current `DesktopGateway` dispatches through `malva.desktop.tools.runner`. The repository contains custom desktop/browser/keyboard/interaction/shell tools, and `requirements.txt` includes `pywinauto`. No `windows_mcp` adapter, MCP server configuration, or Windows-MCP dependency was found in the audited tree/code search.

**Required action:**

- Do not delete the current tool suite before a replacement is proven.
- Add a dedicated Windows-MCP adapter/service behind the existing `DesktopGateway` interface.
- Run it as a separate process/service where compatible.
- Preserve risk policy and action audit logs.
- Verify supported tools and runtime requirements from the upstream repository before integrating.
- Migrate tool-by-tool; avoid a large-bang replacement.
- Keep destructive/high-impact actions behind explicit confirmation.

Reference: https://github.com/CursorTouch/Windows-MCP

---

## 9. Documentation and configuration drift

- `HANDOFF.md` says Phase 1–3 are complete and claims a restored 5-bar spectrum. The source code still has the gaps described above. Update HANDOFF only after tests pass.
- `.env.example` uses `WAKE_WORD=NANA` even though the app branding is Malva. Search whether the wake word is actually used; if unused, remove or label it as planned rather than implying it works.
- `.env.example` sets `SLEEP_AFTER_SECONDS=30`, while `app.py` fallback default is 60. Choose one documented default.
- `BLUEPRINT.md` and `HANDOFF.md` should agree on the product name, architecture, and feature status.
- Keep the GitHub repository name as `Nana` unless the owner explicitly requests a remote rename.

---

# PART II — COPY-READY PROMPT FOR THE CODING AGENT

You are a senior Windows desktop engineer, Python audio engineer, signal-processing engineer, and UI integration engineer. Work inside the existing repository:

`https://github.com/Fattan-malva/Nana`

The product is evolving from Nana into **Malva**. The GitHub repository name may remain `Nana` for now. Do not rename the remote repository.

Read `BLUEPRINT.md` and this audit before editing. The owner likes the current black/monochrome visual theme and wants it preserved. The UI needs functional improvements, not a total redesign.

## Mission

First inspect the local working tree and reproduce/confirm the audit findings. Then implement the critical fixes in small stages.

The user's priorities are:

1. Make audio capture actually work.
2. Make the live audio spectrum react to real microphone/system audio.
3. Complete Assistant, Meeting, Interview Practice, Interview Notes, and Voice Input workflows.
4. Keep the existing visual theme but make the UI more useful and less basic.
5. Make the floating window reliably draggable.
6. Add friendly, visible Sleep and Focus controls.
7. Follow `BLUEPRINT.md`, especially source isolation and local-first privacy.

## Non-negotiable working rules

- Inspect the real local repository and git status first.
- Preserve all unrelated/uncommitted user changes.
- Do not reset, clean, or overwrite user work.
- Do not perform a framework migration or a broad rewrite.
- Do not replace the current theme or create a generic dashboard.
- Do not use fake/random spectrum movement.
- Do not claim something works without tests.
- Do not route system audio to the microphone/default input as a fallback.
- Do not silently send audio/transcripts to cloud providers when local-only is active.
- Do not silently stop a live Meeting/Interview session because the idle timer fired.
- Do not delete the existing desktop tool suite until Windows-MCP is integrated and tested.
- Do not commit or push unless the repository owner explicitly asks you to.
- If Windows hardware/device behavior cannot be tested in your environment, document it honestly and provide manual test steps.

---

## Stage 0 — Audit and reproduce before editing

Read these files first:

- `BLUEPRINT.md`
- `HANDOFF.md`
- `app.py`
- `malva/audio/capture.py`
- `malva/shell/session.py`
- `malva/ui/html.py`
- `malva/asr/router.py`
- `malva/transcript/core.py`
- `malva/meeting/engine.py`
- `malva/interview/engine.py`
- `malva/ai/orchestrator.py`
- `malva/privacy/manager.py`
- `malva/desktop/gateway.py`
- `malva/storage/db.py`
- `requirements.txt`
- `.env.example`

Build an audit table with `WORKING`, `PARTIAL`, `BROKEN`, `MISSING`, or `NOT TESTED` status. Include file/function evidence, root cause, and reproduction procedure.

Do not trust `HANDOFF.md` claims until verified against source and tests.

## Stage 1 — P0: fix audio capture and make the spectrum work

### 1.1 Implement real system-audio loopback

- Inspect the installed/pinned `pyaudiowpatch` version and upstream API.
- Implement the default WASAPI loopback device selection.
- Use the actual loopback endpoint corresponding to the selected Windows output device.
- Do not use `pyaudio.PyAudio()` as a substitute for the WASAPI loopback enumeration path.
- Do not return `None` and accidentally open the default microphone when system audio is requested.
- If loopback is unavailable, raise a clear typed error and show it to the user.
- Correctly handle stereo output formats and device sample rates.
- Convert to the ASR format (mono 16 kHz if necessary) only after capturing valid source frames.
- Keep microphone and system audio as separate tracks.
- Add tests/mocks for device selection and failures.

### 1.2 Make audio capture robust

- Validate device indexes, sample rate, channel count, and sample format.
- Add clear capture state: `starting`, `active`, `paused`, `stopped`, `error`.
- Do not set the UI badge to Active before the stream has actually opened.
- Emit a device-open success/failure event.
- Avoid infinite retry loops without backoff or visible error.
- Ensure each track closes stream and PortAudio resources once.
- Repeated start/stop/mode-switch must not create duplicate streams or worker threads.
- Handle device disconnect/reconnect.
- Ensure sleep/wake can reopen or resume the stream safely.
- Do not block the UI thread.

### 1.3 Implement real spectrum analysis

The current code's five time-domain RMS slices are not frequency bands. Fix this.

Preferred implementation:
- Analyze the latest PCM frame using an appropriate window.
- Compute FFT or equivalent frequency-band energy.
- Aggregate five useful bands, such as low, low-mid, mid, high-mid, high.
- Normalize the result into a stable documented range `[0.0, 1.0]`.
- Clamp non-finite values and handle empty buffers.
- Apply smoothing/attack/release to prevent flicker.
- Rate-limit the UI event stream (start at approximately 20–30 updates per second).
- Include the source in the event payload: microphone, system audio, or both.
- Reset/decay bars on silence, pause, stop, sleep, device loss, and error.
- Never block capture or ASR processing with FFT or JS bridge calls.
- The visualizer must use actual samples, never random animation.

If you decide that a five-bar amplitude meter is a better product choice than frequency bands, label it accurately as a level meter. Do not call time slices a spectrum.

### 1.4 Wire audio events end-to-end

Trace and test:

`Windows device → AudioTrack → PCM frames → analyzer → AudioEngine callback → MalvaSession event → app.py event handler → pywebview JS bridge → updateBars() → visible bars`

- Keep one canonical payload schema and document it.
- Test JS function availability before first callback.
- Handle WebView page-not-ready conditions safely.
- Log bridge errors in debug mode; do not silently swallow all failures.
- Test microphone and system-audio events independently.

### 1.5 Enforce source routing by mode

Implement the Blueprint contract:

| Mode | Microphone | System Audio |
|---|---:|---:|
| Assistant | ON by default | ON by default |
| Meeting | OFF by default | ON by default |
| Interview Practice | ON | OFF by default; optional if needed for practice |
| Interview Notes | User selectable | User selectable |
| Voice Input | ON | MUST be OFF |

Rules:
- Assistant must start both isolated tracks by default.
- Meeting must not start the user's microphone unless explicitly enabled.
- Voice Input must reject system audio in backend code.
- UI source badges must reflect confirmed stream states.
- Source toggles must be mode-aware and reset safely when changing mode.
- Do not use the microphone as a fallback system-audio source.

---

## Stage 2 — P0: make session state and live transcript events consistent

### 2.1 Canonical events

Use one event contract for all modes, for example:

- `session_started`
- `source_state`
- `state_change`
- `transcript_segment`
- `audio_levels`
- `meeting_report`
- `interview_question`
- `interview_feedback`
- `interview_report`
- `voice_input_text`
- `focus_mode`
- `sleep_mode`
- `capture_error`

Do not have the UI depend on inconsistent names like `segment` or `notes_segment` unless they are intentionally normalized by the app layer.

### 2.2 State restoration

The current `_on_utterance()` can set the state back to Listening without emitting a UI `state_change` in empty-result, Voice Input, Meeting, and Interview Notes branches.

Fix this with a consistent state transition helper or safe `try/finally` logic. Ensure that:
- Processing always resolves into Listening, Paused, Sleeping, or Error.
- Errors are visible.
- UI state always reflects backend state.
- Focus does not overwrite Paused/Sleeping/Error state.

### 2.3 Initial source state

`on_ui_ready()` currently calls `sync_sources()` before `session.start()`. It then starts the session, but the app event handler does not currently process `session_started`.

Fix the order and/or handle `session_started` / `source_state`, so the UI only displays active source badges after streams actually open.

### 2.4 Reset idle activity from the session, not only the UI

Meeting and Interview Notes currently emit event types that the idle timer does not count as activity. Replace this with authoritative session/audio activity:
- active capture means the session is not idle;
- transcript/audio events reset idle activity where appropriate;
- auto-sleep cannot interrupt an active protected session.

---

## Stage 3 — P0/P1: complete the modes as real workflows

### 3.1 Assistant Mode

- Starts microphone + system audio as separate tracks by default.
- Shows active source badges.
- Shows live transcript with source, timestamp, and language.
- Routes user speech/context into the Assistant AI flow.
- Supports independent mic/system source controls.
- Does not reset or lose history when a source is toggled.

### 3.2 Meeting Mode

- System audio only by default.
- Live transcript appears in UI.
- Shows source and timestamp.
- Final session report visibly includes summary, decisions, action items, and transcript.
- Action-item completion UI updates the database.
- Do not auto-sleep while meeting capture is active.
- Keep raw transcript separate from generated report.
- Do not claim diarization unless speaker identity is actually available.

### 3.3 Interview Practice

Wire the existing `InterviewEngine` methods into the real UI/session lifecycle.

Expected flow:
1. User selects topic and interview type.
2. Malva generates one question.
3. Question is shown clearly in the panel.
4. User answers via microphone.
5. User can finish the answer (or use a tested VAD boundary).
6. `evaluate_answer()` is called with the current question and captured answer.
7. Feedback is shown with strengths and concrete improvements.
8. User requests the next question.
9. A final report is saved and rendered.

Support behavioral, technical, coding, and situational tracks.

Do not route all speech to generic `AIOrchestrator.ask()` and call that a complete Interview Practice flow.

### 3.4 Interview Notes

- User chooses microphone/system sources.
- Live transcript is shown.
- Questions/answers are grouped as best-effort and labeled as AI-derived if inferred.
- Preserve timestamps and sources.
- Generate an editable report with summary, Q/A pairs, key quotes, and follow-up questions.
- Fix the current report schema mismatch: `finalize_notes()` returns `summary`, but the app handler currently expects `report`.
- Do not claim accurate speaker separation without diarization or another reliable speaker-label source.

### 3.5 Voice Input

- Microphone only.
- Live capture state is visible.
- Show the recognized text in the UI.
- Add copy action.
- Provide controlled text insertion only if a safe existing mechanism is available.
- Implement the missing `window.showVoiceText()` or replace it with a canonical UI event handler.
- No system audio is allowed in this mode.

### 3.6 Mode switching

- Mode selector should be quickly accessible from the compact/expanded pill without hiding it deep in Settings.
- Show the current mode clearly.
- Mode switch must update capture, ASR/session routing, report engine, and UI together.
- Preserve previous session data.
- Before stopping a session, finalize or save its current state.
- Avoid starting the new mode until old audio resources have stopped successfully.
- Keep per-mode controls contextual, not all settings at once.

---

## Stage 4 — P0/P1: enforce local-first privacy

This is mandatory.

- The current ASR router sends audio to Google STT when local model is unavailable or fails.
- The current AI orchestrator defaults to Ollama Cloud.
- The `PrivacyManager.local_only` flag is not wired into either execution path.

Implement one shared processing policy:
- `LOCAL_ONLY` is the default.
- In `LOCAL_ONLY`, no audio, transcript, prompt, or session context may be sent to a remote service.
- If the local model is unavailable, show a clear local-model-required error/state.
- Cloud processing requires explicit user opt-in.
- Store the choice and display it prominently.
- Do not silently retry against a cloud endpoint when a local request fails.
- Add tests that mock HTTP clients and assert that no external call occurs in local-only mode.

---

## Stage 5 — P1: Sleep and Focus controls

### Focus Mode

- Make Focus an app-level state, not only a session-level flag.
- Preserve Focus across mode switches until user turns it off.
- Add a friendly labeled toggle in the quick panel.
- Show clear ON/OFF state and tooltip.
- Focus suppresses nonessential UI interruptions and prevents automatic idle sleep.
- It must not disable pause, emergency stop, audio permissions, or privacy controls.
- It must not modify Windows sleep policy silently.
- Turning Focus off must not force a paused or sleeping session into Listening.

### Sleep Mode

- Add explicit `Sleep` action and `Wake` action.
- Show what Sleep will pause.
- Never auto-sleep during an active Meeting/Interview/Voice session.
- Auto-sleep should only run when no protected active session exists and the user enabled it.
- Manual Sleep during active capture requires clear confirmation or a safe policy.
- Stop or pause streams cleanly; do not leave an open stream unread in a paused loop.
- Wake must restore capture or report why it could not resume.
- Keep Sleep and Focus visually distinct.

### UI placement

Use friendly text labels and understandable icons in the expanded quick panel. Keep the collapsed pill minimal and show only concise status indicators.

---

## Stage 6 — P1: window dragging

The current drag implementation already exists:
- Native Win32 drag helper in `app.py`.
- `#dragGrip` in `malva/ui/html.py`.
- JS listener calls `start_drag()`.

Do not replace it blindly.

Test on Windows with the actual pywebview runtime:
- Compact state.
- Expanded state.
- Multi-monitor.
- Different DPI scaling.
- Drag must not trigger other controls.

Improve:
- Useful drag grip/hover affordance.
- Visible feedback or logging if native drag fails.
- Safe window position restore if implemented.
- No interaction conflict with buttons, text input, or scrolling.

---

## Stage 7 — P1/P2: refine existing UI without replacing the theme

Preserve the existing theme and visual design language. Improve information hierarchy and functional completeness.

Required UI work:
- Quick mode picker reachable without deep Settings navigation.
- Clearly visible microphone/system source indicators.
- Clearly visible current mode and capture state.
- Real audio visualizer tied to real samples.
- Contextual panel for Interview Practice.
- Meeting report/summary content.
- Interview Notes report content.
- Voice Input transcript + copy action.
- Friendly Focus and Sleep buttons.
- Empty, loading, paused, processing, error, and sleeping states.
- Keep collapsed pill small.
- Do not expand automatically for each transcript/AI update.
- Avoid dashboard overload.
- Do not use decorative fake waveforms.

Keep the current color palette, font direction, and icon treatment unless an actual contrast/usability defect requires a targeted fix.

---

## Stage 8 — P1/P2: Windows-MCP migration

- Current desktop gateway still dispatches to `malva.desktop.tools.runner`.
- Keep that integration working while implementing a separate Windows-MCP adapter.
- Verify the current Windows-MCP upstream runtime requirements.
- Run the MCP integration as a separate service/process where practical.
- Keep the current `DesktopGateway` as the stable policy boundary.
- Route calls through the existing permission/risk policy and audit logging.
- Do not give arbitrary shell/registry/process termination destructive access by default.
- Migrate tools incrementally after capability parity tests.

Reference: https://github.com/CursorTouch/Windows-MCP

---

## Stage 9 — Tests and acceptance

There is no test suite in the audited repository snapshot. Add tests before marking the core work complete.

### Deterministic tests

Audio:
- Synthetic sine waves produce expected frequency-band activity.
- Silence produces baseline values.
- Mono and stereo sample handling works.
- Empty/invalid/NaN samples do not crash.
- Device-not-found does not fall back to microphone for system audio.
- WASAPI loopback selection chooses a loopback endpoint.
- Stop/pause/wake resets or resumes visualizer state.
- Repeated start/stop creates no duplicate tracks.

Mode routing:
- Assistant starts mic + system.
- Meeting starts system only.
- Interview Practice starts mic.
- Interview Notes respects selected source settings.
- Voice Input starts mic and rejects system audio.

UI/event:
- Audio event reaches `updateBars()`.
- Meeting transcript event renders in transcript UI.
- Interview Notes event renders.
- Interview Practice question and feedback events render.
- Voice Input result renders.
- Every processing branch returns to a correct state.

Sleep/Focus:
- Active Meeting cannot auto-sleep.
- Active Interview cannot auto-sleep.
- Focus remains enabled through mode changes.
- Focus cannot override Paused/Sleeping/Error.
- Manual Sleep/Wake changes source states correctly.

Privacy:
- Local-only mode makes no external HTTP request.
- A missing local ASR model does not trigger Google STT.
- A local LLM failure does not trigger cloud fallback.
- Cloud requests happen only after explicit opt-in.

### Windows manual QA

Run on Windows 10/11 with actual microphone and output devices:
1. Launch Malva.
2. Speak into the microphone; spectrum reacts.
3. Play system audio; system spectrum reacts.
4. Confirm Assistant displays both separate source badges.
5. Confirm Meeting captures system audio only by default.
6. Confirm Voice Input does not react to system audio.
7. Pause/Resume capture.
8. Stop and restart capture multiple times.
9. Disconnect/reconnect the selected device.
10. Switch through all five modes.
11. Verify live transcript and final report for Meeting and Interview Notes.
12. Complete a full Interview Practice Q/A/feedback cycle.
13. Drag the pill in compact and expanded states.
14. Toggle Focus on/off and switch modes.
15. Trigger manual Sleep/Wake.
16. Keep a Meeting active beyond the configured idle threshold and verify it is not paused automatically.
17. Verify local-only mode with network calls blocked or mocked.
18. Close the application and verify all streams and threads are released.

### Required agent final report

At completion, provide:

1. Root-cause audit with file/line references.
2. Files changed and why.
3. P0/P1/P2 items completed.
4. Automated tests run and results.
5. Windows manual tests performed and not performed.
6. Current limitations.
7. Remaining backlog from `BLUEPRINT.md`.

If the task is too large for one pass, complete **P0 audio capture + real spectrum + local-only enforcement + session safety** first. Keep the repository stable and report what remains. Do not spend the first pass rebranding, adding decorative UI, or implementing advanced AI features while the primary audio pipeline is broken.

---

# PART III — RECOMMENDED IMPLEMENTATION ORDER

Use this sequence to prevent rework:

1. **P0.1:** Fix real system loopback capture and device error behavior.
2. **P0.2:** Fix microphone/system capture lifecycle and mode routing.
3. **P0.3:** Implement actual audio spectrum/level pipeline and validate the JS bridge.
4. **P0.4:** Fix canonical session/transcript events and state transitions.
5. **P0.5:** Enforce local-only privacy across ASR and LLM.
6. **P1.1:** Wire Meeting, Interview Practice, Interview Notes, and Voice Input end-to-end.
7. **P1.2:** Prevent active sessions from auto-sleeping; add manual Sleep and persistent Focus.
8. **P1.3:** Validate/improve the existing native drag grip.
9. **P1.4:** Refine UI hierarchy and add contextual mode panels while preserving the current theme.
10. **P2:** Integrate Windows-MCP behind the existing DesktopGateway and migrate tool-by-tool.

**Do not mark a phase complete based solely on code being present. Each item needs a test result.**

---

# PART IV — REFERENCES

## Current project

- Nana / Malva repository: https://github.com/Fattan-malva/Nana
- Blueprint in repository: https://github.com/Fattan-malva/Nana/blob/master/BLUEPRINT.md
- Handoff notes: https://github.com/Fattan-malva/Nana/blob/master/HANDOFF.md

## Audio and ASR

- PyAudioWPatch: https://github.com/s0d3s/PyAudioWPatch
- Faster-Whisper: https://github.com/SYSTRAN/faster-whisper
- Qwen3-ASR: https://github.com/QwenLM/Qwen3-ASR
- OpenWhispr: https://github.com/OpenWhispr/openwhispr

## Desktop automation

- Windows-MCP: https://github.com/CursorTouch/Windows-MCP

## UI quality references

- Hallmark: https://github.com/Nutlope/hallmark
- Impeccable: https://github.com/pbakaus/impeccable

## Windows API

- SetWindowDisplayAffinity: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity

---

**End of audit and agent prompt v2.**

This document is based on the public `master` source snapshot identified above. Confirm the local working tree and rerun the acceptance tests before treating any issue as fixed.
