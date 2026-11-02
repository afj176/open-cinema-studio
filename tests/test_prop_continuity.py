import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import studio


class PropTests(unittest.TestCase):
    def test_traced_board_does_not_invalidate_its_source_but_tracks_replacements(self):
        from test_asset_dependencies import fixture
        p,shot=fixture()
        shot['sketch']='trace.png'
        shot['sketches'].append({'name':'trace.png','source_frame':shot['keyframe'],
                                'of':studio.sketch_of(shot,None,None,p)})
        self.assertFalse(studio.sketch_stale(p,shot))
        self.assertFalse(studio.frame_stale(p,shot))
        self.assertFalse(studio.video_stale(p,shot))
        shot['keyframe']='replacement.png'
        self.assertTrue(studio.sketch_stale(p,shot))

    def test_uploaded_opening_requires_a_recorded_review(self):
        import threading
        from unittest.mock import patch
        from test_asset_dependencies import fixture
        p,shot=fixture()
        worker=object.__new__(studio.Studio)
        worker.lock=threading.RLock()
        worker.load=lambda _:p
        worker.save=lambda project:project
        with patch.object(Path,'write_bytes'):
            worker.path=lambda _:Path('scratch-upload')
            worker.set_keyframe(p['id'],shot['id'],'opening.png',b'image')
            take=studio.current_take(shot,'keyframe')
            self.assertFalse(studio.review_passed(take))
            self.assertEqual(take['review']['of'],studio.visual_inputs(p,shot))
            worker.accept_review(p['id'],shot['id'],'keyframe',take['name'],'Inspected the starting pose')
            self.assertTrue(studio.review_passed(take))
            self.assertEqual(take['review']['automated_status'],'needs_review')
            self.assertEqual(take['review']['director_review']['reason'],'Inspected the starting pose')

    def test_film_queue_renders_preceding_performance_before_following_frame(self):
        import copy
        import itertools
        import queue
        import threading
        from test_asset_dependencies import fixture
        p,first=fixture()
        second=copy.deepcopy(first)
        second.update(id='second',frame_source='previous_end',video=None,keyframe=None)
        first.update(video=None,keyframe=None)
        p['shots'].append(second)
        p['continuity_plan']['of']=studio.continuity_inputs(p)
        worker=object.__new__(studio.Studio)
        worker.jobs=[]
        worker.order=itertools.count()
        worker.queue=queue.PriorityQueue()
        worker.lock=threading.RLock()
        worker.load=lambda _:p
        worker.queue_sketches=lambda *_:[]
        worker.queue_film(p['id'])
        ordered=[worker.queue.get()[2] for _ in range(worker.queue.qsize())]
        self.assertEqual([(j['kind'],j['shot']) for j in ordered],
                         [('video',first['id']),('video','second'),('stitch',None)])

    def test_selected_end_frame_invalidates_video_without_invalidating_itself(self):
        from test_asset_dependencies import fixture
        p,shot=fixture()
        shot.update(guide_end=True,endframe={'name':'end-a.png'})
        video=studio.video_inputs(p,shot)
        ending=studio.ending_inputs(p,shot)
        shot['endframe']={'name':'end-b.png'}
        self.assertNotEqual(video,studio.video_inputs(p,shot))
        self.assertEqual(ending,studio.ending_inputs(p,shot))

    def test_planning_failure_preserves_independent_world_job(self):
        import threading
        from unittest.mock import patch
        planner={'kind':'plan_continuity','project':'p','state':'queued'}
        world={'kind':'world','project':'p','state':'queued'}
        worker=object.__new__(studio.Studio)
        worker.jobs=[planner,world]
        worker.lock=threading.RLock()
        tasks=iter([(0,0,planner),(1,1,world)])
        worker.queue=type('Queue',(),{'get':lambda _:next(tasks)})()
        def failed(job,tick):raise ValueError('Review the scene facts')
        completed=[]
        worker._run_plan_continuity=failed
        worker._run_world=lambda job,tick:completed.append('world')
        with patch('studio.traceback.print_exc'),self.assertRaises(StopIteration):worker._worker()
        self.assertEqual(planner['state'],'failed')
        self.assertEqual(world['state'],'done')
        self.assertEqual(completed,['world'])

    def test_object_light_does_not_override_unlit_state(self):
        look='layered paper cutouts, soft warm lantern light, teal and honey colours, warm window light'
        result=studio.director.look_for_state(look,{'Lantern State':'unlit'})
        self.assertNotIn('lantern light',result)
        self.assertIn('teal and honey',result)
        self.assertIn('window light',result)
        self.assertEqual(studio.director.look_for_state(look,{'Lantern State':'lit'}),look)

    def test_prior_take_change_invalidates_following_setup(self):
        from test_asset_dependencies import fixture
        import copy
        p,first=fixture()
        second=copy.deepcopy(first)
        second.update(id='second',frame_source='previous_end')
        p['shots'].append(second)
        old=studio.visual_inputs(p,second)
        first['video']='replacement.mp4'
        self.assertNotEqual(old,studio.visual_inputs(p,second))

    def test_offscreen_cast_is_absent_from_repair_requirements(self):
        shot={'id':'s','start_cast':['Mina'],'end_cast':['Mina'],'start_checks':[],'end_checks':[]}
        p={'cast':'Mina, yellow coat','characters':'Tavi: green coat and red scarf','scene_state':{},'shots':[shot]}
        required=studio.review_requirements(p,shot,'start')
        self.assertNotIn('Tavi',json.dumps(required))
        self.assertIn('Mina',json.dumps(required))

    def test_detailed_graph_bypasses_distillation(self):
        graph=studio.graphs.coverage_graph('test',1,'frame.png','qa','16:9',detailed=True)
        self.assertNotIn('1l',graph)
        self.assertEqual(graph['2']['inputs']['model'],['1',0])
        self.assertEqual(graph['13']['inputs']['steps'],40)
        self.assertEqual(graph['13']['inputs']['cfg'],4)

    def test_prop_state_follows_ledger_and_design_changes_invalidate_images(self):
        shot={'id':'s','prop_id':'prop','state_changes':{'seal':'open'}}
        p={'look':'paper cutouts','scene_state':{'seal':'closed'},'shots':[shot]}
        prop={'id':'prop','name':'Parcel','description':'blue folded paper box','state_key':'seal','variants':{}}
        p['props']=[prop]
        for value in ('open','closed'):
            prop['variants'][value]={'name':value+'.png','of':studio.prop_design(p,prop)}
        self.assertEqual(studio.prop_input(p,shot)['image'],'closed.png')
        self.assertEqual(studio.prop_input(p,shot,'end')['image'],'open.png')
        prop['description']='green box'
        self.assertIsNone(studio.prop_input(p,shot)['image'])
        shot.pop('prop_id')
        self.assertEqual(studio.prop_input(p,shot),{})

    def test_appended_check_values_are_recovered_with_mandatory_review(self):
        plan={'design':'paper box','initial':{'Seal':'closed'},'issues':[],
              'shots':[{'index':1,'changes':{'Seal':'open'},'start_checks':['Seal · closed'],
                        'end_checks':['Seal · open'],'start_cast':[],'end_cast':[]}]}
        result=studio.director.parse_continuity(json.dumps(plan),1)
        self.assertEqual(result['shots'][0]['start_checks'],['Seal'])
        self.assertEqual(len(result['issues']),2)
        plan['shots'][0]['start_checks']=['Unrelated fact']
        with self.assertRaises(ValueError):
            studio.director.parse_continuity(json.dumps(plan),1)

    def test_padded_fact_names_match_normalized_state_without_accepting_unknown_or_duplicate_checks(self):
        plan={'design':'paper box','initial':{' Seal ':'closed'},'issues':[],
              'shots':[{'index':1,'changes':{' Seal ':'open'},'start_checks':[' Seal '],
                        'end_checks':['Seal '],'start_cast':[],'end_cast':[]}]}
        result=studio.director.parse_continuity(json.dumps(plan),1)
        self.assertEqual(result['initial'],{'Seal':'closed'})
        self.assertEqual(result['shots'][0]['changes'],{'Seal':'open'})
        self.assertEqual(result['shots'][0]['start_checks'],['Seal'])
        self.assertEqual(result['shots'][0]['end_checks'],['Seal'])
        self.assertEqual(result['issues'],[])
        for checks in ([' Seal ','Seal'],[' Unrelated fact ']):
            plan['shots'][0]['start_checks']=checks
            with self.subTest(checks=checks),self.assertRaises(ValueError):
                studio.director.parse_continuity(json.dumps(plan),1)
