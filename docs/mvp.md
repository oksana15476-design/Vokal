# MVP Spec

## Product

AI Music Director prepares a finished song for live performance by a specific band.

The first release should feel like a finished service, not a technical utility. The user should not think in terms of stems, transcription models, or MusicXML. They should think:

> I uploaded a song and got rehearsal-ready materials.

## Core Flow

1. User uploads `mp3`, `wav`, `flac`, or `m4a`.
2. User selects the lineup.
3. System analyzes the song.
4. System builds a Stage Pack.
5. System highlights arrangement problems.
6. User asks for changes through AI Director chat.

## Default Lineup

V1 should optimize for the most common cover-band setup:

- lead vocal;
- guitar;
- bass;
- keys;
- drums.

Optional fields:

- vocal range;
- guitar count;
- bass string count;
- musician level;
- whether backing vocals are available;
- whether keys can cover strings/synths.

## Required Analysis

For each uploaded song, V1 should produce:

- BPM;
- key;
- meter;
- song sections;
- chord timeline;
- vocal stem;
- drums stem;
- bass stem;
- guitar stem;
- keys/piano stem where available;
- other stem;
- MIDI drafts for primary parts;
- MusicXML drafts for primary parts;
- confidence by part and section.

## Required Stage Pack

V1 paid output:

- `Full Score.pdf`
- `Chords.pdf`
- `Lyrics + Chords.pdf`
- `Vocal.pdf`
- `Guitar.pdf`
- `Guitar TAB.pdf`
- `Bass.pdf`
- `Keys.pdf`
- `Drums.pdf`
- `Full MIDI.mid`
- per-part MIDI files;
- separated stems;
- minus track;
- click track;
- rehearsal tracks without each main instrument.

## AI Director Suggestions

After processing, the product should surface adaptation issues:

- original contains two guitar layers, but the band has one guitarist;
- original uses strings/brass, but the band has only keys;
- vocal range is too high or too low;
- bass part does not fit selected instrument range;
- drums are too complex for selected level;
- chorus is likely weak with the selected lineup.

Each issue should have one-click actions:

- combine guitar parts;
- move strings to keys;
- transpose song;
- simplify part;
- create easy version;
- create concert ending;
- strengthen chorus.

## Chat Commands for V1

Support a narrow command set first:

- "Transpose down 2 semitones."
- "Make guitar playable by one guitarist."
- "Move strings to keys."
- "Simplify drums."
- "Create beginner bass part."
- "Make chorus bigger."
- "Remove vocals but keep backing vocals."
- "Generate rehearsal track without bass."

## Non-Goals

V1 should not include:

- full DAW editing;
- AI song generation from scratch;
- public song catalog;
- social features;
- marketplace of arrangements;
- perfect automatic notation claims;
- manual waveform editing;
- advanced mixing/mastering.

## Quality Principle

The output is an editable draft, not a magic perfect transcription.

The interface must show:

- confidence per part;
- suspicious bars;
- what was adapted;
- what needs musician review.
