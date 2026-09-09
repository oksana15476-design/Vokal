# SongGraph

SongGraph is the internal representation that prevents the product from becoming a thin wrapper around stem separation and transcription APIs.

The core idea:

> Audio, stems, MIDI, score, sections, chords, and instruments must point to the same musical timeline.

## Minimal Schema

```json
{
  "song": {
    "id": "song_123",
    "title": "Untitled",
    "durationSec": 214.3,
    "bpm": 126,
    "meter": "4/4",
    "key": "F#m"
  },
  "sections": [
    {
      "id": "sec_intro",
      "label": "Intro",
      "startSec": 0,
      "endSec": 12.4,
      "startBar": 1,
      "endBar": 4
    }
  ],
  "chords": [
    {
      "sectionId": "sec_intro",
      "bar": 1,
      "beat": 1,
      "symbol": "F#m"
    }
  ],
  "parts": [
    {
      "id": "part_bass",
      "instrument": "bass",
      "sourceStemId": "stem_bass",
      "midiArtifactId": "artifact_bass_mid",
      "musicXmlArtifactId": "artifact_bass_xml",
      "confidence": 0.91
    }
  ],
  "notes": [
    {
      "partId": "part_bass",
      "pitch": "F#2",
      "startBar": 1,
      "startBeat": 1,
      "durationBeats": 1,
      "velocity": 82,
      "confidence": 0.93
    }
  ],
  "artifacts": [
    {
      "id": "artifact_bass_pdf",
      "type": "pdf",
      "partId": "part_bass",
      "path": "s3://bucket/song_123/bass.pdf"
    }
  ]
}
```

## Why It Matters

Without SongGraph, a command like:

> Remove guitar in verse 2.

is just audio editing.

With SongGraph, the system knows:

- which section is verse 2;
- which tracks are guitar;
- which notes belong to that section;
- which audio stem, MIDI file, and PDF page must change;
- which rehearsal tracks must be regenerated.

## Supported Transformations in V1

- transpose all pitched parts;
- transpose only vocal part;
- mute/remove one instrument in one section;
- generate residual rehearsal track;
- simplify part by note density;
- merge two related parts into one playable part;
- move strings/pads/brass to keys;
- export per-part artifacts again.

## Confidence

Confidence should exist at several levels:

- whole song;
- part;
- section;
- bar;
- note or event.

The product should visually emphasize low-confidence regions. This is essential for musician trust.
