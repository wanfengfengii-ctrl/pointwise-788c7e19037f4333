import json
from dataclasses import dataclass
from sqlite3 import Connection

from mix.preview import Preview
from mix.provenance import ProvenanceEntry
from mix.timeline import TimelineEntry


@dataclass(frozen=True)
class Edition:
    edition_id: int
    program_id: str
    revision_id: int
    sample_rate: int
    frame_count: int
    timeline: tuple
    wav: bytes
    base_edition_id: int | None = None
    audition_id: int | None = None


class UnknownEdition(LookupError):
    pass


def ensure_edition_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS editions (
            edition_id INTEGER PRIMARY KEY,
            program_id TEXT NOT NULL REFERENCES programs(program_id),
            revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
            sample_rate INTEGER NOT NULL CHECK (sample_rate > 0),
            frame_count INTEGER NOT NULL CHECK (frame_count > 0),
            timeline_json TEXT NOT NULL,
            wav BLOB NOT NULL CHECK (length(wav) > 44)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS edition_patches (
            edition_id INTEGER PRIMARY KEY REFERENCES editions(edition_id),
            base_edition_id INTEGER NOT NULL REFERENCES editions(edition_id),
            audition_id INTEGER NOT NULL REFERENCES auditions(audition_id)
        )
    ''')


def store_edition(db: Connection, preview: Preview) -> Edition:
    timeline = preview.timeline
    cursor = db.execute('''
        INSERT INTO editions (program_id, revision_id, sample_rate, frame_count, timeline_json, wav)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        preview.program_id, preview.revision_id, preview.sample_rate, timeline.frame_count,
        json.dumps([entry.as_dict() for entry in timeline.entries], separators=(',', ':')), preview.wav,
    ))
    return Edition(cursor.lastrowid, preview.program_id, preview.revision_id,
                   preview.sample_rate, timeline.frame_count, timeline.entries, preview.wav)


def store_patched_edition(
    db: Connection,
    base: Edition,
    audition,
    timeline: tuple[ProvenanceEntry, ...],
    wav: bytes,
) -> Edition:
    cursor = db.execute('''
        INSERT INTO editions (program_id, revision_id, sample_rate, frame_count, timeline_json, wav)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        base.program_id, audition.revision_id, base.sample_rate, base.frame_count,
        json.dumps([entry.as_dict() for entry in timeline], separators=(',', ':')), wav,
    ))
    edition_id = cursor.lastrowid
    db.execute('''
        INSERT INTO edition_patches (edition_id, base_edition_id, audition_id) VALUES (?, ?, ?)
    ''', (edition_id, base.edition_id, audition.audition_id))
    return Edition(edition_id, base.program_id, audition.revision_id, base.sample_rate,
                   base.frame_count, timeline, wav, base.edition_id, audition.audition_id)


def get_edition(db: Connection, edition_id: int) -> Edition:
    row = db.execute('''
        SELECT edition_id, program_id, revision_id, sample_rate, frame_count, timeline_json, wav
        FROM editions WHERE edition_id = ?
    ''', (str(edition_id),)).fetchone()
    if row is None:
        raise UnknownEdition(edition_id)
    stored_id, program_id, revision_id, sample_rate, frame_count, timeline_json, wav = row
    patch = db.execute('''
        SELECT base_edition_id, audition_id FROM edition_patches WHERE edition_id = ?
    ''', (str(stored_id),)).fetchone()
    if patch is not None:
        timeline = tuple(ProvenanceEntry(**item) for item in json.loads(timeline_json))
        return Edition(stored_id, program_id, revision_id, sample_rate, frame_count,
                       timeline, wav, patch[0], patch[1])
    entries = tuple(TimelineEntry(**item) for item in json.loads(timeline_json))
    return Edition(stored_id, program_id, revision_id, sample_rate, frame_count, entries, wav)
