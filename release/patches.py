from sqlite3 import Connection

from mix.auditions import get_audition
from mix.provenance import splice_provenance, timeline_provenance
from mix.wav import decode_wav, encode_wav
from release.editions import Edition, get_edition, store_patched_edition
from source.pcm import PCM_SAMPLE_BYTES


class InvalidPatch(ValueError):
    pass


def _target_ranges(value: object, frame_count: int, audition_frames: int) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, list) or not value:
        raise InvalidPatch('expected a nonempty list of target ranges')
    ranges = []
    for item in value:
        if not isinstance(item, dict):
            raise InvalidPatch('each target range must be an object')
        start_frame = item.get('start_frame')
        end_frame = item.get('end_frame')
        if type(start_frame) is not int or type(end_frame) is not int:
            raise InvalidPatch('frame bounds must be integers')
        if not 0 <= start_frame < end_frame <= frame_count:
            raise InvalidPatch('target range is empty or outside the base edition')
        if end_frame - start_frame != audition_frames:
            raise InvalidPatch('each target range must match the audition length')
        ranges.append((start_frame, end_frame))
    ordered = sorted(ranges)
    for (_, previous_end), (start_frame, _) in zip(ordered, ordered[1:]):
        if start_frame < previous_end:
            raise InvalidPatch('target ranges must not overlap')
    return tuple(ranges)


def patch_edition(
    db: Connection, base_edition_id: int, audition_id: object, target_ranges: object
) -> Edition:
    """Splice a stored audition into a signed edition inside the caller's write transaction."""
    if type(audition_id) is not int or audition_id < 1:
        raise InvalidPatch('audition_id must be a positive integer')
    base = get_edition(db, base_edition_id)
    audition = get_audition(db, audition_id)
    if audition.program_id != base.program_id:
        raise InvalidPatch('audition belongs to a different program')
    ranges = _target_ranges(target_ranges, base.frame_count, audition.frame_count)
    base_pcm, sample_rate = decode_wav(base.wav)
    if sample_rate != base.sample_rate or len(base_pcm) != base.frame_count * PCM_SAMPLE_BYTES:
        raise ValueError('inconsistent stored edition audio')
    pcm = bytearray(base_pcm)
    for start_frame, end_frame in ranges:
        pcm[start_frame * PCM_SAMPLE_BYTES:end_frame * PCM_SAMPLE_BYTES] = audition.pcm
    timeline = splice_provenance(timeline_provenance(base.timeline), audition.timeline, ranges)
    wav = encode_wav(bytes(pcm), base.sample_rate)
    return store_patched_edition(db, base, audition, timeline, wav)
