# Prompt for an AI to log raw video

Paste it together with the `.ai-log.mp4` file(s) produced by Video Processor. If the video came
out in several parts (`.part01`, `.part02`…), upload them all in the same message, in order.

(The CSV column names stay in Spanish on purpose so they match the `log_raw.csv` template.)

---

I'm giving you raw gameplay (no mic, no audio) reduced to 360p and 2 fps. I need a **log of usable
segments** to use later as b-roll.

**How to read time.** There is a clock in the top-left corner (`hh:mm:ss.mmm`). It is the time of
the ORIGINAL video, even if the file is only one part of it. Always use that clock, never the
player's time. If at some point it can't be read, say so in `notas` instead of guessing.

**What I want.** One row per usable segment between 3 and 30 seconds long. Don't describe the whole
video: only what would work as b-roll (action, scenery, builds, useful menus). If a moment is
especially good, start `notas` with ⭐.

**Format.** Only a CSV, with this exact header and no text around it:

```
archivo,entrada,salida,que_se_ve,tipo,calidad,uso_sugerido,notas
```

- `archivo`: the file id, i.e. whatever comes before the first dot in the name
  (`cards_0007.ai-log.part02.mp4` → `cards_0007`).
- `entrada` and `salida`: `hh:mm:ss` from the on-screen clock.
- `que_se_ve`: one concrete sentence about what is visible. Don't invent anything you can't make out.
- `tipo`: one of `accion`, `paisaje`, `construccion`, `menu`, `cinematica`, `otro`.
- `calidad`: `A` usable as is, `B` needs touching up, `C` discard (leave out the C rows unless they
  work as a warning).
- `uso_sugerido`: free and short (e.g. "danger b-roll", "transition").
- `notas`: glitches, hard cuts, spoilers, things that shouldn't be shown, and any doubt.

If you're not sure about something, write "no estoy seguro" in `notas`.
