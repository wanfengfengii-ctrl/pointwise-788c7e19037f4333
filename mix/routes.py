from base64 import b64encode

from edit.revisions import UnknownRevision
from mix.auditions import InvalidAuditionRange, record_audition
from mix.preview import build_preview
from mix.wav import encode_wav


def preview_response(preview):
    return {
        'program_id': preview.program_id,
        'revision_id': preview.revision_id,
        'sample_rate': preview.sample_rate,
        'frame_count': preview.timeline.frame_count,
        'timeline': [entry.as_dict() for entry in preview.timeline.entries],
        'wav': b64encode(preview.wav).decode('ascii'),
    }


def get_mix(db, revision_id):
    try:
        preview = build_preview(db, revision_id)
    except UnknownRevision:
        return 404, {'error': 'unknown_revision'}
    return 200, preview_response(preview)


def audition_response(audition):
    return {
        'audition_id': audition.audition_id,
        'revision_id': audition.revision_id,
        'program_id': audition.program_id,
        'sample_rate': audition.sample_rate,
        'frame_count': audition.frame_count,
        'timeline': [entry.as_dict() for entry in audition.timeline],
        'wav': b64encode(encode_wav(audition.pcm, audition.sample_rate)).decode('ascii'),
    }


def post_audition(db, body, revision_id):
    try:
        audition = record_audition(db, revision_id, body.get('start_frame'), body.get('end_frame'))
    except UnknownRevision:
        return 404, {'error': 'unknown_revision'}
    except InvalidAuditionRange as exc:
        return 400, {'error': 'invalid_frame_range', 'detail': str(exc)}
    return 201, audition_response(audition)


MIX_ROUTES = (
    ('GET', r'/mix/(?P<revision_id>[0-9]{1,19})', get_mix),
    ('POST', r'/mix/(?P<revision_id>[0-9]{1,19})/auditions', post_audition),
)
