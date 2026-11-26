import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.support import RunningService, pcm, read_wave


def call(service, method, path, body=None):
    status, payload = service.request(method, path, body)
    expected = 201 if method == "POST" else 200
    if status != expected:
        raise AssertionError(f"{method} {path}: expected {expected}, got {status} {payload}")
    return payload


def prepare(service):
    def proof(description, samples, ranges, parent):
        audio = call(service, "POST", "/sources", {
            "program_id": "G", "description": description, "pcm": pcm(samples),
        })
        segments = [call(service, "POST", "/segments", {
            "source_id": audio["source_id"], "start_frame": start, "end_frame": end,
        })["segment_id"] for start, end in ranges]
        revision = call(service, "POST", "/revisions", {
            "program_id": "G", "expected_revision_id": parent, "segment_ids": segments,
        })
        return revision["revision_id"], segments

    base_revision, base_segments = proof("底稿原声", [10, 11, 12, 20, 21, 22], [(0, 3), (3, 6)], None)
    base = call(service, "POST", "/editions", {"revision_id": base_revision})
    x_revision, _ = proof("第一处选段", [1, 2, 3, 4], [(0, 4)], base_revision)
    order = call(service, "POST", "/voice-orders", {"revision_id": x_revision, "slots": [1]})
    take_path = "/voice-orders/{order_id}/takes".format(**order)
    first = call(service, "POST", take_path, {"request_id": "first", "parts": [pcm([99, 100, 101, 102])]})
    y_revision, y_segments = proof("第二处选段", [200, 201], [(0, 2)], x_revision)
    return {
        "base": base, "base_segments": base_segments, "x_revision": x_revision,
        "take_path": take_path, "first_part_id": first["parts"][0]["part_id"],
        "y_revision": y_revision, "y_segment": y_segments[0],
    }


def redub(service, fixture):
    receipt = call(service, "POST", fixture["take_path"], {
        "request_id": "replacement", "parts": [pcm([899, 900, 901, 902])],
    })
    return receipt["parts"][0]["part_id"]


def run(service):
    fixture = prepare(service)
    x_path = "/mix/{x_revision}".format(**fixture)
    before = call(service, "GET", x_path)
    replacement_part_id = redub(service, fixture)
    service.restart()
    after = call(service, "GET", x_path)
    base = call(service, "GET", "/editions/{edition_id}".format(**fixture["base"]))
    y = call(service, "GET", "/mix/{y_revision}".format(**fixture))
    if read_wave(before) != (8000, 4, [99, 100, 101, 102]) or read_wave(after) != (8000, 4, [899, 900, 901, 902]):
        raise AssertionError("普通混听应随替录更新")
    for heard, part_id in ((before, fixture["first_part_id"]), (after, replacement_part_id)):
        entry, = heard["timeline"]
        if (entry["source_kind"], entry["source_id"]) != ("voice", part_id):
            raise AssertionError("普通混听的实收出处错误")
    if fixture["first_part_id"] == replacement_part_id:
        raise AssertionError("替录须有独立的实收号")
    if base != fixture["base"] or read_wave(base) != (8000, 6, [10, 11, 12, 20, 21, 22]):
        raise AssertionError("已签底稿在替录及重开后应保持原样")
    if read_wave(y) != (8000, 2, [200, 201]):
        raise AssertionError("第二处选段的原声错误")
    print(json.dumps({
        "base": {"edition_id": base["edition_id"], "frames": read_wave(base)[2]},
        "before": {"frames": read_wave(before)[2], "part_id": fixture["first_part_id"]},
        "after": {"frames": read_wave(after)[2], "part_id": replacement_part_id},
        "followup_frames": read_wave(y)[2],
    }, ensure_ascii=False))


def main():
    with TemporaryDirectory() as directory:
        with RunningService(Path(directory) / "workbench.sqlite3") as service:
            run(service)


if __name__ == "__main__":
    main()
