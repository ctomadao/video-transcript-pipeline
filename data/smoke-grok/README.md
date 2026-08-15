# Grok upload pack — timestamped video transcripts

Upload `INDEX.md`, this README, and every file under `transcripts/`.
These files let Atlas Brasileiro answer: *em qual vídeo e em que minuto isso foi dito?*

## How to use with the monthly books

The project already has the monthly books. These transcripts are the video layer.
When the user quotes or paraphrases a book passage:

1. Search the transcript files for the closest wording (ASR may differ from the book).
2. Answer with **video title**, **`[HH:MM:SS]`**, the **YouTube URL with `&t=`**, and a short quoted line.
3. If several hits exist, list them. Do not invent timestamps.
4. If the book wording is not in any transcript, say so and give the best near-match.

## Line format

```
[youtubeId @ HH:MM:SS] spoken text
```

Watch URL: `https://www.youtube.com/watch?v={youtubeId}&t={seconds}s`
where `seconds = HH*3600 + MM*60 + SS`.
Example: `[00:01:05]` → `&t=65s`.

JSON sidecars are **not** included (local-only; too large for the project).

Transcript files in this pack: 3

