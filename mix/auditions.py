import json
from dataclasses import dataclass
from sqlite3 import Connection

from mix.preview import build_preview
from mix.provenance import ProvenanceEntry, slice_provenance, timeline_provenance
from source.pcm import PCM_SAMPLE_BYTES


@dataclass(frozen=True)
class Audition:
    audition_id: int
    revision_id: int
    program_id: str
    sample_rate: int
    frame_count: int
    timeline: tuple[ProvenanceEntry, ...]
    pcm: bytes


class UnknownAudition(LookupError):
    pass


class InvalidAuditionRange(ValueError):
    pass


def ensure_audition_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS auditions (
            audition_id INTEGER PRIMARY KEY,
            revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
            program_id TEXT NOT NULL REFERENCES programs(program_id),
            sample_rate INTEGER NOT NULL CHECK (sample_rate > 0),
            frame_count INTEGER NOT NULL CHECK (frame_count > 0),
            timeline_json TEXT NOT NULL,
            pcm BLOB NOT NULL CHECK (length(pcm) = 2 * frame_count)
        )
    ''')


def record_audition(db: Connection, revision_id: int, start_frame: object, end_frame: object) -> Audition:
    """Snapshot the currently heard range so later takes cannot change it."""
    preview = build_preview(db, revision_id)
    if type(start_frame) is not int or type(end_frame) is not int:
        raise InvalidAuditionRange('frame bounds must be integers')
    if not 0 <= start_frame < end_frame <= preview.timeline.frame_count:
        raise InvalidAuditionRange('frame range is empty or outside the mix')
    timeline = slice_provenance(
        timeline_provenance(preview.timeline.entries), start_frame, end_frame,
    )
    pcm = preview.timeline.pcm[start_frame * PCM_SAMPLE_BYTES:end_frame * PCM_SAMPLE_BYTES]
    cursor = db.execute('''
        INSERT INTO auditions (revision_id, program_id, sample_rate, frame_count, timeline_json, pcm)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        preview.revision_id, preview.program_id, preview.sample_rate, end_frame - start_frame,
        json.dumps([entry.as_dict() for entry in timeline], separators=(',', ':')), pcm,
    ))
    return Audition(
        cursor.lastrowid, preview.revision_id, preview.program_id, preview.sample_rate,
        end_frame - start_frame, timeline, pcm,
    )


def get_audition(db: Connection, audition_id: int) -> Audition:
    row = db.execute('''
        SELECT audition_id, revision_id, program_id, sample_rate, frame_count, timeline_json, pcm
        FROM auditions WHERE audition_id = ?
    ''', (str(audition_id),)).fetchone()
    if row is None:
        raise UnknownAudition(audition_id)
    stored_id, revision_id, program_id, sample_rate, frame_count, timeline_json, pcm = row
    timeline = tuple(ProvenanceEntry(**item) for item in json.loads(timeline_json))
    return Audition(stored_id, revision_id, program_id, sample_rate, frame_count, timeline, pcm)
