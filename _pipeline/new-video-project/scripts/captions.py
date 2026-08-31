"""Reshape word timestamps into the two transcripts an editor actually uses.

Whisper's own segmentation is arbitrary: it produced cues up to 142 characters
and 13.6 seconds on a 13-minute demo, which overflow on screen. Everything here
re-cuts from word timestamps instead, so both outputs stay in sync with audio.

  reading transcript  — timecoded paragraphs, for finding sections
  caption transcripts — short cues, for burning on screen
"""
import re

# A line longer than this is hard to read on screen; two lines is the ceiling.
MAX_CHARS_PER_LINE = 42
MAX_LINES = 2
MAX_CUE_SECONDS = 6.0
# A pause this long is a natural place to break a cue.
BREAK_PAUSE = 0.6
# Below this, two cues in a row look like a flicker; hold the earlier one.
MIN_CUE_SECONDS = 0.7

SENTENCE_END = re.compile(r"[.!?]$")
CLAUSE_END = re.compile(r"[,;:]$")


def fmt_srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def fmt_timecode(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h:02}:{m:02}:{s:02}"


# A cue is capped here so it always wraps into at most MAX_LINES readable lines.
MAX_CUE_CHARS = MAX_CHARS_PER_LINE * MAX_LINES


def _wrap(text: str) -> str:
    """Balance a cue across two lines of roughly equal length."""
    words = text.split()
    if len(text) <= MAX_CHARS_PER_LINE:
        return text
    # Split near the middle, at the word boundary that best balances the lines.
    best, split = 10**9, len(words) // 2
    for i in range(1, len(words)):
        top = len(" ".join(words[:i]))
        bot = len(" ".join(words[i:]))
        if max(top, bot) <= MAX_CHARS_PER_LINE and abs(top - bot) < best:
            best, split = abs(top - bot), i
    return " ".join(words[:split]) + "\n" + " ".join(words[split:])


def _srt(cues: list) -> str:
    out = []
    for i, c in enumerate(cues, 1):
        out += [str(i),
                f"{fmt_srt_time(c['start'])} --> {fmt_srt_time(c['end'])}",
                c["text"], ""]
    return "\n".join(out)


def _flush(buf: list) -> dict:
    return {"start": buf[0]["start"], "end": buf[-1]["end"],
            "text": _wrap(" ".join(w["word"].strip() for w in buf))}


def readable_cues(words: list) -> list:
    """Subtitles sized to be read: up to 2 lines, breaking on sense not clock."""
    cues, buf = [], []
    for i, w in enumerate(words):
        # Adding this word would overflow the cue: cut before it, at the best
        # boundary available, so no cue ever needs a third line.
        text = " ".join(x["word"].strip() for x in buf + [w])
        if buf and len(text) > MAX_CUE_CHARS:
            split = _best_split(buf)
            cues.append(_flush(buf[:split]))
            buf = buf[split:]
        buf.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        pause = (nxt["start"] - w["end"]) if nxt else 99.0
        too_slow = (w["end"] - buf[0]["start"]) >= MAX_CUE_SECONDS
        token = w["word"].strip()
        # Otherwise, prefer to break where the speaker finished a thought.
        if SENTENCE_END.search(token) or pause >= BREAK_PAUSE or too_slow or nxt is None:
            cues.append(_flush(buf))
            buf = []
    if buf:
        cues.append(_flush(buf))
    return _dehold(cues)


def _best_split(buf: list) -> int:
    """Index to cut an overflowing cue: after the last clause/sentence break
    that leaves a readable head, else as many words as fit on one line."""
    for j in range(len(buf) - 1, 0, -1):
        head = " ".join(x["word"].strip() for x in buf[:j + 1])
        if len(head) <= MAX_CUE_CHARS and (
                SENTENCE_END.search(buf[j]["word"].strip())
                or CLAUSE_END.search(buf[j]["word"].strip())):
            return j + 1
    # No punctuation to break on: take the most words that fit one line.
    for j in range(len(buf), 0, -1):
        if len(" ".join(x["word"].strip() for x in buf[:j])) <= MAX_CHARS_PER_LINE:
            return max(1, j)
    return 1


def _dehold(cues: list) -> list:
    """Stretch any cue too brief to read, without overlapping the next."""
    for i, c in enumerate(cues):
        if c["end"] - c["start"] < MIN_CUE_SECONDS:
            limit = cues[i + 1]["start"] if i + 1 < len(cues) else c["end"] + MIN_CUE_SECONDS
            c["end"] = min(c["start"] + MIN_CUE_SECONDS, max(limit, c["end"]))
    return cues


def readable_srt(words: list) -> str:
    return _srt(readable_cues(words))


def reading_transcript(words: list, para_seconds: float = 35.0) -> str:
    """Timecoded paragraphs for skimming a recording to find sections.

    Breaks on long pauses, which in practice are where the speaker changed
    topic or started a retake, and caps paragraph length so nothing becomes a
    wall of text.
    """
    paras, buf = [], []
    for i, w in enumerate(words):
        buf.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        pause = (nxt["start"] - w["end"]) if nxt else 99.0
        long_enough = (w["end"] - buf[0]["start"]) >= para_seconds
        if (pause >= 1.5 and long_enough) or (w["end"] - buf[0]["start"]) >= para_seconds * 2 or nxt is None:
            paras.append((buf[0]["start"], " ".join(x["word"].strip() for x in buf)))
            buf = []
    lines = ["# Transcript", ""]
    for start, text in paras:
        lines += [f"**[{fmt_timecode(start)}]** {text}", ""]
    return "\n".join(lines)


def silence_markers(words: list, min_gap: float = 2.0) -> list:
    """Long pauses: dead air to trim, and usually where retakes start."""
    out = []
    for i in range(1, len(words)):
        gap = words[i]["start"] - words[i - 1]["end"]
        if gap >= min_gap:
            out.append({"start": round(words[i - 1]["end"], 3),
                        "end": round(words[i]["start"], 3),
                        "duration": round(gap, 3)})
    return out
