from release.server import initialize_database
from source.programs import ProgramSpec
from tests.support import WorkbenchTest, read_wave


class PatchTests(WorkbenchTest):
    def audition(self, revision_id, start_frame, end_frame, status=201):
        return self.api('POST', f'/mix/{revision_id}/auditions', {
            'start_frame': start_frame, 'end_frame': end_frame,
        }, status=status)

    def patch(self, base_id, audition_id, target_ranges, status=201):
        return self.api('POST', f'/editions/{base_id}/patches', {
            'audition_id': audition_id, 'target_ranges': target_ranges,
        }, status=status)

    def patch_fixture(self):
        source_id = self.source(samples=(10, 11, 12, 20, 21, 22))['source_id']
        a = self.segment(source_id, 0, 3)['segment_id']
        b = self.segment(source_id, 3, 6)['segment_id']
        base_revision = self.proof([a, b])['revision_id']
        base = self.edition(base_revision)
        x_segment = self.segment(self.source(samples=(1, 2, 3, 4))['source_id'], 0, 4)['segment_id']
        x_revision = self.proof([x_segment], base_revision)['revision_id']
        order_id = self.voice_order(x_revision, [1])['order_id']
        first = self.submit(order_id, 'first', [[99, 100, 101, 102]])
        y_segment = self.segment(self.source(samples=(200, 201))['source_id'], 0, 2)['segment_id']
        y_revision = self.proof([y_segment], x_revision)['revision_id']
        return {
            'a': a, 'b': b, 'base': base, 'x_revision': x_revision, 'order_id': order_id,
            'first_part_id': first['parts'][0]['part_id'],
            'y_segment': y_segment, 'y_revision': y_revision,
        }

    @staticmethod
    def provenance(payload):
        return [
            (entry['start_frame'], entry['end_frame'], entry['source_kind'], entry['source_id'],
             entry['source_start_frame'], entry['source_end_frame'])
            for entry in payload['timeline']
        ]

    def test_audition_response(self):
        fixture = self.patch_fixture()
        audition = self.audition(fixture['x_revision'], 1, 4)
        self.assertEqual(audition['audition_id'], 1)
        self.assertEqual(audition['revision_id'], fixture['x_revision'])
        self.assertEqual(audition['program_id'], 'G')
        self.assertEqual(audition['sample_rate'], 8000)
        self.assertEqual(audition['frame_count'], 3)
        self.assertEqual(set(audition), {'audition_id', 'revision_id', 'program_id', 'sample_rate',
                                         'frame_count', 'timeline', 'wav'})
        self.assertEqual(audition['timeline'], [{
            'start_frame': 0, 'end_frame': 3, 'source_kind': 'voice',
            'source_id': fixture['first_part_id'], 'source_start_frame': 1, 'source_end_frame': 4,
        }])
        self.assertEqual(read_wave(audition), (8000, 3, [100, 101, 102]))
        self.assert_audio(self.preview(fixture['x_revision']), [99, 100, 101, 102])

    def test_audition_across_slots(self):
        a, b, c = self.story_segments()
        revision_id = self.proof([c, b, a])['revision_id']
        order_id = self.voice_order(revision_id, [2])['order_id']
        voiced = self.submit(order_id, 'middle', [[120, 121, 122]])['parts'][0]['part_id']
        audition = self.audition(revision_id, 1, 6)
        self.assertEqual(read_wave(audition), (8000, 5, [31, 120, 121, 122, 10]))
        self.assertEqual(audition['timeline'], [
            {'start_frame': 0, 'end_frame': 1, 'source_kind': 'source', 'source_id': c,
             'source_start_frame': 1, 'source_end_frame': 2},
            {'start_frame': 1, 'end_frame': 4, 'source_kind': 'voice', 'source_id': voiced,
             'source_start_frame': 0, 'source_end_frame': 3},
            {'start_frame': 4, 'end_frame': 5, 'source_kind': 'source', 'source_id': a,
             'source_start_frame': 0, 'source_end_frame': 1},
        ])

    def test_audition_errors(self):
        fixture = self.patch_fixture()
        for start, end in ((2, 2), (4, 3), (-1, 2), (0, 5), (0.0, 2), (False, 2), (0, '2'), (None, 2)):
            with self.subTest(start=start, end=end):
                error = self.audition(fixture['x_revision'], start, end, status=400)
                self.assertIn('error', error)
        self.audition(9999, 0, 1, status=404)
        self.assertEqual(self.stored('SELECT COUNT(*) FROM auditions'), [(0,)])
        audition = self.audition(fixture['x_revision'], 0, 4)
        self.assertEqual(read_wave(audition), (8000, 4, [99, 100, 101, 102]))

    def test_patch_after_redub_and_restart(self):
        fixture = self.patch_fixture()
        audition = self.audition(fixture['x_revision'], 1, 4)
        self.submit(fixture['order_id'], 'replacement', [[899, 900, 901, 902]])
        self.service.restart()
        self.assert_audio(self.preview(fixture['x_revision']), [899, 900, 901, 902])
        patched = self.patch(fixture['base']['edition_id'], audition['audition_id'],
                             [{'start_frame': 2, 'end_frame': 5}])
        self.assertEqual(patched['edition_id'], 2)
        self.assertEqual(patched['base_edition_id'], fixture['base']['edition_id'])
        self.assertEqual(patched['audition_id'], audition['audition_id'])
        self.assertEqual(patched['program_id'], 'G')
        self.assertEqual(patched['sample_rate'], 8000)
        self.assertEqual(patched['frame_count'], 6)
        self.assertNotIn('revision_id', patched)
        self.assertEqual(read_wave(patched), (8000, 6, [10, 11, 100, 101, 102, 22]))
        self.assertEqual(self.provenance(patched), [
            (0, 2, 'source', fixture['a'], 0, 2),
            (2, 5, 'voice', fixture['first_part_id'], 1, 4),
            (5, 6, 'source', fixture['b'], 2, 3),
        ])
        self.assertEqual(self.api('GET', f"/editions/{patched['edition_id']}"), patched)
        self.assertEqual(self.api('GET', f"/editions/{fixture['base']['edition_id']}"), fixture['base'])

    def test_cross_seam_repatch(self):
        fixture = self.patch_fixture()
        audition = self.audition(fixture['x_revision'], 1, 4)
        self.submit(fixture['order_id'], 'replacement', [[899, 900, 901, 902]])
        patched = self.patch(fixture['base']['edition_id'], audition['audition_id'],
                             [{'start_frame': 2, 'end_frame': 5}])
        followup = self.audition(fixture['y_revision'], 0, 2)
        repatched = self.patch(patched['edition_id'], followup['audition_id'],
                               [{'start_frame': 4, 'end_frame': 6}])
        self.assertEqual(repatched['base_edition_id'], patched['edition_id'])
        self.assertEqual(read_wave(repatched), (8000, 6, [10, 11, 100, 101, 200, 201]))
        self.assertEqual(self.provenance(repatched), [
            (0, 2, 'source', fixture['a'], 0, 2),
            (2, 4, 'voice', fixture['first_part_id'], 1, 3),
            (4, 6, 'source', fixture['y_segment'], 0, 2),
        ])
        self.service.restart()
        self.assertEqual(self.api('GET', f"/editions/{fixture['base']['edition_id']}"), fixture['base'])
        self.assertEqual(self.api('GET', f"/editions/{patched['edition_id']}"), patched)
        self.assertEqual(self.api('GET', f"/editions/{repatched['edition_id']}"), repatched)

    def test_multi_range_patch(self):
        fixture = self.patch_fixture()
        audition = self.audition(fixture['x_revision'], 1, 4)
        patched = self.patch(fixture['base']['edition_id'], audition['audition_id'],
                             [{'start_frame': 2, 'end_frame': 5}])
        followup = self.audition(fixture['y_revision'], 0, 2)
        multi = self.patch(patched['edition_id'], followup['audition_id'],
                           [{'start_frame': 4, 'end_frame': 6}, {'start_frame': 0, 'end_frame': 2}])
        self.assertEqual(read_wave(multi), (8000, 6, [200, 201, 100, 101, 200, 201]))
        self.assertEqual(self.provenance(multi), [
            (0, 2, 'source', fixture['y_segment'], 0, 2),
            (2, 4, 'voice', fixture['first_part_id'], 1, 3),
            (4, 6, 'source', fixture['y_segment'], 0, 2),
        ])
        adjacent = self.patch(fixture['base']['edition_id'], followup['audition_id'],
                              [{'start_frame': 0, 'end_frame': 2}, {'start_frame': 2, 'end_frame': 4},
                               {'start_frame': 4, 'end_frame': 6}])
        self.assertEqual(read_wave(adjacent), (8000, 6, [200, 201, 200, 201, 200, 201]))
        self.assertEqual(self.provenance(adjacent), [
            (0, 2, 'source', fixture['y_segment'], 0, 2),
            (2, 4, 'source', fixture['y_segment'], 0, 2),
            (4, 6, 'source', fixture['y_segment'], 0, 2),
        ])

    def test_patch_errors(self):
        fixture = self.patch_fixture()
        audition = self.audition(fixture['x_revision'], 1, 4)
        base_id = fixture['base']['edition_id']
        not_found = self.patch(9999, audition['audition_id'],
                               [{'start_frame': 0, 'end_frame': 3}], status=404)
        self.assertEqual(not_found['error'], 'unknown_edition')
        not_found = self.patch(base_id, 9999, [{'start_frame': 0, 'end_frame': 3}], status=404)
        self.assertEqual(not_found['error'], 'unknown_audition')
        for change in (
            {'audition_id': True}, {'audition_id': '1'}, {'audition_id': 0}, {'audition_id': -1},
            {'target_ranges': []}, {'target_ranges': 'x'}, {'target_ranges': [3]},
            {'target_ranges': [{}]}, {'target_ranges': [{'start_frame': 0}]},
            {'target_ranges': [{'start_frame': True, 'end_frame': 3}]},
            {'target_ranges': [{'start_frame': 0.0, 'end_frame': 3}]},
            {'target_ranges': [{'start_frame': 2, 'end_frame': 2}]},
            {'target_ranges': [{'start_frame': 3, 'end_frame': 2}]},
            {'target_ranges': [{'start_frame': -1, 'end_frame': 2}]},
            {'target_ranges': [{'start_frame': 4, 'end_frame': 7}]},
            {'target_ranges': [{'start_frame': 0, 'end_frame': 2}]},
            {'target_ranges': [{'start_frame': 0, 'end_frame': 3},
                               {'start_frame': 2, 'end_frame': 5}]},
            {'target_ranges': [{'start_frame': 0, 'end_frame': 3},
                               {'start_frame': 0, 'end_frame': 3}]},
        ):
            with self.subTest(change=change):
                body = {'audition_id': audition['audition_id'],
                        'target_ranges': [{'start_frame': 0, 'end_frame': 3}], **change}
                error = self.api('POST', f'/editions/{base_id}/patches', body, status=400)
                self.assertIn('error', error)
        self.assertEqual(self.stored('SELECT COUNT(*) FROM editions'), [(1,)])
        self.assertEqual(self.stored('SELECT COUNT(*) FROM edition_patches'), [(0,)])
        self.api('GET', '/editions/2', status=404)
        patched = self.patch(base_id, audition['audition_id'], [{'start_frame': 0, 'end_frame': 3}])
        self.assertEqual(patched['edition_id'], 2)
        self.assertEqual(read_wave(patched), (8000, 6, [100, 101, 102, 20, 21, 22]))

    def test_cross_program_rejected(self):
        fixture = self.patch_fixture()
        initialize_database(self.database, (ProgramSpec('H', 16000),))
        foreign = self.source(samples=(1, 2, 3), program='H', rate=16000)
        segment_id = self.segment(foreign['source_id'], 0, 3)['segment_id']
        proof = self.api('POST', '/revisions', {
            'program_id': 'H', 'expected_revision_id': None, 'segment_ids': [segment_id],
        })
        audition = self.audition(proof['revision_id'], 0, 3)
        error = self.patch(fixture['base']['edition_id'], audition['audition_id'],
                           [{'start_frame': 0, 'end_frame': 3}], status=400)
        self.assertIn('error', error)
        self.assertEqual(self.stored('SELECT COUNT(*) FROM editions'), [(1,)])
        self.api('GET', '/editions/2', status=404)

    def test_failed_patch_write(self):
        fixture = self.patch_fixture()
        audition = self.audition(fixture['x_revision'], 1, 4)
        base_id = fixture['base']['edition_id']
        with self.fail_commit_on('editions'):
            error = self.patch(base_id, audition['audition_id'],
                               [{'start_frame': 2, 'end_frame': 5}], status=500)
            self.assertEqual(error, {'error': 'database_failure'})
            self.assertEqual(self.stored('SELECT COUNT(*) FROM editions'), [(1,)])
            self.assertEqual(self.stored('SELECT COUNT(*) FROM edition_patches'), [(0,)])
            self.api('GET', '/editions/2', status=404)
        patched = self.patch(base_id, audition['audition_id'], [{'start_frame': 2, 'end_frame': 5}])
        self.assertEqual(patched['edition_id'], 2)
        self.assertEqual(read_wave(patched), (8000, 6, [10, 11, 100, 101, 102, 22]))

    def test_audition_reusable_after_restart(self):
        fixture = self.patch_fixture()
        audition = self.audition(fixture['x_revision'], 1, 4)
        self.service.restart()
        first = self.patch(fixture['base']['edition_id'], audition['audition_id'],
                           [{'start_frame': 0, 'end_frame': 3}])
        second = self.patch(fixture['base']['edition_id'], audition['audition_id'],
                            [{'start_frame': 3, 'end_frame': 6}])
        self.assertEqual(read_wave(first), (8000, 6, [100, 101, 102, 20, 21, 22]))
        self.assertEqual(read_wave(second), (8000, 6, [10, 11, 12, 100, 101, 102]))
        self.assertNotEqual(first['edition_id'], second['edition_id'])
        self.assertEqual(self.api('GET', f"/editions/{first['edition_id']}"), first)
        self.assertEqual(self.api('GET', f"/editions/{second['edition_id']}"), second)
