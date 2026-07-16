"""Pure segment-timeline logic.

No pydoover / IO dependencies - everything here is a plain function over
dicts and ints so it can be unit-tested without a processor client.

A *segment* is a labelled, contiguous slice of a single timeline.

- The **open segment** (exactly one at all times) is a dict
  ``{"kind": str, "start_ts": int}`` where ``start_ts`` is an epoch-ms int.
- A **closed segment** is a dict
  ``{"kind": str, "start_ts": int, "end_ts": int}`` (epoch-ms ints).
"""

from __future__ import annotations

NONE_KIND = "None"


def valid_kinds(segment_kinds: list[str]) -> set[str]:
    """The set of kinds a segment may legally be: configured kinds + "None"."""
    return set(segment_kinds) | {NONE_KIND}


def derive_kind_options(segment_kinds: list[str], show_none: bool) -> list[str]:
    """Ordered dropdown options.

    "None" is included only when ``show_none`` is true - EXCEPT when
    ``segment_kinds`` is empty, in which case "None" is used regardless
    (there would otherwise be nothing to pick).
    """
    if not segment_kinds:
        return [NONE_KIND]
    options = list(segment_kinds)
    if show_none:
        options = [NONE_KIND] + options
    return options


def default_open_kind(segment_kinds: list[str]) -> str:
    """Kind the first-ever open segment starts as (always "None")."""
    return NONE_KIND


def clamp_switch_instant(
    client_ts: int | None, current_start_ts: int, now_ts: int
) -> int:
    """Effective switch instant.

    ``client_ts`` (the moment the operator picked the new kind, epoch-ms) is
    clamped to ``[current_start_ts, now_ts]`` so a switch can never open a
    segment before the current one started nor in the future. When
    ``client_ts`` is missing, ``now_ts`` is used.
    """
    if client_ts is None:
        return now_ts
    return max(current_start_ts, min(int(client_ts), now_ts))


def make_open_segment(kind: str, start_ts: int) -> dict:
    return {"kind": kind, "start_ts": int(start_ts)}


def close_segment(open_segment: dict, end_ts: int) -> dict:
    """Turn an open segment into a closed-segment record ending at ``end_ts``."""
    return {
        "record_type": "segment",
        "kind": open_segment["kind"],
        "start_ts": int(open_segment["start_ts"]),
        "end_ts": int(end_ts),
    }


def _intersect(a_start: int, a_end: int, b_start: int, b_end: int):
    """Intersection of ``[a_start, a_end)`` and ``[b_start, b_end)``.

    Returns ``(start, end)`` or ``None`` if the overlap is empty.
    """
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if start < end:
        return (start, end)
    return None


def compute_windows(
    closed_segments: list[dict],
    open_segment: dict | None,
    kind: str,
    start_ts: int,
    end_ts: int,
) -> list[tuple[int, int]]:
    """Windows of active ``kind`` inside ``[start_ts, end_ts]``.

    = every closed segment of ``kind`` intersected with the requested range,
    PLUS the open segment if it matches ``kind`` (treated as running up to
    ``end_ts``). Partial overlaps are clamped to the range. The result is
    sorted ascending; discontinuities (gaps between windows) are expected and
    preserved.
    """
    windows: list[tuple[int, int]] = []

    for seg in closed_segments:
        if seg.get("kind") != kind:
            continue
        overlap = _intersect(int(seg["start_ts"]), int(seg["end_ts"]), start_ts, end_ts)
        if overlap is not None:
            windows.append(overlap)

    if open_segment is not None and open_segment.get("kind") == kind:
        # The open segment has no end; treat it as running to end_ts.
        overlap = _intersect(int(open_segment["start_ts"]), end_ts, start_ts, end_ts)
        if overlap is not None:
            windows.append(overlap)

    windows.sort()
    return windows


def paint_segment(
    timeline: list[dict], start: int, end: int, kind: str, now: int
) -> list[dict]:
    """Paint ``[start, end]`` as ``kind`` over a contiguous timeline, normalising.

    ``timeline`` is a list of segment dicts ``{"kind","start_ts","end_ts"}`` that
    contiguously cover ``[T0, now]`` (the currently-open segment represented with
    ``end_ts == now``), sorted ascending, no gaps/overlaps. Returns the new
    timeline (same shape + invariants); its LAST segment ends at ``now`` and is
    the new open segment.

    Semantics — every instant belongs to exactly one kind:
      - ``[start, end]`` becomes ``kind``;
      - existing ``kind`` segments touched by ``[start, end]`` merge with it (and
        with each other) into one contiguous run — extending / combining;
      - other-kind segments fully inside ``[start, end]`` are removed;
      - other-kind segments partially overlapped are truncated.

    ``start``/``end`` are clamped to ``[T0, now]``; an empty range is a no-op
    (returns a copy of the input).
    """
    if not timeline:
        return []
    t0 = int(timeline[0]["start_ts"])
    tn = int(timeline[-1]["end_ts"])
    s = max(int(start), t0)
    e = min(int(end), tn)
    if s >= e:
        return [
            {"kind": seg["kind"], "start_ts": int(seg["start_ts"]), "end_ts": int(seg["end_ts"])}
            for seg in timeline
        ]

    # Subtract [s, e] from every existing segment (keep the outside parts),
    # then drop the painted interval in as one new segment of `kind`.
    pieces: list[dict] = []
    for seg in timeline:
        a = int(seg["start_ts"])
        b = int(seg["end_ts"])
        k = seg["kind"]
        if b <= s or a >= e:
            pieces.append({"kind": k, "start_ts": a, "end_ts": b})
            continue
        if a < s:
            pieces.append({"kind": k, "start_ts": a, "end_ts": s})
        if b > e:
            pieces.append({"kind": k, "start_ts": e, "end_ts": b})
    pieces.append({"kind": kind, "start_ts": s, "end_ts": e})

    pieces.sort(key=lambda p: p["start_ts"])

    # Merge contiguous same-kind runs (the sorted pieces already tile [t0, tn]).
    merged: list[dict] = []
    for p in pieces:
        if (
            merged
            and merged[-1]["kind"] == p["kind"]
            and merged[-1]["end_ts"] == p["start_ts"]
        ):
            merged[-1]["end_ts"] = p["end_ts"]
        else:
            merged.append(p)
    return merged


def select_boundary_crossing_segment(
    candidates: list[dict], end_ts: int
) -> dict | None:
    """The (at most one) closed segment that crosses the report end boundary.

    Closed-segment messages are timestamped at their END, so a segment that
    STARTS inside the requested range but was CLOSED after ``end_ts`` is not
    found by a fetch bounded ``before=end_ts`` — the caller forward-scans past
    ``end_ts`` and passes every segment record found there as ``candidates``.

    Because segments are contiguous (no gaps, no overlaps), at most one
    segment can straddle ``end_ts``: the candidate with the smallest end.
    Any later segment record necessarily has ``start_ts >= end_ts`` and can
    contribute nothing to the range. Returns that first candidate iff it
    genuinely started before ``end_ts`` (``compute_windows`` clamps the
    rest), else None.
    """
    segs = [c for c in candidates if c.get("record_type") == "segment"]
    if not segs:
        return None
    first = min(segs, key=lambda c: int(c["end_ts"]))
    if int(first["start_ts"]) < end_ts:
        return first
    return None
