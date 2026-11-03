import copy
import itertools
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_asset_dependencies import fixture
import studio
import setup


class GenerationModesTests(unittest.TestCase):
    def test_new_film_defaults_and_explicit_standard(self):
        obj=object.__new__(studio.Studio)
        obj.save=lambda p:p
        for data, expected in [({}, ('fast','klein','klein','fast')),
                               ({'ai_mode':'normal'}, ('normal','hidream','qwen','detailed'))]:
            p=obj.create(data)
            self.assertEqual(tuple(p[k] for k in ('ai_mode','image_backend','frame_backend','image_quality')), expected)

    def test_mode_change_applies_preset_but_same_mode_preserves_customization(self):
        obj,p,_=self.fake()
        obj.update('film', {'ai_mode':'fast','image_backend':'hidream'})
        self.assertEqual((p['image_backend'],p['frame_backend'],p['image_quality']), ('klein','klein','fast'))
        obj.update('film', {'ai_mode':'fast','image_backend':'hidream'})
        self.assertEqual(p['image_backend'],'hidream')
        obj.update('film', {'ai_mode':'normal'})
        self.assertEqual((p['image_backend'],p['frame_backend'],p['image_quality']), ('hidream','qwen','detailed'))

    def fake(self):
        project, first = fixture()
        project['ai_mode']='normal'
        for name in ('second','third','fourth'):
            shot=copy.deepcopy(first)
            shot.update(id=name,transition='cut',frame_source='storyboard')
            project['shots'].append(shot)
        obj=object.__new__(studio.Studio)
        obj.lock=threading.RLock()
        obj.jobs=[]
        obj.queue=queue.PriorityQueue()
        obj.order=itertools.count()
        obj.load=lambda _:copy.deepcopy(project)
        def save(p):
            project.clear();project.update(copy.deepcopy(p));return p
        obj.save=save
        return obj,project,first

    def job(self,kind,shot=None):
        return {'id':kind+str(shot),'project':'film','kind':kind,'shot':shot,'state':'queued','label':kind}

    def test_mode_scoped_per_job_and_reset_after_exception(self):
        self.assertEqual(studio.graphs.writer_node()['inputs']['mode'],'normal')
        with self.assertRaises(RuntimeError):
            with studio.graphs.using_writer('fast'):
                self.assertEqual(studio.graphs.writer_node()['inputs']['mode'],'fast')
                raise RuntimeError('fixture')
        self.assertEqual(studio.graphs.writer_node()['inputs']['mode'],'normal')
        with self.assertRaises(ValueError):
            with studio.graphs.using_writer('unknown'):pass

    def test_enqueue_snapshots_mode_and_deduplicates_double_click(self):
        obj,p,s=self.fake()
        first=obj.enqueue('sketch','film',s['id'],'Storyboard 1')
        p['ai_mode']='fast'
        self.assertEqual(obj.enqueue('sketch','film',s['id'])['id'],first['id'])
        second=obj.enqueue('sketch','film','second')
        self.assertEqual(first['ai_mode'],'normal')
        self.assertEqual(second['ai_mode'],'fast')

    def test_queue_position_reflects_priority_not_enqueue_order(self):
        obj, project, shot = self.fake()
        obj._save_jobs = lambda: None
        video = obj.enqueue('video', project['id'], shot['id'], 'Shot')
        sketch = obj.enqueue('sketch', project['id'], shot['id'], 'Storyboard')
        listed = {job['id']: job for job in obj.list_jobs(project['id'])}
        positions = {key: job.get('queue_position') for key, job in listed.items()}
        self.assertEqual(positions[sketch['id']], 1)
        self.assertEqual(positions[video['id']], 2)
        self.assertEqual(listed[video['id']]['waiting_for'], 'Storyboard')

    def test_draft_prioritizes_first_shot_then_batches_remaining_work_in_both_modes(self):
        for mode in ('normal', 'fast'):
            with self.subTest(mode=mode):
                obj, p, _ = self.fake()
                p.update(ai_mode=mode, review_policy='draft')
                for shot in p['shots']:
                    shot.update(sketch=None, keyframe=None, video=None, sketches=[], takes={'keyframe':[], 'video':[]})
                p['continuity_plan']['of'] = studio.continuity_inputs(p)
                obj._save_jobs = lambda: None
                obj.queue_film('scratch')
                ordered = [obj.queue.get()[2] for _ in range(obj.queue.qsize())]
                ordered = [job for job in ordered if job['kind'] != 'character_reference']
                first = p['shots'][0]['id']
                self.assertEqual([(j['kind'], j['shot']) for j in ordered[:3]],
                                 [('sketch', first), ('keyframe', first), ('video', first)])
                remaining = [j['kind'] for j in ordered[3:] if j['kind'] in ('sketch', 'keyframe', 'video')]
                self.assertEqual(remaining, ['sketch'] * 3 + ['keyframe'] * 3 + ['video'] * 3)

    def test_render_request_timestamp_is_shared_by_video_jobs(self):
        obj, p, _ = self.fake()
        p['review_policy'] = 'draft'
        for shot in p['shots']:
            shot.update(sketch=None, keyframe=None, video=None, sketches=[], takes={'keyframe':[], 'video':[]})
        p['continuity_plan']['of'] = studio.continuity_inputs(p)
        obj._save_jobs = lambda: None
        jobs = obj.queue_film('scratch', render_started_at=1234.0)
        videos = [job for job in jobs if job['kind'] == 'video']
        self.assertEqual(len(videos), 4)
        self.assertTrue(all(job['render_started_at'] == 1234.0 for job in videos))

    def test_nonwide_first_draft_renders_before_world_without_changing_strict_or_wide(self):
        for mode in ('normal', 'fast'):
            for policy, size, defer in (('draft', 'Medium', True), ('draft', 'Wide', False),
                                        ('strict', 'Medium', False)):
                for linked in (False, True):
                    with self.subTest(mode=mode, policy=policy, size=size, linked=linked):
                        obj, p, _ = self.fake()
                        p.update(ai_mode=mode, review_policy=policy, world=None)
                        for shot in p['shots']:
                            shot.update(sketch=None, keyframe=None, video=None, sketches=[],
                                        takes={'keyframe': [], 'video': []})
                        p['shots'][0]['shot_size'] = size
                        if linked:
                            p['shots'][1]['frame_source'] = 'previous_end'
                        p['continuity_plan']['of'] = studio.continuity_inputs(p)
                        obj._save_jobs = lambda: None
                        obj.queue_film('scratch')
                        ordered = [obj.queue.get()[2] for _ in range(obj.queue.qsize())]
                        world = next(i for i, job in enumerate(ordered) if job['kind'] == 'world')
                        video = next(i for i, job in enumerate(ordered)
                                     if job['kind'] == 'video' and job['shot'] == p['shots'][0]['id'])
                        self.assertEqual(world > video, defer)
                        first_video = ordered[video]
                        self.assertEqual(first_video.get('defer_world', False), defer)
                        if not linked:
                            frame = next(job for job in ordered if job['kind'] == 'keyframe' and job['shot'] == p['shots'][0]['id'])
                            self.assertEqual(frame.get('defer_world', False), defer)

    def test_deferred_world_does_not_retroactively_stale_only_its_new_frame_and_video(self):
        p, shot = fixture()
        p['world'] = None
        recipe = shot['takes']['keyframe'][0]['recipe']
        recipe.update(world=None, world_reference=False, world_optional=True,
                      visual=studio.visual_inputs(p, shot))
        shot['takes']['video'][0]['of'] = studio.video_inputs(p, shot)
        self.assertFalse(studio.frame_stale(p, shot))
        self.assertFalse(studio.video_stale(p, shot))
        p['world'] = {'plate': 'new-world.png', 'takes': [{'name': 'new-world.png', 'of': studio.world_of(p)}]}
        self.assertFalse(studio.frame_stale(p, shot))
        self.assertFalse(studio.video_stale(p, shot))
        recipe.pop('world_optional')  # Legacy takes retain their original world dependency.
        self.assertTrue(studio.frame_stale(p, shot))

    def test_deferred_frame_renders_without_plate_but_rechecks_current_policy_and_size(self):
        from unittest.mock import Mock
        for policy, size, optional in (('draft', 'Medium', True), ('draft', 'Wide', False),
                                        ('strict', 'Medium', False)):
            with self.subTest(policy=policy, size=size):
                project, shot = fixture()
                project.update(review_policy=policy, world=None)
                shot.update(shot_size=size, keyframe=None, video=None, takes={'keyframe': [], 'video': []})
                worker = object.__new__(studio.Studio)
                worker.lock = threading.RLock()
                worker.load = Mock(return_value=project)
                worker._require_plan = Mock(return_value=project)
                worker._make_world = Mock(return_value='world.png')
                worker._current_sketch = Mock(return_value='board.png')
                worker._upload = lambda _, name: 'uploaded_' + name
                worker._render_checked = Mock(return_value=([{'filename': 'made.png'}], 9, {}))
                worker._finish_keyframe = Mock()
                worker.comfy = Mock()
                with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
                    worker.path = lambda _: Path(folder)
                    with patch.object(studio, 'cast_stale', return_value=False), patch.object(studio, 'story_stale', return_value=False):
                        worker._run_keyframe({'project': 'scratch', 'shot': shot['id'], 'defer_world': True}, lambda _: None)
                self.assertEqual(worker._make_world.called, not optional)
                recipe = worker._finish_keyframe.call_args.args[5]
                self.assertEqual(recipe.get('world_optional', False), optional)
                self.assertEqual(recipe['world'], None if optional else 'world.png')

    def test_strict_and_already_queued_work_keep_original_dependency_order(self):
        for policy in ('strict', 'draft'):
            with self.subTest(policy=policy):
                obj, p, _ = self.fake()
                p['review_policy'] = policy
                for shot in p['shots']:
                    shot.update(sketch=None, keyframe=None, video=None, sketches=[], takes={'keyframe':[], 'video':[]})
                p['continuity_plan']['of'] = studio.continuity_inputs(p)
                obj._save_jobs = lambda: None
                if policy == 'draft':
                    obj.enqueue('sketch', 'scratch', p['shots'][0]['id'])
                obj.queue_film('scratch')
                ordered = [obj.queue.get()[2] for _ in range(obj.queue.qsize())]
                relevant = [j['kind'] for j in ordered if j['kind'] in ('sketch', 'keyframe', 'video')]
                self.assertEqual(relevant, ['sketch'] * 4 + ['keyframe'] * 4 + ['video'] * 4)

    def test_cast_review_blocks_only_affected_shot_and_assembly(self):
        obj,p,s=self.fake()
        root=self.job('sketch',s['id'])
        obj.jobs=[root,self.job('keyframe',s['id']),self.job('video',s['id']),
                  self.job('sketch','second'),self.job('keyframe','second'),self.job('video','second'),self.job('stitch')]
        root['state']='needs_review'
        obj._block_dependents(root)
        self.assertEqual([j['state'] for j in obj.jobs],['needs_review','blocked','blocked','queued','queued','queued','blocked'])
        self.assertEqual(obj.jobs[1]['blocked_by'],root['id'])

    def test_performance_chain_blocks_transitively_but_stops_at_independent_cut(self):
        obj,p,s=self.fake()
        p['shots'][1]['frame_source']='previous_end'
        p['shots'][2]['transition']='continue'
        root=self.job('video',s['id']);root['state']='failed'
        obj.jobs=[root,self.job('video','second'),self.job('video','third'),self.job('video','fourth')]
        obj._block_dependents(root)
        self.assertEqual([j['state'] for j in obj.jobs],['failed','blocked','blocked','queued'])

    def test_failed_memory_source_blocks_its_return_and_continuations(self):
        obj,p,s=self.fake()
        p['shots'][2]['memory_shot'] = s['id']
        p['shots'][3]['transition'] = 'continue'
        root=self.job('keyframe',s['id']);root['state']='failed'
        obj.jobs=[root,self.job('video','second'),self.job('keyframe','third'),self.job('video','fourth')]
        obj._block_dependents(root)
        self.assertEqual([j['state'] for j in obj.jobs],['failed','queued','blocked','blocked'])

    def test_failed_source_video_does_not_block_independent_memory_return(self):
        obj,p,s=self.fake()
        p['shots'][2]['memory_shot'] = s['id']
        root=self.job('video',s['id']);root['state']='failed'
        obj.jobs=[root,self.job('keyframe','third'),self.job('video','third'),self.job('stitch')]
        obj._block_dependents(root)
        self.assertEqual([j['state'] for j in obj.jobs],['failed','queued','queued','blocked'])

    def test_failed_video_blocks_memory_of_dependent_reframe(self):
        obj,p,s=self.fake()
        p['shots'][1]['frame_source'] = 'previous_end'
        p['shots'][3]['memory_shot'] = 'second'
        root=self.job('video',s['id']);root['state']='failed'
        obj.jobs=[root,self.job('keyframe','second'),self.job('keyframe','fourth')]
        obj._block_dependents(root)
        self.assertEqual([j['state'] for j in obj.jobs],['failed','blocked','blocked'])

    def test_pause_cancels_queued_memory_dependents_and_resume_requeues_them(self):
        obj,p,s=self.fake()
        p['shots'][2]['memory_shot'] = s['id']
        p['shots'][3]['transition'] = 'continue'
        obj.jobs=[self.job('keyframe',s['id']),self.job('video','second'),self.job('keyframe','third'),
                  self.job('video','fourth'),self.job('stitch')]
        obj._save_jobs=lambda: None
        calls=[]
        obj.queue_film=lambda project_id, only=None: calls.append((project_id, only))
        obj.pause_shot('film',s['id'],True)
        self.assertEqual([j['state'] for j in obj.jobs],['cancelled','queued','cancelled','cancelled','cancelled'])
        obj.pause_shot('film',s['id'],False)
        self.assertEqual(calls,[('film',{s['id'],'third','fourth'})])

    def test_retry_uses_current_mode_and_preserves_operation_arguments(self):
        obj,p,s=self.fake();p['ai_mode']='fast'
        old={**self.job('write_story'),'state':'failed','target':'title','count':3,'ai_mode':'normal'}
        obj.jobs=[old]
        new=obj.retry_job(old['id'])
        self.assertEqual((new['target'],new['count'],new['ai_mode']),('title',3,'fast'))
        self.assertNotEqual(new['id'],old['id'])

    def test_fast_readiness_does_not_require_normal_weights(self):
        instance=setup.Setup(type('Client',(),{'server':'test'})())
        instance.status=lambda:{'connected':True,'missing_nodes':[],'ffmpeg':True,'models':[
            {'id':'writer','bytes':1,'group':'writing','name':'normal','installed':False},
            {'id':'writer_fast','bytes':1,'group':'writing_fast','name':'fast','installed':True}]}
        instance.require('write_lead',mode='fast')
        with self.assertRaisesRegex(RuntimeError,'normal'):instance.require('write_lead',mode='normal')

    def test_stop_only_interrupts_selected_film(self):
        obj,p,s=self.fake()
        from unittest.mock import Mock
        obj.comfy=Mock()
        other={**self.job('sketch'),'project':'other','state':'running'}
        own=self.job('sketch')
        obj.jobs=[other,own]
        obj.cancel('film')
        self.assertEqual(own['state'],'cancelled')
        self.assertNotIn('stopped',other)
        obj.comfy.interrupt.assert_not_called()
        obj.cancel('other')
        obj.comfy.interrupt.assert_called_once()

    def test_missing_cast_evidence_retains_candidate_without_passing(self):
        from unittest.mock import Mock
        obj,p,s=self.fake()
        obj.comfy=Mock()
        obj.comfy.wait.return_value={'outputs':{'save':{'images':[{'filename':'candidate.png','type':'output'}]}}}
        files,seed,review=obj._render_checked({'cast_review':{}},7,lambda _:None)
        self.assertEqual(files[0]['filename'],'candidate.png')
        self.assertEqual(review['status'],'needs_review')

    def test_storyboard_scopes_named_group_to_ledger_without_restricting_crowds(self):
        prompt=studio.director.sketch_prompt('A duel','Medium',lead=True,
            others='The Guard (Heavyset soldiers with visors hiding their faces)',expected_cast=2,
            world='A square full of statues and tourists')
        self.assertIn('Exactly 2 visible characters',prompt)
        self.assertNotIn('soldiers',prompt)
        self.assertNotIn('tourists',prompt)
        crowd=studio.director.sketch_prompt('Workers enter','Wide',lead=False,others='Workers (a crowd of workers)')
        self.assertIn('crowd of workers',crowd)
        self.assertNotIn('Exactly ',crowd)

    def test_restart_retains_history_and_marks_inflight_work_interrupted(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime') as folder:
            with patch.object(studio,'PROJECTS',Path(folder)/'projects'),patch.object(threading.Thread,'start'):
                obj=studio.Studio('test')
                obj.jobs=[{**self.job('sketch'),'state':'running'},{**self.job('world'),'state':'done'}]
                obj._save_jobs()
                restored=studio.Studio('test')
                self.assertEqual([j['state'] for j in restored.jobs],['interrupted','done'])
                self.assertTrue(restored.queue.empty())

    def test_flagged_storyboard_requires_explicit_current_director_acceptance(self):
        obj,p,s=self.fake()
        p['review_policy']='strict'
        review={'status':'needs_review','findings':['Cast count differs'],
                'of':studio.sketch_of(s,studio.current_plate(p),p.get('reference'),p)}
        s['sketches']=[{'name':'candidate.png','review':review,'of':review['of']}]
        p['shots'][0]=s
        p['continuity_plan']['of']=studio.continuity_inputs(p)
        with self.assertRaises(ValueError):obj.accept_review('film',s['id'],'sketch','candidate.png','')
        obj.accept_review('film',s['id'],'sketch','candidate.png','Inspected two visible actors')
        self.assertEqual(p['shots'][0]['sketch'],'candidate.png')
        self.assertEqual(p['shots'][0]['quality']['sketch']['automated_status'],'needs_review')

    def test_portrait_guided_storyboard_acceptance_checks_current_identity(self):
        obj,p,s=self.fake()
        p['review_policy']='strict'
        p.update(reference='portrait.png', lead_identity='short curly hair', lead_identity_of='portrait.png')
        snapshot=studio.sketch_of(s,studio.current_plate(p),p['reference'],p)
        snapshot['portrait_identity']={'reference':'portrait.png','description':'short curly hair'}
        review={'status':'needs_review','findings':['Check composition'],'of':snapshot}
        s['sketches']=[{'name':'candidate.png','review':review,'of':snapshot}]
        p['shots'][0]=s
        p['continuity_plan']['of']=studio.continuity_inputs(p)
        p['lead_identity']='different hair'
        with self.assertRaisesRegex(RuntimeError, 'out of date'):
            obj.accept_review('film',s['id'],'sketch','candidate.png','Inspected composition')
        p['lead_identity']='short curly hair'
        obj.accept_review('film',s['id'],'sketch','candidate.png','Inspected composition')
        self.assertEqual(p['shots'][0]['sketch'],'candidate.png')

    def test_earlier_repair_candidate_can_be_inspected_and_recovered(self):
        obj,p,s=self.fake()
        p['continuity_plan']['of']=studio.continuity_inputs(p)
        review={'status':'needs_review','findings':['uncertain'], 'of':studio.visual_inputs(p,s)}
        s['frame_repairs']=[{'name':'earlier.png','phase':'start','review':review}]
        p['shots'][0]=s
        obj.accept_review('film',s['id'],'keyframe','earlier.png','Berry is visibly in the paw')
        self.assertEqual(p['shots'][0]['keyframe'],'earlier.png')
        self.assertTrue(p['shots'][0]['takes']['keyframe'][-1]['recovered_from_repair'])

    def test_storyboards_use_planning_resolution_and_visual_state_language(self):
        graph=studio.graphs.storyboard_graph('two actors',3,'16:9','test',expected_cast=2)
        self.assertEqual((graph['6']['inputs']['width'],graph['6']['inputs']['height']),(1280,704))
        for aspect in studio.graphs.ASPECTS:
            shape=studio.graphs.storyboard_graph('test',3,aspect,'test')['6']['inputs']
            self.assertEqual((shape['width']%32,shape['height']%32),(0,0))
        self.assertEqual(graph['1']['class_type'],'CheckpointLoaderSimple')
        prompt=studio.director.sketch_state_prompt({'Lamp':'unlit','Door':'closed'},['Lamp'])
        self.assertIn('Lamp is unlit',prompt)
        self.assertNotIn('Door',prompt)
        self.assertNotIn('AUTHORITATIVE',prompt)

    def test_fast_video_uses_base_pass_and_preserves_audio_and_ending_guide(self):
        normal=studio.graphs.shot_graph('start.png','test',2,'16:9',4,'test',end_image='end.png')
        fast=studio.graphs.shot_graph('start.png','test',2,'16:9',4,'test',end_image='end.png',performance='fast')
        self.assertEqual((fast['12']['inputs']['width'],fast['12']['inputs']['height']),(640,352))
        self.assertIn('24u',normal)
        self.assertNotIn('24u',fast)
        self.assertEqual(fast['34']['inputs']['samples'],['24',2])
        self.assertEqual(fast['35']['inputs']['samples'],['22',1])
        self.assertEqual(fast['36']['inputs']['audio'],['35',0])
        self.assertEqual(fast['14']['inputs']['frame_idx'],-1)
        with self.assertRaises(ValueError):studio.graphs.shot_graph('a','b',2,'16:9',4,'x',performance='unknown')
