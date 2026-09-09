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

## Modern UX References

Current product references point to a clearer direction for Vokal UI:

- [Moises](https://moises-ai.com/): make stems, chords, key/BPM, pitch and mix controls visible as the core workspace, not hidden settings.
- [Vocal Remover](https://vocalremover.org/ru/): keep the first screen focused on one job and one upload action, with other tools separated into navigation.
- [Splice Create](https://splice.com/tools/mobile): offer a fast demo/start path and make export feel immediate.
- [MuseScore Studio UI](https://handbook.musescore.org/navigation/the-user-interface): keep notation/score central with surrounding panels for tools, palettes and status.
- [Ableton Note](https://www.ableton.com/en/note/), [Soundtrap Studio](https://blog.soundtrap.com/?p=1457) and [BandLab Studio](https://blog.bandlab.com/studio-faq/): use transport, timeline and musical sections as the orientation layer.
- [Udio interface](https://help.udio.com/en/articles/10716509-explore-the-udio-interface): put prompt/create on Home, detailed controls in Create, library/results in a separate area, and a player visible around the workflow.
- [Suno Studio](https://about.suno.com/release-notes/introducing-suno-studio): treat the result as a generative audio workspace with timeline, stems, BPM/pitch controls and export.
- [ElevenLabs Studio](https://elevenlabs.io/studio): present AI as a co-editor, keep timeline/editing central, and make the free/paid boundary explicit through credits and export.

Implication:

Vokal should open as a working music console: choose scenario, open a ready demo or upload a song, then see materials, playback context, song form, confidence and AI-director actions in one workspace.

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
