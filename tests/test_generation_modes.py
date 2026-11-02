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
            {'group':'writing','name':'normal','installed':False},
            {'group':'writing_fast','name':'fast','installed':True}]}
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
        review={'status':'needs_review','findings':['Cast count differs'],
                'of':studio.sketch_of(s,studio.current_plate(p),p.get('reference'),p)}
        s['sketches']=[{'name':'candidate.png','review':review,'of':review['of']}]
        p['shots'][0]=s
        p['continuity_plan']['of']=studio.continuity_inputs(p)
        with self.assertRaises(ValueError):obj.accept_review('film',s['id'],'sketch','candidate.png','')
        obj.accept_review('film',s['id'],'sketch','candidate.png','Inspected two visible actors')
        self.assertEqual(p['shots'][0]['sketch'],'candidate.png')
        self.assertEqual(p['shots'][0]['quality']['sketch']['automated_status'],'needs_review')

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
