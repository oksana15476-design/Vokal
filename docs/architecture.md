# Architecture

## Shape

The product is an orchestration layer over specialized music AI services and local processing workers.

V1 should avoid training custom models. The defensible product layer is the workflow, the internal song representation, and the adaptation logic.

## Components

### Web App

- upload flow;
- lineup setup;
- job status;
- Stage Pack viewer;
- notation preview;
- AI Director chat;
- downloads.

Suggested stack:

- Next.js;
- TypeScript;
- Tailwind or a restrained component system;
- OpenSheetMusicDisplay for MusicXML rendering.

### API

- auth;
- projects;
- uploads;
- processing jobs;
- artifacts;
- chat commands;
- billing events.

Suggested stack:

- FastAPI or NestJS;
- Postgres;
- Redis queue;
- S3-compatible object storage.

### Audio Worker

Responsibilities:

- normalize audio with ffmpeg;
- run/source stem separation;
- create minus tracks;
- create residual practice tracks;
- generate click tracks;
- render audio previews.

### Transcription Worker

Responsibilities:

- convert stems into MIDI;
- convert MIDI into MusicXML drafts;
- request external transcription APIs when needed;
- estimate confidence;
- flag suspicious sections.

### Notation Worker

Responsibilities:

- render MusicXML to PDF;
- export per-part PDFs;
- export MIDI;
- generate chord charts;
- generate lyrics + chords sheets.

Possible tools:

- MuseScore CLI for PDF/MIDI/MusicXML conversion;
- music21 for analysis and conversion;
- OpenSheetMusicDisplay for browser previews.

### AI Director

Responsibilities:

- read SongGraph;
- explain song structure;
- detect mismatches between original arrangement and lineup;
- propose adaptation plans;
- apply supported transformations;
- keep audio, MIDI, score, and rehearsal artifacts in sync.

## External Services

### Stems

Prototype:

- Demucs.

Paid quality path:

- AudioShake API.

AudioShake currently exposes source-separation models for vocals, lead/backing vocals, instrumental, drums, bass, guitar, piano, keys, strings, wind, and other. It also supports residual outputs for practice tracks.

### Transcription

Prototype:

- Spotify Basic Pitch for single stems;
- MT3-family models for multi-instrument experiments.

Paid quality path:

- Klangio API for MIDI, MusicXML, PDF, beat tracking, and chord recognition.

### LLM

Use LLMs for planning and structured edits, not raw audio inference.

Good first uses:

- arrangement analysis;
- transformation planning;
- user-facing explanations;
- conversion from chat command to deterministic operation;
- score adaptation rules.

## Processing Pipeline

1. Store original upload.
2. Normalize audio.
3. Extract metadata.
4. Separate stems.
5. Detect tempo, meter, key, beats, and sections.
6. Detect chords.
7. Transcribe important stems.
8. Build initial SongGraph.
9. Generate Stage Pack.
10. Run adaptation analysis against lineup.
11. Show confidence and review warnings.

## Key Technical Risk

Automatic transcription from a dense mix is imperfect.

Mitigation:

- transcribe separated stems, not the full mix;
- show confidence;
- make results editable;
- scope first genres and lineups tightly;
- treat output as rehearsal material, not legally/publicly authoritative sheet music.
