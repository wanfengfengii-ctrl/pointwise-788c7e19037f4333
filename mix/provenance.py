from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProvenanceEntry:
    """An output range of a rendered product mapped to frames of its origin."""
    start_frame: int
    end_frame: int
    source_kind: str
    source_id: int
    source_start_frame: int
    source_end_frame: int

    def as_dict(self) -> dict:
        return asdict(self)


def timeline_provenance(entries) -> tuple[ProvenanceEntry, ...]:
    """Flatten mix or edition timeline entries to origin-relative provenance."""
    provenance = []
    for entry in entries:
        if isinstance(entry, ProvenanceEntry):
            provenance.append(entry)
        else:
            provenance.append(ProvenanceEntry(
                entry.start_frame, entry.end_frame, entry.source_kind, entry.source_id,
                0, entry.end_frame - entry.start_frame,
            ))
    return tuple(provenance)


def _subentry(entry: ProvenanceEntry, start_frame: int, end_frame: int) -> ProvenanceEntry:
    offset = start_frame - entry.start_frame
    return ProvenanceEntry(
        start_frame, end_frame, entry.source_kind, entry.source_id,
        entry.source_start_frame + offset,
        entry.source_start_frame + offset + (end_frame - start_frame),
    )


def slice_provenance(
    entries: tuple[ProvenanceEntry, ...], start_frame: int, end_frame: int
) -> tuple[ProvenanceEntry, ...]:
    """Rebased provenance covering the output range [start_frame, end_frame)."""
    sliced = []
    for entry in entries:
        lo = max(entry.start_frame, start_frame)
        hi = min(entry.end_frame, end_frame)
        if lo >= hi:
            continue
        part = _subentry(entry, lo, hi)
        sliced.append(ProvenanceEntry(
            lo - start_frame, hi - start_frame,
            part.source_kind, part.source_id, part.source_start_frame, part.source_end_frame,
        ))
    return tuple(sliced)


def _without_range(entry: ProvenanceEntry, start_frame: int, end_frame: int) -> tuple:
    if entry.end_frame <= start_frame or entry.start_frame >= end_frame:
        return (entry,)
    pieces = []
    if entry.start_frame < start_frame:
        pieces.append(_subentry(entry, entry.start_frame, start_frame))
    if end_frame < entry.end_frame:
        pieces.append(_subentry(entry, end_frame, entry.end_frame))
    return tuple(pieces)


def splice_provenance(
    base_entries: tuple[ProvenanceEntry, ...],
    insert_entries: tuple[ProvenanceEntry, ...],
    target_ranges,
) -> tuple[ProvenanceEntry, ...]:
    """Replace each non-overlapping target range with the insert provenance rebased to it."""
    kept = list(base_entries)
    inserted = []
    for range_start, range_end in sorted(target_ranges):
        kept = [
            piece
            for entry in kept
            for piece in _without_range(entry, range_start, range_end)
        ]
        inserted.extend(
            ProvenanceEntry(
                entry.start_frame + range_start, entry.end_frame + range_start,
                entry.source_kind, entry.source_id,
                entry.source_start_frame, entry.source_end_frame,
            )
            for entry in insert_entries
        )
    return tuple(sorted([*kept, *inserted], key=lambda entry: entry.start_frame))
