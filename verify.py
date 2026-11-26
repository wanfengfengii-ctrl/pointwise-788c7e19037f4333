"""Run the original regression plus HTTP checks of the PATCHES.md patch flow.

Keeps the complete original unittest regression, then starts its own service to
check signing from an audition after a replacement take, cross-seam re-patching,
fetching editions by id, and the edition state after rejected or failed patches.
"""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import check_project
from patch_example import prepare, redub
from tests.support import RunningService, commit_failure, read_wave


def expect_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f'{label}\n  expected: {expected!r}\n  actual:   {actual!r}')


def provenance(payload):
    return [
        [entry['start_frame'], entry['end_frame'], entry['source_kind'], entry['source_id'],
         entry['source_start_frame'], entry['source_end_frame']]
        for entry in payload['timeline']
    ]


def check_patch_flow(service, database):
    fixture = prepare(service)
    base = fixture['base']
    base_id = base['edition_id']
    a_segment, b_segment = fixture['base_segments']
    first_part = fixture['first_part_id']
    y_segment = fixture['y_segment']

    def request(method, path, body=None, status=None):
        expected = status if status is not None else (201 if method == 'POST' else 200)
        actual, payload = service.request(method, path, body)
        if actual != expected:
            raise AssertionError(f'{method} {path}: expected {expected}, got {actual}: {payload}')
        return payload

    # 替录后签发：试听三帧后交替录并重开服务，原试听仍签发当时听到的声音。
    audition = request('POST', f"/mix/{fixture['x_revision']}/auditions",
                       {'start_frame': 1, 'end_frame': 4})
    expect_equal(read_wave(audition), (8000, 3, [100, 101, 102]), 'audition frames')
    expect_equal(provenance(audition), [[0, 3, 'voice', first_part, 1, 4]], 'audition provenance')
    redub(service, fixture)
    service.restart()
    expect_equal(read_wave(request('GET', f"/mix/{fixture['x_revision']}")),
                 (8000, 4, [899, 900, 901, 902]), 'mix after redub')
    patched = request('POST', f'/editions/{base_id}/patches', {
        'audition_id': audition['audition_id'],
        'target_ranges': [{'start_frame': 2, 'end_frame': 5}],
    })
    expect_equal(patched['base_edition_id'], base_id, 'patched base id')
    expect_equal(patched['audition_id'], audition['audition_id'], 'patched audition id')
    expect_equal(read_wave(patched), (8000, 6, [10, 11, 100, 101, 102, 22]), 'patched frames')
    expect_equal(provenance(patched), [
        [0, 2, 'source', a_segment, 0, 2],
        [2, 5, 'voice', first_part, 1, 4],
        [5, 6, 'source', b_segment, 2, 3],
    ], 'patched provenance')
    expect_equal(request('GET', f"/editions/{patched['edition_id']}"), patched, 'fetch patched')

    # 跨缝再换：第二份试听换入第一份派生成品，跨过第一次换声的尾接缝。
    followup = request('POST', f"/mix/{fixture['y_revision']}/auditions",
                       {'start_frame': 0, 'end_frame': 2})
    expect_equal(read_wave(followup), (8000, 2, [200, 201]), 'followup audition frames')
    repatched = request('POST', f"/editions/{patched['edition_id']}/patches", {
        'audition_id': followup['audition_id'],
        'target_ranges': [{'start_frame': 4, 'end_frame': 6}],
    })
    expect_equal(read_wave(repatched), (8000, 6, [10, 11, 100, 101, 200, 201]), 'repatched frames')
    expect_equal(provenance(repatched), [
        [0, 2, 'source', a_segment, 0, 2],
        [2, 4, 'voice', first_part, 1, 3],
        [4, 6, 'source', y_segment, 0, 2],
    ], 'repatched provenance')

    # 同一份试听一次换多个互不重叠区间（乱序给出）。
    multi = request('POST', f"/editions/{patched['edition_id']}/patches", {
        'audition_id': followup['audition_id'],
        'target_ranges': [{'start_frame': 4, 'end_frame': 6}, {'start_frame': 0, 'end_frame': 2}],
    })
    expect_equal(read_wave(multi), (8000, 6, [200, 201, 100, 101, 200, 201]), 'multi frames')
    expect_equal(provenance(multi), [
        [0, 2, 'source', y_segment, 0, 2],
        [2, 4, 'voice', first_part, 1, 3],
        [4, 6, 'source', y_segment, 0, 2],
    ], 'multi provenance')

    # 拒绝的换声不留下可领取的新成品，同一试听仍可用于有效签发。
    rejections = [
        ('/editions/9999/patches', {'audition_id': audition['audition_id'],
                                    'target_ranges': [{'start_frame': 0, 'end_frame': 3}]}, 404),
        (f'/editions/{base_id}/patches', {'audition_id': 9999,
                                          'target_ranges': [{'start_frame': 0, 'end_frame': 3}]}, 404),
        (f'/editions/{base_id}/patches', {'audition_id': True,
                                          'target_ranges': [{'start_frame': 0, 'end_frame': 3}]}, 400),
        (f'/editions/{base_id}/patches', {'audition_id': audition['audition_id'],
                                          'target_ranges': []}, 400),
        (f'/editions/{base_id}/patches', {'audition_id': audition['audition_id'],
                                          'target_ranges': [{'start_frame': 0, 'end_frame': 2}]}, 400),
        (f'/editions/{base_id}/patches', {'audition_id': audition['audition_id'],
                                          'target_ranges': [{'start_frame': 4, 'end_frame': 7}]}, 400),
        (f'/editions/{base_id}/patches', {'audition_id': audition['audition_id'],
                                          'target_ranges': [{'start_frame': 0, 'end_frame': 3},
                                                            {'start_frame': 2, 'end_frame': 5}]}, 400),
        (f'/editions/{base_id}/patches', {'audition_id': audition['audition_id'],
                                          'target_ranges': [{'start_frame': True, 'end_frame': 3}]}, 400),
    ]
    for path, body, status in rejections:
        error = request('POST', path, body, status=status)
        if 'error' not in error:
            raise AssertionError(f'rejection for {body!r} lacks an error field: {error}')
    request('GET', '/editions/5', status=404)
    fifth = request('POST', f'/editions/{base_id}/patches', {
        'audition_id': audition['audition_id'],
        'target_ranges': [{'start_frame': 0, 'end_frame': 3}],
    })
    expect_equal(fifth['edition_id'], 5, 'edition id after rejections')
    expect_equal(read_wave(fifth), (8000, 6, [100, 101, 102, 20, 21, 22]), 'fifth frames')

    # 写败的换声同样不留成品。
    with commit_failure(database, 'editions'):
        error = request('POST', f'/editions/{base_id}/patches', {
            'audition_id': audition['audition_id'],
            'target_ranges': [{'start_frame': 3, 'end_frame': 6}],
        }, status=500)
        expect_equal(error, {'error': 'database_failure'}, 'write failure response')
        request('GET', '/editions/6', status=404)
    sixth = request('POST', f'/editions/{base_id}/patches', {
        'audition_id': audition['audition_id'],
        'target_ranges': [{'start_frame': 3, 'end_frame': 6}],
    })
    expect_equal(sixth['edition_id'], 6, 'edition id after write failure')

    # 按号领取：重开服务后底稿与全部派生成品各自按号领回。
    service.restart()
    signed = {base_id: base, 2: patched, 3: repatched, 4: multi, 5: fifth, 6: sixth}
    for edition_id, payload in signed.items():
        expect_equal(request('GET', f'/editions/{edition_id}'), payload, f'fetch edition {edition_id}')
    request('GET', '/editions/7', status=404)
    print('PATCH FLOW PASS '
          f'(signed after redub: edition 2, cross-seam: edition 3, fetched by id: {len(signed)})')


def main():
    regression_code = check_project.main()
    try:
        with TemporaryDirectory() as directory:
            database = Path(directory) / 'workbench.sqlite3'
            with RunningService(database) as service:
                check_patch_flow(service, database)
    except Exception as exc:
        print(f'PATCH FLOW FAIL: {exc}', file=sys.stderr)
        return 1
    return 0 if regression_code == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
