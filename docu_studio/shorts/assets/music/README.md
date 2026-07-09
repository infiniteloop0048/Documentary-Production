# Shorts Music Bed

Drop royalty-free background tracks (mp3/wav) into this folder and add a
matching entry to `manifest.json`:

```json
{ "filename": "your-track.mp3", "mood": "uplifting", "bpm": 120 }
```

`bpm` is used by a future beat-sync feature — set it accurately even if
nothing consumes it yet.

**Do not commit copyrighted audio here.** Good sources for royalty-free
tracks: YouTube Audio Library, Pixabay Music, Free Music Archive — check
each track's license terms before use.

If `manifest.json` has no entries whose `filename` exists on disk, Shorts
runs skip the music bed automatically. No crash, no error — it's just quieter.
