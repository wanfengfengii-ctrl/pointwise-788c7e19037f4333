"""Demonstrate PATCHES.md: sign two generations of patched editions.

Runs the patch flow against its own service, then fetches both derived editions
back by id after a restart and prints their decoded frames and provenance.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from patch_example import prepare, redub
from tests.support import RunningService, read_wave


def call(service, method, path, body=None):
    status, payload = service.request(method, path, body)
    expected = 201 if method == 'POST' else 200
    if status != expected:
        raise AssertionError(f'{method} {path}: expected {expected}, got {status} {payload}')
    return payload


def require_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f'{label}: expected {expected!r}, got {actual!r}')


def run(service):
    fixture = prepare(service)
    base = fixture['base']

    # 定稿员试听首份实收的三帧；配音师随后交了替录，重开服务后按原试听签发。
    audition = call(service, 'POST', f"/mix/{fixture['x_revision']}/auditions",
                    {'start_frame': 1, 'end_frame': 4})
    redub(service, fixture)
    service.restart()
    first = call(service, 'POST', f"/editions/{base['edition_id']}/patches", {
        'audition_id': audition['audition_id'],
        'target_ranges': [{'start_frame': 2, 'end_frame': 5}],
    })

    # 新成品接着换声：第二份试听跨过第一次换声的尾接缝。
    followup = call(service, 'POST', f"/mix/{fixture['y_revision']}/auditions",
                    {'start_frame': 0, 'end_frame': 2})
    second = call(service, 'POST', f"/editions/{first['edition_id']}/patches", {
        'audition_id': followup['audition_id'],
        'target_ranges': [{'start_frame': 4, 'end_frame': 6}],
    })

    # 重开服务，按号领回两代成品。
    service.restart()
    fetched_first = call(service, 'GET', f"/editions/{first['edition_id']}")
    fetched_second = call(service, 'GET', f"/editions/{second['edition_id']}")
    fetched_base = call(service, 'GET', f"/editions/{base['edition_id']}")
    require_equal(fetched_first, first, 'first generation playback')
    require_equal(fetched_second, second, 'second generation playback')
    require_equal(fetched_base, base, 'base edition playback')
    require_equal(read_wave(fetched_first), (8000, 6, [10, 11, 100, 101, 102, 22]), 'first frames')
    require_equal(read_wave(fetched_second), (8000, 6, [10, 11, 100, 101, 200, 201]), 'second frames')

    for generation, payload in ((0, fetched_base), (1, fetched_first), (2, fetched_second)):
        print(json.dumps({
            'generation': generation,
            'edition_id': payload['edition_id'],
            'base_edition_id': payload.get('base_edition_id'),
            'audition_id': payload.get('audition_id'),
            'frames': read_wave(payload)[2],
            'provenance': payload['timeline'],
        }, ensure_ascii=False))


def main():
    with TemporaryDirectory() as directory:
        with RunningService(Path(directory) / 'workbench.sqlite3') as service:
            run(service)


if __name__ == '__main__':
    main()
