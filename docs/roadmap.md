# Roadmap

## Phase 0: Validation Prototype

Goal: prove the workflow with one real song and one lineup.

Build:

- upload mock;
- lineup setup;
- fake processing state;
- Stage Pack result page;
- AI Director recommendation panel;
- notation preview using sample MusicXML;
- chat command mock.

Success:

- musicians understand the promise in under 30 seconds;
- they can name a song they would use it on;
- they can name what they would pay for.

## Phase 1: Thin Technical MVP

Goal: produce a real Stage Pack draft from one uploaded song.

Build:

- audio upload;
- storage;
- background job queue;
- Demucs or AudioShake stems;
- basic BPM/key/chord/section analysis;
- Basic Pitch or Klangio transcription;
- MusicXML/PDF rendering;
- downloadable ZIP;
- confidence labels.

Success:

- 3-5 musicians can rehearse from the output after quick manual review;
- the system handles 10 test songs end to end;
- processing failures are visible and recoverable.

## Phase 2: Arrangement Adaptation

Goal: adapt original arrangement to a selected lineup.

Build:

- one-guitar adaptation;
- strings-to-keys adaptation;
- vocal range transposition;
- beginner/intermediate/advanced simplification;
- regeneration of affected PDFs/MIDI/rehearsal tracks.

Success:

- users prefer adapted output to raw transcription;
- users are willing to pay more for adaptation than for stems/notes alone.

## Phase 3: AI Arrangement Copilot

Goal: let users change the arrangement through natural language.

Build:

- supported command parser;
- deterministic edit operations;
- diff cards;
- undo;
- version history;
- audio preview rendering.

Example commands:

- "Make the chorus bigger."
- "Simplify the bass."
- "Give keys the string line."
- "Shorten the intro."
- "Create a concert ending."

## Phase 4: Team Product

Goal: make the product sticky for bands and schools.

Build:

- saved bands;
- musician profiles;
- school accounts;
- song library;
- teacher/student versions;
- reusable arrangement presets;
- billing and usage limits.
