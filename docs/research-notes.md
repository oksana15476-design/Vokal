# Research Notes

These notes capture the current market and technical direction as of 2026-09-09.

## Strategic Thesis

The crowded market is individual utilities:

- remove vocal;
- split stems;
- detect BPM/key;
- detect chords;
- convert audio to MIDI;
- generate a song from text;
- master a track.

The less crowded opportunity is the full workflow:

> finished song -> selected lineup -> playable arrangement -> rehearsal pack -> iterative adaptation.

## Competitor Pressure

High-pressure areas:

- vocal removal;
- stem separation;
- BPM/key detection;
- mastering;
- generic AI song generation;
- audio-to-MIDI;
- audio-to-notes.

More attractive areas:

- adapting a song for a specific live lineup;
- generating complete rehearsal packs;
- moving parts between instruments;
- simplifying by musician level;
- keeping audio, MIDI, and notation synchronized after AI edits.

## Russia

The Russian market appears especially interesting because several utility products exist, but the full "song to band-ready performance" workflow is less visible.

Known local/nearby references:

- ПеснеГен: broad AI music tools, generation, stems, mastering, notes/MIDI, chords, analysis.
- ДелиГолос: vocal/instrumental separation, stems, MIDI, recognized notes, Android app.
- Audio2Midi: track/link/idea to score and MIDI.
- NotationAI: AI notation/editor workflow with MIDI/MusicXML/PDF.
- PARTITA STUDIO: AI composition and MIDI arrangement via agent-driven desktop app.

Implication:

Do not compete as "another AI music toolkit". Compete as "AI musical director for live performance preparation".

## First Market

Best first users:

- cover bands;
- musical directors;
- arrangers;
- music schools;
- teachers.

Avoid starting with broad consumer B2C. The urgent paid problem belongs to people who regularly need to prepare songs for performance.

## Pricing Hypothesis

Per-song:

- 790 RUB: basic analysis;
- 1490 RUB: Stage Pack;
- 2990-4990 RUB: adapted arrangement.

Subscription:

- 2990-5990 RUB/month for bands;
- 10000-30000 RUB/month for schools or studios.

## Technical Sources To Recheck

- AudioShake developer docs for separation models, credits, residual outputs, and webhooks.
- Klangio API docs for transcription, MusicXML, MIDI, PDF, chord recognition, and beat tracking.
- OpenSheetMusicDisplay for MusicXML preview.
- MuseScore CLI for PDF and MIDI exports.
- Spotify Basic Pitch for fallback audio-to-MIDI.
- Demucs for open-source stem separation.

## Open Questions

- Which genre should V1 optimize for first: pop, rock, worship, wedding cover bands, music school repertoire?
- Should we start with Russia-only payments and Russian UX, or bilingual from day one?
- Can we legally process user-uploaded copyrighted songs if outputs are private rehearsal materials?
- What accuracy level is acceptable for paid rehearsal use?
- Do users want automatic output first, or a guided "review suspicious bars" flow?
