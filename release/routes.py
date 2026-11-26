from edit.revisions import UnknownRevision
from mix.auditions import UnknownAudition
from release.editions import UnknownEdition
from release.patches import InvalidPatch, patch_edition
from release.playback import edition_payload, read_playback
from release.publish import publish_revision


def post_editions(db, body):
    revision_id = body.get('revision_id')
    if type(revision_id) is not int or revision_id < 1:
        return 400, {'error': 'invalid_revision_id'}
    try:
        edition = publish_revision(db, revision_id)
    except UnknownRevision:
        return 404, {'error': 'unknown_revision'}
    return 201, edition_payload(edition)


def post_edition_patches(db, body, edition_id):
    try:
        edition = patch_edition(db, edition_id, body.get('audition_id'), body.get('target_ranges'))
    except UnknownEdition:
        return 404, {'error': 'unknown_edition'}
    except UnknownAudition:
        return 404, {'error': 'unknown_audition'}
    except InvalidPatch as exc:
        return 400, {'error': 'invalid_patch', 'detail': str(exc)}
    return 201, edition_payload(edition)


def get_edition_response(db, edition_id):
    try:
        playback = read_playback(db, edition_id)
    except UnknownEdition:
        return 404, {'error': 'unknown_edition'}
    return 200, playback


RELEASE_ROUTES = (
    ('POST', r'/editions', post_editions),
    ('POST', r'/editions/(?P<edition_id>[0-9]{1,19})/patches', post_edition_patches),
    ('GET', r'/editions/(?P<edition_id>[0-9]{1,19})', get_edition_response),
)
