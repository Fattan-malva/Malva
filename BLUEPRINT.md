# Malva --- Product & Technical Blueprint v1

> **Status:** Product direction / planning draft\
> **Project:** Malva (rebrand and evolution of Nana)\
> **Tagline:** Your computer, understood.\
> **Product category:** Private AI Desktop Copilot\
> **Primary design principle:** Small interface. Deep intelligence.
> User-controlled privacy.

------------------------------------------------------------------------

## 1. Purpose of this document

This document defines the initial product direction, functional modes,
architecture, technical boundaries, privacy principles, and development
roadmap for **Malva**.

It is written in Markdown so it can be read by humans and AI coding
agents. Mermaid diagrams are included as fenced `mermaid` code blocks.
An AI agent should preserve the requirements and constraints in this
document unless the project owner explicitly changes them.

This is a planning blueprint, not an instruction to begin implementation
immediately. Before implementation, inspect the current Nana repository
and validate the proposed architecture against its actual framework,
code, dependencies, and runtime constraints.

## 2. Product vision

Malva is a private AI desktop copilot that understands audio,
conversations, and desktop context, then helps the user turn that
context into useful actions.

Malva has three product foundations:

1.  **Voice Intelligence** --- capture audio from explicitly selected
    sources, transcribe multilingual speech, and understand spoken
    context.
2.  **Conversation Intelligence** --- support assistant conversations,
    meetings, and interviews; extract summaries, decisions, and action
    items.
3.  **Desktop Intelligence** --- understand and interact with Windows
    applications through a controlled desktop-tool integration.

### Product principles

-   Local-first processing for audio and transcripts wherever practical.
-   Small, unobtrusive floating-pill UI as the primary interaction
    surface.
-   Separate audio sources and preserve source metadata.
-   Explicit user control over capture, privacy, and consequential
    actions.
-   Modular architecture: audio, ASR, AI orchestration, desktop
    automation, UI, and storage should not be tightly coupled.
-   Never claim performance, accuracy, or capture compatibility before
    testing.
-   Keep original transcripts distinct from AI-generated summaries,
    translations, and interpretations.

## 3. Confirmed product decisions

  -----------------------------------------------------------------------
  Area                                Decision
  ----------------------------------- -----------------------------------
  Product name                        Malva (replacing Nana)

  Interview Mode                      Both Interview Practice and
                                      Interview Notes

  Main UI                             Pill-first; floating pill is the
                                      default surface

  Focus Mode                          Always available; user can turn it
                                      on and leave it active until
                                      disabled

  ASR language setting                Auto and Manual

  ASR direction                       Cloud speech recognition
                                      (Gemini Live transcription). No
                                      local models. Free tier during the
                                      test phase.

  Cloud processing                    Approved for every service: speech
                                      (Gemini), LLM (Ollama cloud), and
                                      web search. Controlled by the
                                      CLOUD_ENABLED setting, not by an
                                      in-app opt-in. Revisit before
                                      production (free-tier data use).

  Tool permissions                    All Windows-MCP tools are granted
                                      automatically. Only destructive
                                      actions (delete) need approval,
                                      given by a click or by a spoken
                                      phrase from the microphone. Closing
                                      a tab or an app is not destructive.

  Desktop integration                 Windows-MCP as a separately managed
                                      integration

  Hidden Mode                         Privacy-oriented capture exclusion
                                      where supported; no universal
                                      invisibility guarantee

  Sleep Mode                          Preserve existing concept and
                                      distinguish it from Focus Mode
  -----------------------------------------------------------------------

## 4. Operating modes

Modes are profiles that configure audio sources, AI behavior, session
behavior, and output format. They are not separate applications.

  -----------------------------------------------------------------------
  Mode                    Default audio source    Purpose
  ----------------------- ----------------------- -----------------------
  Assistant               Microphone + system     General assistant and
                          audio, kept as separate context understanding
                          tracks                  

  Meeting                 System audio only       Meeting transcription,
                                                  summaries, decisions,
                                                  action items

  Interview Practice      Microphone as primary   Simulated interviewer
                          input; system audio     and answer feedback
                          optional for practice   
                          scenarios               

  Interview Notes         User-selected source(s) Record and organize
                                                  interview questions and
                                                  answers

  Voice Input             Microphone only         Convert the user's
                                                  speech into text input

  Focus                   Does not select audio   Keep the active session
                          sources; applies        available and reduce
                          session behavior to the distractions
                          active mode             
  -----------------------------------------------------------------------

### Audio-source invariants

-   **Assistant:** microphone and system audio may both be captured, but
    must remain separate tracks.
-   **Meeting:** system audio only by default. The user's microphone can
    be enabled as an optional, separate track.
-   **Interview Practice:** microphone is the primary source. System
    audio is optional and explicitly selected.
-   **Interview Notes:** source selection depends on the interview
    setup.
-   **Voice Input:** microphone only. System audio must not enter this
    pipeline.
-   **Focus:** must not silently change the active audio sources or
    capture permissions.

The application must make the active sources visible to the user.

## 5. UI and interaction model

### Pill-first UI

The floating pill is the primary UI. It should remain compact and must
not grow automatically whenever a transcript segment or AI response
arrives.

The pill should provide at-a-glance information such as:

-   Current mode.
-   Session state (idle, listening, processing, paused, error).
-   Microphone/system-audio capture status.
-   Focus Mode status.
-   Hidden Mode status, if enabled.
-   A clear way to expand, pause, or stop the session.

### Expanded panel

The expanded panel is a compact companion surface, not a full dashboard.
It may show:

-   Recent transcript segments.
-   A small AI response area.
-   Quick controls for the current session.
-   Shortcuts to settings or the full workspace.

Long content must scroll internally instead of causing unbounded window
growth.

### UI behavior requirements

-   No automatic expansion for every transcript or AI response.
-   Important events may offer an expansion affordance, but must not
    force expansion.
-   User can collapse the panel at any time.
-   User can lock the size and position.
-   Support drag positioning, multi-monitor placement, and optional
    always-on-top.
-   Full settings and history belong in a separate workspace.
-   Maintain readable status indicators without requiring the user to
    open a large window.

### Conceptual UI diagram

``` mermaid
flowchart TD
    P[Floating Pill] --> Q[Quick Panel]
    P --> W[Workspace]
    Q --> S[Current Session Status]
    Q --> T[Recent Transcript]
    Q --> A[Quick AI Interaction]
    Q --> C[Session Controls]
    W --> H[Session History]
    W --> M[Meeting and Interview Reports]
    W --> X[Search and Export]
    P --> ST[Settings]
    ST --> AU[Audio and ASR Settings]
    ST --> PR[Privacy Settings]
    ST --> UI[Appearance and Shortcuts]
```

## 6. Interview Mode

Interview Mode contains two distinct submodes.

### 6.1 Interview Practice

Purpose: help the user prepare before an interview.

Capabilities:

-   AI acts as an interviewer.
-   Support behavioral, technical, coding, and situational interview
    scenarios.
-   User answers through the microphone.
-   Evaluate answer structure, relevance, clarity, specificity, and
    completeness.
-   Provide coaching and suggestions for improvement.
-   Generate a session report and recommend future practice topics.

### 6.2 Interview Notes

Purpose: organize interviews such as job interviews, user research,
journalism, and business interviews.

Capabilities:

-   Transcribe the selected audio sources.
-   Group questions and answers.
-   Track timestamps and speaker labels when available.
-   Organize content by topic.
-   Generate summaries, key quotes, and follow-up questions.
-   Export an editable report.

### Separation requirements

Interview Practice and Interview Notes must have separate:

-   Prompt and instruction sets.
-   Session configuration.
-   Output/report structure.
-   Evaluation logic.
-   Relevant settings.

Live assistance during real interviews must respect the organizer's
rules and participant expectations. Do not design the product to
disguise prohibited assistance or misrepresent whether AI is being used.

## 7. Focus Mode and Sleep Mode

Focus Mode is a persistent, user-controlled operating mode that can be
enabled at any time and remains active until disabled.

### Focus Mode behavior

-   Do not automatically end a session merely because the user is not
    interacting with the UI.
-   Keep the floating pill available.
-   Keep the active audio pipeline running according to the selected
    mode and permissions.
-   Suppress nonessential notifications.
-   Prevent automatic UI expansion.
-   Preserve pause, stop, emergency-stop, and privacy controls.
-   Do not silently change Windows power/sleep policy.

### Sleep Mode behavior

Sleep Mode remains a separate resource-saving state. It may pause or
place services into standby according to the existing product behavior.

  Behavior                     Sleep Mode                           Focus Mode
  ---------------------------- ------------------------------------ --------------------------
  Primary goal                 Save resources                       Maintain active workflow
  Active session               Paused/standby according to policy   Remains active
  Nonessential notifications   Minimal                              Suppressed
  Audio pipeline               Stopped or standby                   Follows active mode
  Windows power policy         No silent changes                    No silent changes

Focus Mode cannot keep the application running through application exit,
Windows shutdown, or power loss.

## 8. Audio architecture

Audio capture must be separated from ASR and AI orchestration. Capture
microphone and system audio independently and preserve their metadata.

``` mermaid
flowchart TD
    DEV[Windows Audio Devices] --> CAP[Audio Capture Service]
    CAP --> MIC[Microphone Track]
    CAP --> SYS[System Audio Track]
    MIC --> ROUTER[Audio Source Router]
    SYS --> ROUTER
    ROUTER --> ASSIST[Assistant Profile]
    ROUTER --> MEET[Meeting Profile]
    ROUTER --> PRACTICE[Interview Practice]
    ROUTER --> NOTES[Interview Notes]
    ROUTER --> VOICE[Voice Input]
    ASSIST --> ASR[ASR Pipeline]
    MEET --> ASR
    PRACTICE --> ASR
    NOTES --> ASR
    VOICE --> ASR
    ASR --> EVENTS[Transcript Events]
    EVENTS --> AI[AI Orchestrator]
    AI --> UI[Malva UI]
```

### Audio track metadata

Each track should preserve, where applicable:

-   Source type and device identifier.
-   Session identifier.
-   Timestamp and timing alignment.
-   Sample rate and channel count.
-   Track state and permission state.
-   Audio format and processing metadata.

### Audio safety and correctness

-   Do not silently mix microphone and system audio into one track.
-   Voice Input must reject system-audio input at the routing layer, not
    merely hide it in the UI.
-   Meeting Mode must default to system audio only.
-   Optional microphone capture in Meeting Mode must be visibly
    indicated and stored separately.
-   Provide a clear capture indicator and emergency stop.

## 9. ASR architecture

Speech recognition runs in the cloud with the **Gemini Live API**, model
`gemini-3.5-transcribe-live`. Malva has no local recognition model.

-   Each audio source (microphone, system audio) has its own stream, so
    the two tracks are never mixed.
-   Audio is sent as 16-bit PCM, 16 kHz, mono (`audio/pcm;rate=16000`).
    Device audio at other rates is resampled before sending.
-   The model runs with `response_modalities=["TEXT"]`, so it does not
    generate spoken replies.
-   `interim_input_transcription` gives live partial text while someone
    speaks. It is shown but not stored.
-   `input_transcription` gives the final text of one speech turn. Only
    final text enters the transcript store and goes to the AI.
-   A streaming session lasts at most 10 minutes. Malva reconnects before
    that limit (after 9 minutes). Audio captured during a reconnect is
    queued and sent when the connection is back. If the network stalls,
    the oldest audio is dropped and counted.
-   Speech activity (a simple level threshold) only resets the auto-sleep
    timer. It does not segment the audio.

Verified against the Gemini Live transcription documentation. Limits for
the free tier are not stated on that page and must be checked in AI Studio
before production use.

Speech that reaches the cloud is covered by the product decision in §3.
A missing `GEMINI_API_KEY` or `CLOUD_ENABLED=false` stops transcription,
and the user is told which one applies. Nothing falls back to another
service.

### Candidate models (historical)

Earlier drafts evaluated Qwen3-ASR and local Whisper models. Both were
removed when the design moved to cloud recognition. They are kept here
only as reference for future benchmarks.

### Language settings

Provide two user-facing settings:

-   **Auto:** detect language dynamically throughout the session. Do not
    detect only once at session start.
-   **Manual:** lock recognition to the selected language.

Auto mode should be tested for code-switching, including
Indonesian-English mixed speech. Store language metadata at the segment
level where the model supports it.

### Example transcript event

``` json
{
  "session_id": "session-example",
  "text": "Kita perlu review the deployment plan besok.",
  "segments": [
    {
      "text": "Kita perlu review",
      "language": "id"
    },
    {
      "text": "the deployment plan",
      "language": "en"
    },
    {
      "text": "besok.",
      "language": "id"
    }
  ]
}
```

This is a conceptual schema example, not a fixed implementation
contract.

### ASR settings

-   Auto / Manual language selection.
-   Model selection and model availability.
-   CPU/GPU device selection where supported.
-   Model size and memory profile.
-   Custom vocabulary for names, acronyms, and technical terms.
-   Confidence or uncertainty markers where available.
-   Chunking/buffering controls where useful.
-   `GEMINI_API_KEY` and `GEMINI_ASR_MODEL` in `.env`.
-   `CLOUD_ENABLED` (default `true`) as the single cloud switch.

### Benchmark requirements

Measure at least:

-   Time to first partial transcript.
-   Finalization delay.
-   Word Error Rate (WER) on representative datasets.
-   Indonesian, English, and mixed-language performance.
-   Noise and accent robustness.
-   CPU, GPU, RAM, and VRAM use.
-   Long-session stability.
-   Model startup and warm-up time.

## 10. Desktop Intelligence and Windows-MCP

Use **Windows-MCP** as a desktop interaction integration. Do not make it
responsible for native audio capture, ASR, storage, or the entire AI
orchestration layer.

``` mermaid
flowchart TD
    AI[Malva AI Orchestrator] --> GW[Desktop Tool Gateway]
    GW --> POLICY[Permission and Policy Layer]
    POLICY --> ADAPTER[Windows-MCP Adapter]
    ADAPTER --> WIN[Windows Desktop and Applications]
    POLICY --> AUDIT[Action Audit Log]
    AUDIT --> DB[(Local Storage)]
```

### Responsibility boundaries

  Component              Responsibility
  ---------------------- ---------------------------------------------------
  Windows-MCP            Supported desktop interaction capabilities
  Desktop Tool Gateway   Stable tool interface exposed to the AI layer
  Permission Layer       Check whether an action is allowed
  Policy Layer           Apply risk-based restrictions
  Audit Log              Record requested actions, approvals, and outcomes

### Risk-based permissions

Every tool is granted automatically. Approval is needed only for an
action that deletes something. The check looks at the tool name and the
arguments, so a delete hidden in a command or in typed text is also caught.

  -----------------------------------------------------------------------
  Action                                  Policy
  --------------------------------------- -------------------------------
  Any tool, including close tab or app    Automatic
  Anything that deletes files or data     Approval required: click in
                                          the panel, or say "setuju" /
                                          "ya hapus" (cancel: "batal")
  -----------------------------------------------------------------------

Voice approval rules:

-   Only the microphone can approve. System audio never approves.
-   The whole utterance must be one approval phrase. A sentence that
    contains the word does not count.
-   Only a pending destructive action can be approved, and only within
    120 seconds of being proposed. The newest pending action is the one
    approved.

Run Windows-MCP as a separate process or service where practical. This
reduces dependency and runtime coupling with the desktop application and
audio services.

## 11. Hidden Mode and privacy

Hidden Mode is a **privacy-oriented capture-exclusion feature**. It may
request that Windows exclude the Malva window from compatible capture
paths while the window remains visible to the local user.

A Windows API to evaluate is:

-   `SetWindowDisplayAffinity`
-   `WDA_EXCLUDEFROMCAPTURE`

This is not a universal invisibility guarantee. Compatibility depends on
Windows version, capture method, application, and capture source. It
cannot guarantee exclusion from every OBS, Zoom, Discord, Google Meet,
Teams, recorder, remote-desktop path, or external camera.

### Required behavior

1.  User manually enables Hidden Mode.
2.  Malva attempts the supported Windows capture-exclusion mechanism.
3.  Malva reports the actual result.
4.  UI status must distinguish:
    -   `Capture Exclusion Active`
    -   `Unsupported`
    -   `Failed`
5.  User can disable the mode at any time.
6.  Do not silently alter recording indicators, audio permissions, or
    another application's recording state.
7.  Do not claim that all capture or recording paths are blocked.

### Privacy settings

-   Cloud processing is approved for speech, LLM, and web search (§3),
    and is switched with `CLOUD_ENABLED`.
-   Per-application audio allow/deny rules where supported.
-   Configurable transcript and audio retention.
-   Delete session and related data.
-   Clear audio-capture indicators.
-   Emergency stop.
-   Encryption for sensitive local data.

## 12. Local storage and data model

Use **SQLite** as the initial local database candidate. Avoid
introducing a cloud database before there is a concrete synchronization
requirement.

Suggested logical tables:

  Table                   Purpose
  ----------------------- --------------------------------------------
  `sessions`              Assistant, Meeting, and Interview sessions
  `audio_tracks`          Audio source and track metadata
  `transcript_segments`   Text, timestamps, language, speaker
  `speakers`              Session-local speaker identities
  `meeting_notes`         Summaries and notes
  `decisions`             Extracted decisions
  `action_items`          Tasks, owners, deadlines, status
  `interview_reports`     Practice and Notes reports
  `model_registry`        ASR model and runtime configuration
  `app_settings`          User preferences
  `tool_audit_logs`       Desktop tool requests and outcomes

### Data integrity rules

-   Never overwrite raw transcript text with AI-generated content.
-   Keep original transcript, corrected transcript, translation,
    summary, and AI interpretation distinguishable.
-   Preserve timestamps and source-track references.
-   Keep session IDs stable.
-   Make retention and deletion behavior explicit.
-   Store enough provenance to trace generated summaries and action
    items to transcript segments.

## 13. Differentiating features

Prioritize integration and reliability over adding many disconnected
features.

### 13.1 Cross-Meeting Memory

-   Find decisions across sessions.
-   Identify potentially conflicting decisions.
-   Track unresolved action items.
-   Connect recurring project names and topics.
-   Cite the original session and timestamp.
-   Clearly distinguish source statements from AI inference.

### 13.2 Decision-to-Execution

1.  Detect candidate action items.
2.  Show them to the user for review.
3.  Ask for approval before consequential actions.
4.  Execute through an authorized integration.
5.  Track completion where the integration supports it.

### 13.3 Screen-Aware Meeting

-   Optionally capture screen context with explicit user permission.
-   Associate permitted screenshots or slide context with transcript
    timestamps.
-   Do not continuously capture the screen without a clear user-visible
    state and permission.
-   Respect app-level privacy rules.

### 13.4 Multilingual Meeting Bridge

-   Preserve original transcript.
-   Provide optional translation.
-   Keep technical terms and names intact where possible.
-   Make original and translated text distinguishable.

### 13.5 Custom Vocabulary

-   User-defined names, acronyms, project terms, and technical
    vocabulary.
-   Vocabulary can be scoped to a session or project.
-   Never silently rewrite source transcripts without preserving the
    original.

## 14. Proposed application architecture

The final framework and technology choices must follow a repository
audit. The following is a logical module layout, not a requirement to
use a specific programming language or folder structure.

``` mermaid
flowchart TB
    UI[Malva Floating Pill UI]
    SHELL[Desktop Application Shell]
    CORE[Malva Core]
    AUDIO[Audio Capture Service]
    ASR[ASR Engine and Model Router]
    TRANSCRIPT[Transcript Core]
    AI[AI Orchestrator]
    MEETING[Meeting Engine]
    INTERVIEW[Interview Engine]
    DESKTOP[Desktop Tool Gateway and Windows-MCP Adapter]
    PRIVACY[Privacy and Permission Manager]
    STORAGE[(Local Database)]

    UI --> SHELL
    SHELL --> CORE
    CORE --> AUDIO
    CORE --> ASR
    CORE --> TRANSCRIPT
    CORE --> AI
    CORE --> MEETING
    CORE --> INTERVIEW
    CORE --> DESKTOP
    CORE --> PRIVACY
    CORE --> STORAGE
    AUDIO --> ASR
    ASR --> TRANSCRIPT
    TRANSCRIPT --> AI
    AI --> MEETING
    AI --> INTERVIEW
    AI --> DESKTOP
    PRIVACY --> AUDIO
    PRIVACY --> DESKTOP
    AI --> STORAGE
    MEETING --> STORAGE
    INTERVIEW --> STORAGE
```

### Suggested logical modules

  Module               Responsibility
  -------------------- ------------------------------------------
  `app-shell`          Lifecycle, tray, windows, shortcuts
  `floating-ui`        Pill, compact panel, positioning
  `audio-engine`       Microphone and system audio capture
  `asr-engine`         Model loading, routing, streaming
  `transcript-core`    Segments, timestamps, language, speakers
  `ai-orchestrator`    Prompts, context, model providers, tools
  `meeting-engine`     Summaries, decisions, action items
  `interview-engine`   Practice and Notes workflows
  `desktop-engine`     Windows-MCP adapter and tool gateway
  `privacy-engine`     Permissions, Hidden Mode, retention
  `storage-engine`     Database, search, export

## 15. Development roadmap

### Phase 0 --- Repository audit and foundations

-   Inspect Nana repository structure and current branch.
-   Identify desktop framework, language, build system, dependencies,
    audio stack, UI, storage, and packaging.
-   Map existing features to the proposed Malva modules.
-   Identify reusable code, refactor candidates, and replacement
    candidates.
-   Verify Windows-MCP runtime and dependency requirements.
-   Define the design system and product naming migration.
-   Do not perform a broad rewrite before the audit.

### Phase 1 --- Malva Core

-   Rebrand Nana to Malva.
-   Implement the floating pill.
-   Separate audio capture service.
-   Implement microphone/system audio track isolation.
-   Preserve Sleep Mode.
-   Add Focus Mode.
-   Add core settings and session state.

### Phase 2 --- Voice Intelligence

-   Implement ASR Model Router.
-   Benchmark Gemini Live transcription on representative Indonesian and English audio.
-   Add Auto and Manual language settings.
-   Add live transcription.
-   Add transcript storage and source metadata.
-   Add custom vocabulary if supported by the selected ASR pipeline.

### Phase 3 --- Conversation Intelligence

-   Assistant Mode.
-   Meeting Mode.
-   Interview Practice.
-   Interview Notes.
-   Summaries, decisions, and action items.
-   Exportable reports.

### Phase 4 --- Desktop Intelligence

-   Windows-MCP adapter.
-   Desktop Tool Gateway.
-   Permission and risk policy.
-   Action audit log.
-   Desktop context awareness.

### Phase 5 --- Privacy and advanced intelligence

-   Hidden Mode with honest compatibility status.
-   Cross-Meeting Memory.
-   Decision-to-Execution.
-   Screen-Aware Meeting.
-   Multilingual Meeting Bridge.

## 16. Definition of Done --- Malva v1

-   [ ] Floating pill remains compact during normal use.
-   [ ] User can collapse and expand the UI manually.
-   [ ] Transcript updates do not force UI expansion.
-   [ ] Audio sources are isolated into separate tracks.
-   [ ] Voice Input cannot receive system audio.
-   [ ] Meeting Mode defaults to system audio only.
-   [ ] Optional microphone capture is visibly indicated.
-   [ ] Indonesian and English recognition are benchmarked.
-   [ ] Auto language behavior is tested across language changes.
-   [ ] Focus Mode keeps the active Malva session available according to
    policy.
-   [ ] Sleep Mode remains distinct.
-   [ ] Interview Practice and Interview Notes have separate workflows.
-   [ ] Windows-MCP actions pass through a permission layer.
-   [ ] Consequential actions require explicit approval.
-   [ ] Hidden Mode reports actual compatibility and does not promise
    universal invisibility.
-   [ ] Original transcripts remain separate from AI-generated outputs.
-   [ ] Local data retention and deletion are user-controllable.

## 17. Repository audit checklist

Before implementation, inspect the existing Nana project and answer:

1.  What desktop framework and programming languages does it use?
2.  How are windows, tray behavior, and global shortcuts implemented?
3.  How is microphone capture implemented?
4.  Is system audio capture already available?
5.  Are microphone and system audio mixed or isolated?
6.  What transcription provider/model is currently used?
7.  How are AI providers and prompts configured?
8.  What database or local storage is used?
9.  How are settings and secrets stored?
10. How is the application packaged and updated?
11. Which dependencies conflict with Windows-MCP?
12. Which existing features should remain compatible?

The output of this audit should be a file-level migration map: `KEEP`,
`REFACTOR`, `REPLACE`, `ADD`, or `REMOVE`, each with a reason and
dependencies.

## 18. Reference repositories and documentation

### Project repositories

-   **Nana (current project to audit and evolve):**
    https://github.com/Fattan-malva/Nana
-   **Windows-MCP (desktop interaction reference):**
    https://github.com/CursorTouch/Windows-MCP
-   **OpenWhispr (voice/transcription reference):**
    https://github.com/OpenWhispr/openwhispr

### Design quality and anti-AI-slop references

-   **Hallmark:** https://github.com/Nutlope/hallmark
    -   Design skill and visual quality checks intended to help coding
        agents avoid generic AI-generated interfaces.
-   **Impeccable:** https://github.com/pbakaus/impeccable
    -   Design vocabulary and critique/audit toolkit for improving
        interface quality.

Use these as references and evaluation aids. Do not copy their visual
identity. Malva needs its own coherent design system.

### Microsoft documentation

-   **SetWindowDisplayAffinity:**
    https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity
    -   Documentation for the Windows window display affinity API
        relevant to capture-exclusion experiments. This is not a
        guarantee against all capture methods.

### Reference usage notes

-   Re-check repository documentation, licenses, releases, and runtime
    requirements before adopting code or dependencies.
-   A repository being open source does not automatically mean its code
    can be copied without license review.
-   Treat model language support, streaming support, hardware
    requirements, and performance as version-dependent facts to verify
    during implementation.
-   Record the exact versions/commits used in the eventual technical
    implementation plan.

## 19. Instructions for AI coding agents

When using this blueprint as project context:

1.  Read this document before proposing architecture changes.
2.  Inspect the actual repository before making implementation
    assumptions.
3.  Preserve the confirmed product decisions in Section 3.
4.  Treat the diagrams as logical architecture, not proof that the
    current code already has those modules.
5.  Do not replace the existing framework without an explicit migration
    rationale.
6.  Do not implement Hidden Mode as a promise of universal capture
    invisibility.
7.  Do not merge microphone and system audio into one indistinguishable
    track.
8.  Do not add cloud calls or destructive desktop capabilities that are
    not listed in §3 and §10. Cloud and approval rules are product
    decisions and must be changed here first.
9.  Keep original transcripts and AI-generated outputs separate.
10. Propose changes in small, testable phases.
11. When making a technical claim that depends on a library or API
    version, verify it against current upstream documentation. The
    Gemini Live transcription page is the reference for §9.
12. If a requirement conflicts with the existing repository or platform
    limitations, explain the conflict and propose alternatives instead
    of silently ignoring the requirement.

------------------------------------------------------------------------

**End of Blueprint v1**

This document is the product and architecture baseline for the next
step: audit the Nana repository and produce a file-level Malva migration
plan.
