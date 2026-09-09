# EDMG Studio Master Blueprint
## Unified AI Director + Hardware-Aware Video Renderer + Professional DAW/Timeline Architecture

**Target:** Codex implementation handoff  
**Product:** EDMG Studio / EDMG AI Studio  
**Status:** Master implementation blueprint  
**Primary objective:** Unify the AI-generation system and rebuild the timeline/audio/video editing side into a professional DAW-style production environment while retaining external/API providers.

---

# 1. Executive Summary

EDMG Studio should become one integrated production environment with three tightly connected pillars:

1. **AI Director**
   - Qwen3-VL family
   - understands lyrics, prompts, images, generated frames/video, continuity, and project context
   - outputs structured scene plans instead of generic prompt prose

2. **Unified Hardware-Aware Video Renderer**
   - HunyuanVideo-1.5 for low/standard hardware
   - LTX-2.5 Distilled for stronger hardware
   - automatically selected by hardware capability
   - external/API providers remain available through a modular provider layer

3. **Professional DAW/Timeline Production Environment**
   - multitrack audio/video/MIDI/AI timeline
   - frame-accurate and sample-accurate editing
   - mixer, inserts, sends, automation, buses, markers, cue tracks, media pool, plugin host
   - logical editing/macros
   - project templates/workspaces
   - MIDI remote/control mappings
   - professional post-production workflow
   - AI generation exists directly on the timeline instead of beside it

The result should feel like a serious DAW/post-production editor with a first-class AI video generation system built into the same project model.

---

# 2. Important Clean-Room Rule

The supplied Nuendo installation archives were inspected only to identify architectural patterns, component categories, workflow concepts, and interoperability ideas.

Observed categories included:

- VST3 plugin hosting/scanning
- MIDI remote scripting/control surfaces
- logical/project editing presets
- project templates
- quick controls
- window layouts
- audio alignment
- audio-to-chords
- markers/events
- reconform
- AAF/EDL/DAWproject-style interchange components
- ADR/dialogue components
- ADM/BWF and Dolby Atmos-related components
- video engine and video cut detection
- media services
- OSC and EUCON adapters
- sampler/drum components
- scoring/chord resources
- project logical editor categories such as automation, mixing, naming, nudge, quantize, selection, tempo/signature, tracks, visibility, record/monitor, parts/events
- track/transport/control-room abstractions exposed through MIDI remote APIs
- plugin snapshots and modular VST bundles

**Do not copy, redistribute, embed, decompile, or reuse Steinberg proprietary binaries, assets, fonts, presets, skins, project templates, or source code.**

Codex should implement equivalent EDMG functionality using original code, public specifications, documented APIs, and EDMG-owned assets.

---

# 3. Product Goals

## 3.1 Primary Goals

1. Build one coherent internal generation engine.
2. Build one coherent timeline/project model shared by AI, audio, video, MIDI, automation, and post-production.
3. Keep external/API providers supported.
4. Make local generation work from low-tier GPUs to multi-GPU workstations.
5. Preserve real generated motion on low-tier systems.
6. Improve prompt quality, continuity, motion planning, and project-level story understanding.
7. Make EDMG usable as an actual DAW/post-production editor, not merely a generation frontend.
8. Reduce duplicated renderer options and model bloat.
9. Ensure both Electron and WinUI frontends operate against the same project/engine contracts.
10. Keep the architecture extensible without exposing complexity to ordinary users.

---

# 4. Non-Goals for the First Rewrite

Do not attempt to implement every possible professional DAW feature in the first milestone.

Do not:

- copy Nuendo UI or assets pixel-for-pixel
- implement every audio codec immediately
- implement every cloud provider immediately
- support every local video model
- support every control-surface protocol immediately
- build full music notation before the core timeline is stable
- attempt complete Dolby Atmos authoring before ordinary multichannel routing is stable
- mix renderer-specific logic directly into timeline UI code
- build separate timeline engines for Electron and WinUI

---

# 5. Final High-Level Architecture

```text
                         EDMG PROJECT
                              │
           ┌──────────────────┼──────────────────┐
           │                  │                  │
           ▼                  ▼                  ▼
       DAW/TIMELINE        AI DIRECTOR       MEDIA SYSTEM
           │                  │                  │
           │                  │                  │
           └────────────┬─────┴───────┬──────────┘
                        │             │
                        ▼             ▼
                   SceneSpec      StoryBible
                        │
                        ▼
                 Renderer Manager
                        │
           ┌────────────┼────────────┐
           │            │            │
           ▼            ▼            ▼
        Hunyuan       LTX-2.5     External APIs
           │            │            │
           └────────────┼────────────┘
                        ▼
                  Generated Media
                        │
                        ▼
                    TIMELINE
                        │
           ┌────────────┼────────────┐
           ▼            ▼            ▼
         Mixer      Automation      Video
           │            │            │
           └────────────┼────────────┘
                        ▼
               Post Processing / Export
```

---

# 6. Preserve External/API Provider Support

## Decision

**Yes. Keep it.**

External/API providers remain an important optional capability.

They must not, however, dictate the internal renderer architecture.

## Rules

- Internal renderer must work independently of cloud services.
- Existing providers must not be removed merely because local generation improves.
- Existing provider-specific code should gradually be wrapped in normalized adapters.
- New external providers should be addable without modifying the timeline core.
- Cloud provider selection belongs under renderer/provider settings, not as separate competing editor modes.

## Provider hierarchy

```text
IGenerationProvider
│
├── InternalGenerationProvider
│   ├── HunyuanRenderer
│   └── LtxRenderer
│
└── ExternalGenerationProvider
    ├── ExistingProviderAdapter
    ├── ExistingProviderAdapter2
    └── FutureProviderAdapter
```

---

# 7. Model Strategy

## 7.1 Director Family

### Standard
`Qwen3-VL-8B-Instruct`

### High Tier
`Qwen3-VL-30B-A3B-Instruct`

Use one Director family to reduce behavior divergence.

---

## 7.2 Video Renderer Family

### Low / Standard
`HunyuanVideo-1.5`

### High / Ultra
`LTX-2.5 Distilled`

---

## 7.3 Explicitly Deferred

Do not make these first-class required models during this rewrite:

- Wan 2.2
- MiniMax H3
- FastH3
- Kling
- additional experimental video families

Adapters can be added later.

---

# 8. Hardware-Aware Tiers

## Tier A — Low

Example:
- NVIDIA RTX 4050 6 GB
- 16 GB RAM minimum
- 32 GB RAM preferred

Use:
- Qwen3-VL-8B quantized/offloaded
- HunyuanVideo-1.5 low-VRAM mode
- shorter generation chunks
- lower working resolution
- post upscale/interpolation

This tier must still provide:
- real generated subject motion
- camera movement
- environmental motion
- T2V/I2V capability
- continuity support

It must not become a slideshow renderer.

---

## Tier B — Standard

Example:
- 8–16 GB VRAM
- 32 GB RAM

Use:
- Qwen3-VL-8B
- HunyuanVideo-1.5
- optional LTX qualification where testing proves safe

---

## Tier C — High

Example:
- 24 GB VRAM

Use:
- Qwen3-VL-30B-A3B if installed
- LTX-2.5
- Hunyuan optional as fast-preview renderer

---

## Tier D — Ultra

Example:
- 48 GB+ VRAM
- multiple large GPUs

Use:
- Qwen3-VL-30B-A3B
- LTX-2.5 maximum profile
- parallel post-processing
- optional second GPU worker
- model staging across GPUs where officially supported

---

# 9. User-Facing Renderer Modes

Normal users should see:

- **Automatic**
- **Fast**
- **Quality**
- **Maximum**

Not a list of model names.

## Automatic
Hardware profiler chooses the safest/best path.

## Fast
Prefer fastest installed suitable renderer/profile.

## Quality
Prefer LTX when qualified, otherwise highest-quality Hunyuan profile.

## Maximum
Use strongest installed local renderer or explicitly selected external provider.

Advanced settings may expose direct engine selection.

---

# 10. AI Director System

The Director is not merely a prompt enhancer.

It is a project-aware planning and review system.

## Responsibilities

- interpret user concept
- read transcript/lyrics
- use timestamps
- consume audio analysis
- create scene plans
- maintain character identity
- maintain locations
- maintain visual style
- plan camera motion
- plan subject motion
- plan environmental motion
- plan transitions
- manage project story progression
- inspect generated frames/clips
- detect continuity drift
- create corrections
- compile model-specific prompts

---

# 11. StoryBible

Implement a typed persistent `StoryBible`.

Recommended fields:

```text
StoryBible
├── ProjectTheme
├── NarrativeSummary
├── Characters[]
├── Locations[]
├── Props[]
├── Wardrobe[]
├── VisualStyle
├── ColorPalette
├── LightingRules
├── CameraLanguage
├── MotionLanguage
├── ContinuityRules
├── ForbiddenChanges[]
├── RecurringMotifs[]
├── TimelineStoryState
└── Revision
```

Every AI-generated scene should reference the same project StoryBible.

---

# 12. SceneSpec

The Director must create structured data first.

Do not make freeform prompt text the authoritative project representation.

Example:

```json
{
  "scene_id": "scene_001",
  "timeline_start_seconds": 0.0,
  "duration_seconds": 6.0,
  "intent": "traveler enters abandoned town",
  "continuity_mode": "continuous",
  "subjects": [
    {
      "id": "traveler_01",
      "role": "primary",
      "appearance_lock": true,
      "expression": "uneasy and alert"
    }
  ],
  "actions": [
    "walks slowly toward town center",
    "looks toward a dark upstairs window"
  ],
  "camera": {
    "shot_type": "medium-wide",
    "movement": "slow forward tracking",
    "motion_strength": 0.4
  },
  "environment": {
    "location_id": "town_01",
    "weather": "thin drifting fog",
    "secondary_motion": [
      "fog crosses road",
      "branches move in wind"
    ]
  },
  "motion": {
    "subject": 0.6,
    "camera": 0.35,
    "environment": 0.45
  },
  "renderer_hints": {
    "mode": "automatic",
    "prefer_i2v": false,
    "target_quality": "balanced"
  }
}
```

---

# 13. Prompt Compiler Layer

Create:

- `HunyuanPromptCompiler`
- `LtxPromptCompiler`
- `ExternalProviderPromptCompiler`

The same SceneSpec can therefore target different engines.

## Hunyuan compiler
Prefer:
- descriptive prose
- explicit subject motion
- explicit environment motion
- clear shot/camera description
- concrete actions

## LTX compiler
Prefer:
- chronological action
- cinematic temporal wording
- action evolution over time
- camera motion and scene dynamics
- coherent narrative description

External providers get their own adapters.

---

# 14. Director Review Loop

The Director should be capable of reviewing generated output.

Flow:

```text
SceneSpec
   ↓
Render
   ↓
Generated Clip
   ↓
Frame/Video Review
   ↓
ReviewReport
   ↓
CorrectionPlan
   ↓
Next SceneSpec or Optional Regeneration
```

Review dimensions:

- character consistency
- wardrobe consistency
- environment consistency
- intended action presence
- subject-motion strength
- camera-motion correctness
- artifact detection
- temporal coherence
- continuity to previous scene
- visual style consistency

Do not automatically regenerate endlessly.

Use configurable thresholds and retry caps.

---

# 15. THE DAW/TIMELINE REBUILD

This is a major part of the architecture, not an afterthought.

The timeline should become the central production workspace.

AI scenes, audio, video, markers, MIDI, automation, generated versions, and final edits all live in one timeline model.

---

# 16. DAW Design Principles

The EDMG timeline should adopt professional DAW concepts:

1. **Track-based project structure**
2. **Event/clip-based editing**
3. **Sample-accurate audio time**
4. **Frame-accurate video time**
5. **Musical grid support**
6. **SMPTE/timecode support**
7. **Non-destructive editing**
8. **Command-based undo/redo**
9. **Real-time automation**
10. **Plugin hosting**
11. **Mixer separate from but synchronized with timeline**
12. **Marker/cue system**
13. **Media pool**
14. **Keyboard-first workflow**
15. **Control-surface mapping**
16. **Logical/query editing**
17. **Project templates/workspaces**
18. **Strong post-production support**
19. **AI generation directly attached to timeline events**

---

# 17. Unified Time Model

This is foundational.

Implement a canonical project time model supporting:

- absolute samples
- seconds
- nanoseconds where needed
- video frames
- SMPTE timecode
- bars/beats/ticks
- tempo map
- signature map

Recommended internal rule:

- audio placement ultimately resolves to **64-bit sample positions**
- video placement resolves through rational frame-rate math
- musical positions resolve through a tempo/signature map
- never use ordinary floating-point seconds as the sole canonical timeline coordinate

Required frame rates:

- 23.976
- 24
- 25
- 29.97
- 29.97 DF
- 30
- 50
- 59.94
- 60

Make timecode conversion a tested core service.

---

# 18. Timeline Track Types

Minimum professional set:

```text
Track
├── AudioTrack
├── VideoTrack
├── MidiTrack
├── InstrumentTrack
├── FolderTrack
├── GroupTrack
├── FXTrack
├── MarkerTrack
├── TempoTrack
├── SignatureTrack
├── AutomationTrack/Lane
├── AIVisualTrack
├── AIPromptTrack
├── SceneTrack
├── ReferenceTrack
└── Master/OutputTrack
```

Future:
- chord track
- arranger track
- ADR cue track
- object-audio track
- subtitle/dialogue track

---

# 19. Timeline Event Types

```text
TimelineEvent
├── AudioEvent
├── VideoEvent
├── MidiPart
├── AIClip
├── SceneEvent
├── MarkerEvent
├── AutomationEvent
├── TempoEvent
├── SignatureEvent
├── ReferenceEvent
└── Compound/NestedEvent
```

Every event requires:

- immutable ID
- start
- duration
- source reference
- source offset
- playback rate
- mute state
- lock state
- color/tag
- group/link ID
- version history reference
- metadata
- creation origin
- undo-safe revision data

---

# 20. Core Timeline Editing

Implement professional editing operations:

- select
- range select
- move
- trim start
- trim end
- split
- glue/join
- duplicate
- copy/paste
- cut
- ripple delete
- insert time
- remove time
- nudge
- slip
- slide
- time stretch
- playback-rate change
- fade in/out
- crossfade
- mute event
- lock event
- group events
- link audio/video
- snap
- quantize
- normalize/level process through non-destructive process descriptors where appropriate

All editing must use a command architecture for reliable undo/redo.

---

# 21. Editing Modes / Tools

Provide original EDMG tools inspired by professional DAWs:

- Object Select
- Range Select
- Split
- Draw
- Erase
- Mute
- Zoom
- Time Stretch
- Automation Draw

Optional:
- audition
- scrub
- warp marker
- comp tool

Keyboard modifiers should alter behavior where intuitive.

---

# 22. Snap/Grid Engine

Support:

- snap off
- grid
- events
- markers
- cursor
- zero-crossing for audio
- frames
- beats
- bars
- subdivisions
- adaptive grid

Snap engine should be a service independent from UI.

---

# 23. Track Lanes and Comping

Audio and AI/video tracks should support lanes.

Use lanes for:

- alternate recording takes
- generated variations
- regenerated AI clips
- alternate video takes
- comping

An AI scene should be able to keep:

```text
Scene 12
├── v1 original generation
├── v2 motion correction
├── v3 continuity correction
└── selected active take
```

Do not overwrite previous renders by default.

---

# 24. AI Clips as First-Class Timeline Objects

An AI-generated video must not simply appear as a loose output file.

Create `AIClip` / `SceneEvent` metadata containing:

- SceneSpec ID
- StoryBible revision
- provider ID
- model ID
- model version
- seed
- prompt package
- source references
- render profile
- render job ID
- output path
- source frame/reference path
- generation timestamp
- review score
- continuity score
- generation status
- retry history
- cost information for external APIs
- provenance

Right-click timeline actions:

- Regenerate
- Create Variation
- Improve Motion
- Improve Continuity
- Extend
- Reframe
- Re-prompt
- Review with Director
- Promote to StoryBible Reference
- Open Generation Details
- Switch Version

---

# 25. Timeline Generation Regions

Allow user to select a timeline range and invoke AI generation.

Example:

```text
[ 00:42.000 ────────────────── 00:48.000 ]
                ↓
        Generate Visual Scene
                ↓
        Director receives:
        - selected time range
        - lyric text
        - audio analysis
        - previous scene
        - next scene if present
        - project StoryBible
                ↓
          SceneSpec created
                ↓
             rendered
                ↓
       inserted into selection
```

This connects AI generation to actual editing.

---

# 26. Timeline Rendering / Visualization

The timeline must remain responsive on large projects.

Implement:

- horizontal virtualization
- vertical track virtualization
- waveform tile cache
- thumbnail tile cache
- background peak generation
- background thumbnail generation
- LOD rendering
- retained project model separate from view
- GPU-accelerated drawing where appropriate
- no media decoding on UI thread

Waveform cache should be persistent and invalidated by source hash.

Video thumbnails should be generated asynchronously.

---

# 27. Transport

Required:

- play
- stop
- record
- rewind
- fast-forward
- jump to start/end
- previous/next marker
- loop/cycle
- punch in/out
- preroll/postroll
- metronome
- scrub
- shuttle
- play selection
- locate selection start/end

Transport state must be shared by timeline, mixer, remote controls, and backend audio engine.

---

# 28. Audio Engine

The audio engine is real-time critical and must be isolated from UI/AI workloads.

## Required architectural rules

- dedicated real-time audio callback
- never block real-time thread
- never allocate unnecessarily in callback
- no AI inference on audio thread
- no file I/O in audio callback
- command/message queues between UI and audio engine
- plugin graph precomputed outside callback where possible

## Initial Windows backends

Priority:
1. ASIO
2. WASAPI Exclusive/Shared as fallback

Future:
- CoreAudio
- ALSA/PipeWire

---

# 29. Audio Routing Graph

Implement:

```text
Input
  ↓
Track Pre
  ↓
Input Filter / Gain
  ↓
Insert Chain
  ↓
Channel Processing
  ↓
Fader / Pan
  ├── Sends
  ↓
Bus / Group
  ↓
Master
  ↓
Monitor / Export
```

Track state:

- mute
- solo
- record enable
- input monitor
- automation read
- automation write
- phase
- gain
- pan
- routing
- inserts
- sends

---

# 30. Mixer

Build a synchronized mixer view.

Minimum channel strip:

- name
- color
- meter
- gain
- pan
- mute
- solo
- record
- monitor
- inserts
- sends
- automation read/write
- output routing
- channel fader

Mixer selection should synchronize with timeline track selection.

Support:

- mixer bank
- hidden/visible channels
- groups
- FX returns
- master bus

---

# 31. Plugin Architecture

The inspected Nuendo files show a heavily modular plugin architecture and VST3 usage.

EDMG should use a similarly modular **public-standard-based** approach.

## Initial plugin goal

**VST3 host support**.

Required:

- plugin scanner
- scanner subprocess
- blacklist/quarantine on crash
- metadata cache
- plugin category
- vendor
- version
- I/O layout
- latency
- editor capability
- preset/snapshot support where permitted by API
- plugin bypass
- plugin enable/disable

Do not let a crashing third-party plugin take down the primary app process.

---

# 32. Plugin Delay Compensation

Implement project-wide plugin latency compensation.

The graph engine should calculate:

- track insert latency
- bus latency
- route latency
- master latency

Playback alignment must remain sample coherent.

Recording monitoring must support low-latency bypass policies later.

---

# 33. Automation

Implement automation lanes for:

- volume
- pan
- mute
- sends
- plugin parameters
- selected AI/render parameters where useful

Automation modes initially:

- Read
- Write
- Touch

Later:
- Latch
- Trim

Automation data should use efficient point/curve storage.

Editing:
- draw
- select
- move
- scale
- thin
- copy/paste
- snap

---

# 34. Quick Controls

The inspected configuration demonstrates a useful concept: a small bank of assignable parameters mapped relative to the selected channel/track.

Create an EDMG **Quick Controls** system.

Each track can expose a configurable 8-control bank.

Possible mappings:

- volume
- pan
- low-cut
- high-cut
- send level
- plugin parameter
- AI motion amount
- AI camera amount
- generation strength
- prompt adherence

This becomes useful both in UI and hardware control surfaces.

---

# 35. Logical Edit / Project Action Engine

One of the strongest concepts worth adopting is a preset-driven logical editor.

Create an original EDMG subsystem named:

**Timeline Query & Action Engine**

It should allow:

```text
IF conditions
    ↓
match timeline/project objects
    ↓
THEN actions
```

## Example conditions

- track type
- track name contains
- event type
- selected
- muted
- hidden
- inside time range
- before cursor
- after cursor
- color/tag
- duration
- source type
- generated by AI
- provider
- scene rating
- marker type

## Example actions

- select
- mute/unmute
- show/hide
- rename
- color/tag
- move
- nudge
- delete
- enable record
- enable monitor
- route output
- quantize
- set time base
- execute render command
- run Director review
- regenerate selected AI clips

## Preset categories

- Automation
- Editing
- Mixing
- Naming
- Nudge
- Parts/Events
- Quantize
- Record/Monitor
- Selection
- Tempo/Signature
- Tracks
- Visibility
- AI Generation
- Continuity
- Render Jobs

This subsystem should operate through public project commands so it is fully undoable.

---

# 36. Command / Keybinding System

Provide an application-wide command registry.

Every action should have a stable command ID.

Example:

```text
timeline.split
timeline.nudge_left
transport.play
transport.stop
track.mute
track.solo
project.save
ai.generate_selection
ai.review_selection
mixer.toggle
```

Keybindings should be user-editable.

Support named keybinding profiles.

The inspected archives include compatibility-oriented key-command profiles for other DAWs. EDMG can provide **original** optional profiles that mimic familiar shortcut conventions where legally appropriate, without copying proprietary config files.

---

# 37. Undo / Redo Architecture

All project mutations should use commands or transactions.

Required:

- multi-step operation grouped as one undo
- AI insertion undo
- automation undo
- track routing undo
- plugin insert undo
- logical editor batch action undo
- project-level history safety

Avoid arbitrary UI components mutating project state directly.

---

# 38. MIDI and Control Surface Support

The inspected MIDI remote architecture exposes a strong separation between:

- physical surface
- MIDI bindings
- pages
- host objects
- host values
- transport
- mixer banks
- track selection
- plugin parameter banks
- quick controls

Build an original EDMG equivalent.

## Minimum MIDI Remote architecture

```text
ControlSurfaceDefinition
├── InputPort
├── OutputPort
├── Controls[]
│   ├── Button
│   ├── Knob
│   ├── Encoder
│   ├── Fader
│   ├── Pad
│   └── Pitch/Mod controls
├── Pages[]
└── Bindings[]
```

Host binding targets:

- transport
- track volume/pan
- mute/solo
- record/monitor
- mixer bank
- selected track
- plugin parameters
- sends
- quick controls
- AI generation controls

Start with MIDI CC/Note mappings.

Later:
- NRPN
- 14-bit
- feedback LEDs/displays
- scripting API

---

# 39. OSC / Remote API

Add an internal control API abstraction so OSC can be supported later without special-case timeline code.

Targets:

- transport
- selected track
- mixer
- markers
- render controls
- AI generation commands
- project navigation

EUCON should be considered only if licensing/SDK availability makes it appropriate.

Do not block core delivery on EUCON.

---

# 40. Media Pool / Asset Browser

Create a project media system.

Each imported/generated media asset gets:

- media ID
- original path
- project-relative reference
- media type
- duration
- sample rate
- channels
- frame rate
- resolution
- checksum
- proxy path
- waveform cache
- thumbnail cache
- tags
- source/provider
- usage references

Views:

- project media
- generated media
- references
- unused media
- favorites
- failed/missing media

Features:

- relink missing files
- reveal in explorer
- replace source
- duplicate
- remove unused
- consolidate project

---

# 41. Audio/Video Alignment

The inspected components show dedicated audio alignment/video infrastructure.

EDMG should support:

- waveform-based audio alignment
- sync by timecode
- sync by clap/transient
- sync by common audio
- align selected clips
- link synchronized audio/video

Later:
- speech alignment
- ADR replacement alignment

---

# 42. Markers, Cues, and Regions

Implement a robust marker system.

Marker types:

- position marker
- range marker
- scene marker
- lyric marker
- beat/section marker
- cue
- ADR marker
- render marker
- note/comment marker

Each marker can include:

- title
- notes
- color
- category
- time/range
- tags
- scene ID
- status

Markers should be visible on a marker track and navigable by transport.

---

# 43. Audio Analysis Tracks

Audio analysis already used by AI should be visible optionally.

Derived data:

- waveform
- beats
- tempo
- energy
- onsets
- section boundaries
- transcript words
- lyrics lines

These should not necessarily become ordinary editable media events.

They can be overlay lanes or analysis tracks.

The Director receives the same analysis data used by the timeline UI.

---

# 44. Tempo and Signature Maps

Support:

- constant tempo
- tempo events
- ramps
- time-signature changes
- musical grid

MIDI and musical automation can follow musical time.

Audio/video can remain in linear time unless explicitly configured.

---

# 45. MIDI Editing

Initial scope:

- MIDI import/export
- piano-roll editor
- note move/resize
- velocity
- quantize
- controller lanes
- program changes
- pitch bend
- sustain

Later:
- expression maps
- MPE
- drum editor
- advanced logical MIDI editor
- chord track

Do not delay core audio/video timeline work for deep MIDI composition features.

---

# 46. Video Track

Video must be first-class.

Features:

- frame thumbnails
- linked audio
- source timecode
- resize/crop metadata
- transform metadata
- opacity
- basic transitions
- proxy media
- frame stepping
- exact-frame cut
- clip speed
- freeze frame
- still extraction

Viewer:

- current frame
- safe areas optional
- timecode overlay
- playback resolution selector
- proxy/full-res toggle

---

# 47. AI Visual Track

This is distinct from an ordinary imported video track.

AI track events contain generation metadata and version history.

Possible visual state:

```text
[Scene 01 ✓] [Scene 02 rendering 62%] [Scene 03 queued] [Scene 04 needs review]
```

Timeline should display generation progress non-blockingly.

---

# 48. Render Queue

Do not bind AI generation directly to UI operations.

Create a persistent render queue.

States:

- pending
- preparing
- downloading_model
- loading_model
- generating
- postprocessing
- reviewing
- completed
- failed
- cancelled
- paused
- recoverable

Render jobs survive UI restarts where practical.

Job metadata:

- SceneSpec
- provider
- model
- hardware profile
- output target
- checkpoints
- logs
- progress
- failure reason

---

# 49. Model Lifecycle and VRAM Manager

Director and renderer models do not need to remain resident together.

Implement:

```text
Director needed
   ↓
load/stage Director
   ↓
plan/review
   ↓
release or offload
   ↓
renderer needed
   ↓
load renderer
   ↓
generate
```

The lifecycle manager should:

- estimate free VRAM
- unload inactive models
- CPU offload if supported
- sequence large models
- avoid loading duplicate checkpoints
- coordinate multi-GPU use
- expose memory status

---

# 50. Model Manager

Responsibilities:

- discover installed models
- validate required files
- verify version/hash
- download model package
- resume download
- calculate disk requirement
- uninstall
- move model storage
- detect existing installation
- choose correct variant

Never download every supported model automatically.

---

# 51. Hardware Profiler

Output a typed `HardwareProfile`.

Fields should include:

```text
OS
CPU
physical_core_count
logical_core_count
system_ram_gb
GPU[]
vendor
name
architecture
dedicated_vram
driver
CUDA_available
ROCm_available
DirectML_available_if_used
disk_space
audio_devices
recommended_tier
recommended_director
recommended_renderer
warnings[]
```

The profiler drives renderer recommendations, not hardcoded GPU names.

---

# 52. Workspaces

The inspected window-layout/preset structure reinforces the value of reusable workspaces.

Provide EDMG workspaces:

- AI Generation
- Edit
- Audio
- Mix
- Video
- ADR/Post
- Review
- Compact

Workspace remembers:

- panel visibility
- panel sizes
- dock positions
- active lower zone
- inspector width
- mixer visibility
- timeline zoom
- optional monitor placement

Electron and WinUI can implement workspace layouts differently while honoring shared workspace state where sensible.

---

# 53. Project Templates

Provide original project templates:

- Music Video
- Audio-to-Video
- Podcast Video
- Film/Post
- Dialogue/ADR
- Stereo Music Mix
- Surround Post
- Blank Project

Template stores:

- track layout
- routing
- buses
- marker tracks
- AI tracks
- default render mode
- project frame rate
- sample rate

---

# 54. ADR / Dialogue Workflow

The observed ADR-oriented components suggest valuable post-production capabilities.

Later professional phase:

- cue list
- dialogue regions
- take recording
- character/actor metadata
- pre-roll/post-roll
- beeps/count-in
- take rating
- comp selected take
- text/script panel
- waveform alignment
- replace production dialogue

This should use the same timeline and marker system.

---

# 55. Reconform

For film/post workflows, add reconform later.

Purpose:

If picture edit changes:

```text
old edit
   ↓
change list / new reference
   ↓
EDMG compares timeline
   ↓
moves/cuts associated audio/events
```

Implement only after stable project/timecode foundations.

Possible interchange sources:

- EDL
- XML formats where specifications are available
- AAF through appropriate libraries
- DAWproject where applicable

---

# 56. Import / Export Architecture

Observed component separation strongly suggests a plugin-like interchange architecture.

Create:

```text
IMediaImporter
IMediaExporter
IProjectImporter
IProjectExporter
```

Initial:

- WAV
- FLAC
- MP3
- common video through FFmpeg
- MIDI
- JSON EDMG project
- stems
- final video

Later:
- AAF
- EDL
- DAWproject
- ADM BWF
- MusicXML if scoring added

Keep format logic out of timeline model.

---

# 57. FFmpeg Layer

Use FFmpeg as media infrastructure where appropriate.

Responsibilities:

- decode
- encode
- transcode
- proxy generation
- waveform source conversion when necessary
- thumbnail extraction
- final mux
- audio/video stream inspection

Wrap FFmpeg behind an EDMG service.

Do not scatter command-line invocation throughout UI code.

---

# 58. Post-Processing Pipeline

Shared across renderers.

Stages may include:

1. generated source ingest
2. temporal cleanup
3. upscale
4. restoration
5. frame interpolation
6. frame-rate conversion
7. color transform
8. audio merge
9. timeline composite
10. final encode

Every stage should expose:

- input
- output
- status
- progress
- logs
- cancellation
- cache identity

---

# 59. 60 FPS Strategy

Do not make diffusion models generate 60 unique diffusion frames per second unless a model specifically makes that efficient.

Preferred:

```text
native generated FPS
      ↓
temporal interpolation
      ↓
output FPS
```

This allows low-tier hardware to retain motion while reducing diffusion cost.

---

# 60. Mixer / Timeline / AI Integration

AI should understand selected track context.

Examples:

- Director knows selected audio segment
- regenerate scene from selected time range
- auto-duck music beneath dialogue
- analyze selected clip
- align generated video to beats
- create markers from generated scenes
- create automation based on song dynamics
- prompt may reference selected timeline objects

All such operations use explicit project commands and must be undoable.

---

# 61. Track Inspector

Each selected track should have an Inspector.

Audio:
- routing
- gain
- inserts
- sends
- automation
- delay
- metadata

Video:
- transform
- opacity
- crop
- proxy
- frame rate
- metadata

AI:
- Director mode
- renderer mode
- continuity
- motion
- references
- version
- provider

MIDI:
- input
- channel
- transform
- instrument

---

# 62. Lower Zone / Editors

A lower editor zone can host:

- audio waveform editor
- MIDI piano roll
- automation editor
- AI SceneSpec editor
- clip versions
- render log
- mixer
- media browser

Do not open a separate full window for every edit operation.

---

# 63. Command Palette

Add searchable commands.

Example:

```text
> split
> generate selected range
> normalize
> review continuity
> show mixer
> add marker
> bounce selected tracks
```

This complements keybindings and logical editing.

---

# 64. Project Persistence

Create a versioned EDMG project format.

Recommended direction:

```text
Project.edmgproj
or
ProjectFolder/
```

Store metadata separately from large media.

Project data must include:

- tracks
- events
- routing
- automation
- markers
- StoryBible
- SceneSpecs
- AI generation metadata
- installed model references
- provider configuration references
- render queue metadata
- workspace state
- project settings

Never embed API secrets directly in project files.

---

# 65. Autosave and Recovery

Implement:

- timed autosave
- operation-count autosave
- crash recovery
- render-job recovery
- last-known-good project snapshot
- project backup rotation

AI generation jobs can be expensive; recovery is important.

---

# 66. Performance Isolation

Separate subsystems:

```text
UI Process
Project/Core
Audio Engine
Media Worker
Plugin Scanner
AI Backend
Render Worker
Thumbnail/Waveform Workers
```

A long AI render must not block:

- playback
- scrolling
- editing
- mixer meters
- UI responsiveness

---

# 67. Electron and WinUI Strategy

Both frontends should consume the same backend contracts.

Do not implement separate business logic.

Shared concepts:

- project model
- render queue
- provider contracts
- SceneSpec
- StoryBible
- hardware profile
- media service
- timeline commands
- transport state
- model manager

Frontend-specific:
- visual components
- window chrome
- native integrations
- docking implementation

---

# 68. Suggested Core Contracts

```text
IProjectService
ITimelineService
ITransportService
IAudioEngine
IMixerService
IPluginHost
IMediaService
IRenderQueue
IRenderer
IGenerationProvider
IDirector
IModelManager
IHardwareProfiler
IPromptCompiler
IAutomationService
ICommandService
IUndoService
IRemoteControlService
```

Keep interfaces narrow and testable.

---

# 69. Suggested Domain Objects

```text
Project
ProjectSettings
Track
TrackLane
TimelineEvent
AudioClip
VideoClip
AIClip
MidiPart
Marker
AutomationLane
AutomationPoint
RoutingNode
MixerChannel
PluginInstance
Send
Bus
StoryBible
SceneSpec
PromptPackage
ReviewReport
RenderJob
MediaAsset
HardwareProfile
ModelInstallation
ProviderDefinition
Workspace
KeyCommandProfile
LogicalActionPreset
```

---

# 70. Error Handling

Every major backend service should return structured errors.

Example categories:

- model_missing
- model_version_mismatch
- insufficient_vram
- insufficient_ram
- insufficient_disk
- provider_auth_failed
- provider_rate_limited
- render_crashed
- plugin_crashed
- media_missing
- codec_unsupported
- timeline_invalid
- audio_device_unavailable

UI should convert these into actionable guidance.

---

# 71. Logging

Use structured logs with:

- timestamp
- project
- job
- provider
- renderer
- model
- GPU
- stage
- event
- duration
- exception

Render logs should be exportable for diagnostics.

---

# 72. Testing Strategy

## Unit Tests

- timeline time conversion
- SMPTE/drop-frame
- musical-time conversion
- snap
- trim/split logic
- undo/redo
- routing graph
- plugin latency calculations
- automation interpolation
- SceneSpec schema
- StoryBible revisions
- renderer selection
- hardware tiers
- provider normalization
- prompt compilation
- logical query/actions

## Integration Tests

- import audio → timeline → playback
- import video → frame-accurate playback
- VST3 scan
- insert plugin
- automation playback
- AI range generation
- Hunyuan generation
- LTX generation
- external provider generation
- model fallback
- Director review
- save/reload project
- render queue restart recovery

---

# 73. Minimum Hardware QA Matrix

Test at least:

### Low
- 6 GB NVIDIA GPU
- 16 GB RAM

### Mainstream
- 8 GB GPU
- 16/32 GB RAM

### Mid
- 12–16 GB GPU
- 32 GB RAM

### High
- 24 GB GPU
- 32/64 GB RAM

### Ultra
- 48 GB GPU
- dual 48 GB GPU

Also verify CPU-only Director operation where intended.

AMD support should be capability-gated rather than assumed.

---

# 74. DAW Acceptance Criteria

The DAW foundation is acceptable when:

1. Audio/video tracks can be created and reordered.
2. Clips can be moved, split, trimmed, duplicated, and deleted.
3. Editing is non-destructive.
4. Undo/redo is reliable.
5. Timeline scrolling remains responsive on large projects.
6. Waveforms/thumbnails are cached asynchronously.
7. Playback cursor remains synchronized.
8. Audio engine does not glitch under normal UI load.
9. Mixer reflects track state.
10. Mute/solo/record/monitor work.
11. Inserts/sends routing model exists.
12. VST3 scanning is isolated from main process.
13. Basic automation works.
14. Markers/ranges work.
15. AI-generated clips live as timeline events.
16. AI clip versions are preserved.
17. Timeline generation can operate on a selected range.
18. Project save/reload preserves all timeline state.

---

# 75. AI Acceptance Criteria

1. Qwen3-VL-8B works as standard Director.
2. Qwen3-VL-30B-A3B can be selected on qualifying hardware.
3. SceneSpec is authoritative structured data.
4. StoryBible persists across project scenes.
5. Hunyuan works on low-tier profile.
6. Low tier still generates real motion.
7. LTX works as high-quality renderer.
8. Renderer selection is hardware aware.
9. Only necessary models are downloaded.
10. External providers remain functional.
11. Generated clips contain provenance metadata.
12. Director can inspect/review output where enabled.

---

# 76. External Provider Acceptance Criteria

1. Existing providers remain available.
2. Provider calls are routed through normalized adapter interfaces.
3. Provider credentials remain in secure settings, not project data.
4. External outputs become ordinary EDMG media/AI clips.
5. API job status maps into render queue states.
6. Costs can be recorded when provider exposes them.
7. Cloud failure does not break local rendering.

---

# 77. Implementation Phases

## Phase 0 — Audit and Safety

Before modifying architecture:

- inventory current renderer paths
- inventory current provider integrations
- inventory timeline implementation
- inventory current media model
- inventory audio backend
- identify existing stable functions
- write regression tests around working behavior
- create migration branch

Do not rewrite blindly.

---

## Phase 1 — Shared Core Contracts

Implement:

- Project
- Track
- TimelineEvent
- MediaAsset
- time model
- command/undo system
- hardware profile
- provider contracts
- renderer contracts
- Director contracts
- SceneSpec
- StoryBible

No major UI rewrite yet.

---

## Phase 2 — Timeline Core

Implement:

- timeline store
- track list
- events
- selection
- split
- trim
- move
- snap
- zoom
- scroll
- markers
- command history
- persistence

Focus entirely on correctness.

---

## Phase 3 — Media Engine

Implement:

- media import
- metadata probe
- waveform cache
- thumbnail cache
- proxy service
- relink
- project media pool

---

## Phase 4 — Transport and Audio Engine

Implement/stabilize:

- playback
- seek
- loop
- audio device
- audio tracks
- routing
- meters
- real-time thread isolation

---

## Phase 5 — Mixer / VST3

Implement:

- mixer service
- channel strips
- insert graph
- sends
- buses
- plugin scanner subprocess
- VST3 host
- plugin crash quarantine
- PDC

---

## Phase 6 — Automation and Advanced Editing

Implement:

- automation lanes
- read/write/touch
- fades/crossfades
- lanes
- comping/version selection
- time stretch
- nudge
- ripple edit
- logical action engine

---

## Phase 7 — Director

Implement:

- Qwen3-VL-8B
- StoryBible
- SceneSpec planning
- prompt compilers
- Director timeline awareness

---

## Phase 8 — Hunyuan Renderer

Implement:

- standard internal renderer
- low-VRAM mode
- T2V
- I2V
- chunking
- render queue integration
- timeline insertion

---

## Phase 9 — LTX Renderer

Implement:

- high-tier path
- hardware qualification
- model manager integration
- optional installation
- prompt compiler
- timeline insertion

---

## Phase 10 — Director Review

Implement:

- generated frame sampling
- optional clip understanding
- ReviewReport
- continuity scoring
- next-scene correction
- bounded retry behavior

---

## Phase 11 — Provider Refactor

Wrap current API providers into:

- provider definitions
- capability model
- normalized requests
- normalized output
- render queue

Preserve behavior before expanding provider set.

---

## Phase 12 — Remote Control / Quick Controls

Implement:

- command registry
- keybindings
- MIDI mapping
- 8 Quick Controls
- transport bindings
- mixer bindings

---

## Phase 13 — Professional Post Features

Implement incrementally:

- alignment
- ADR
- reconform
- interchange formats
- surround
- object audio where justified

---

# 78. Codex Work Rules

Codex must:

1. Inspect existing implementation before replacing it.
2. Preserve working features unless explicitly deprecated.
3. Add tests before or alongside major refactors.
4. Keep timeline/project logic out of UI components.
5. Keep AI renderer logic out of timeline UI.
6. Keep API providers behind interfaces.
7. Keep audio real-time code isolated.
8. Avoid global mutable state where possible.
9. Maintain backward compatibility for existing projects where feasible.
10. Add migrations for project schema changes.
11. Never auto-delete legacy renderer code until replacement passes acceptance tests.
12. Never copy proprietary code/assets from the Nuendo archives.

---

# 79. Recommended Source Organization

Adapt to existing languages/frameworks, but preserve boundaries.

```text
/core
  /project
  /timeline
  /time
  /commands
  /undo
  /contracts

/audio
  /engine
  /routing
  /mixer
  /automation

/media
  /import
  /cache
  /proxy
  /pool

/plugins
  /scanner
  /vst3
  /registry

/director
  /qwen
  /story_bible
  /scene_planner
  /review
  /prompt_compilers

/render
  /queue
  /internal
    /hunyuan
    /ltx
  /external

/models
  /manager
  /downloads
  /hardware

/remote
  /commands
  /midi
  /quick_controls
  /osc

/post
  /alignment
  /reconform
  /adr
  /export

/ui
  /timeline
  /inspector
  /mixer
  /media
  /director
  /render_queue
```

---

# 80. Recommended User Experience

The ordinary user should experience this:

```text
1. Create/open project
2. Drop audio onto timeline
3. EDMG analyzes audio
4. Lyrics/transcript appear
5. Director proposes scenes
6. Scene events appear on AI track
7. User clicks Generate
8. EDMG chooses hardware-appropriate renderer
9. Clips render into timeline
10. User edits like a DAW/video editor
11. Director reviews continuity if enabled
12. User mixes audio
13. User exports final video
```

The model/provider complexity stays mostly invisible.

---

# 81. Final Product Shape

## Low Hardware Install

- Qwen3-VL-8B
- HunyuanVideo-1.5
- Whisper model
- EDMG DAW/audio/video engine

## High Hardware Install

- Qwen3-VL-30B-A3B or Qwen3-VL-8B
- LTX-2.5
- Whisper
- EDMG DAW/audio/video engine

Optional:
- Hunyuan as fast preview engine
- external API providers
- additional models later

---

# 82. Final Architecture Summary

```text
                         EDMG STUDIO
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
   PROFESSIONAL DAW      AI DIRECTOR          MEDIA / ASSETS
      TIMELINE           Qwen3-VL                  │
         │                    │                    │
         └─────────────┬──────┴─────────────┬──────┘
                       │                    │
                       ▼                    ▼
                   SceneSpec            StoryBible
                       │
                       ▼
                Renderer Manager
                       │
            ┌──────────┼──────────┐
            ▼          ▼          ▼
        Hunyuan      LTX-2.5    API Providers
            │          │          │
            └──────────┼──────────┘
                       ▼
                Generated Clips
                       │
                       ▼
                    TIMELINE
                       │
       ┌───────────────┼────────────────┐
       ▼               ▼                ▼
     Mixer         Automation        Video Edit
       │               │                │
       └───────────────┼────────────────┘
                       ▼
             Post / Interpolation / Export
```

---

# 83. Bottom-Line Codex Directive

Rebuild EDMG around **one unified project/timeline core**.

The DAW timeline must become the authoritative place where audio, video, AI scenes, automation, markers, MIDI, and generated versions coexist.

Use professional DAW architectural patterns:
- track/event model
- non-destructive editing
- command/undo system
- mixer/routing graph
- VST3 host
- automation
- media pool
- logical/query editing
- quick controls
- MIDI remote mapping
- project templates/workspaces
- post-production-friendly timecode and markers

Integrate the AI system directly into that architecture:
- Qwen3-VL Director
- StoryBible
- SceneSpec
- Hunyuan low-tier renderer
- LTX high-tier renderer
- hardware-aware routing
- selective model downloads
- render queue
- continuity review
- external providers retained behind adapters

**Do not create a DAW module beside the AI studio. The DAW/timeline and AI generation system must share one project model and operate as one application.**
