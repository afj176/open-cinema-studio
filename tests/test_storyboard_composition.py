import unittest

from test_asset_dependencies import studio


class StoryboardCompositionTests(unittest.TestCase):
    def test_multiple_participants_share_an_uninterrupted_scene(self):
        prompt=studio.director.sketch_prompt(
            'The guard attacks and the lead deflects the spear', 'Medium', lead=True,
            others='Guard (one armored guard)', expected_cast=2,
            start_frame='Side view: the guard aims a spear toward the lead')
        self.assertIn('One continuous shot in one shared setting',prompt)
        self.assertIn('side view: the guard aims a spear toward the lead',prompt.lower())
        self.assertIn('not its later outcome',prompt)
        self.assertIn('split screen',studio.director.SKETCH_NEGATIVE)

    def test_single_subject_does_not_invent_a_second_participant(self):
        prompt=studio.director.sketch_prompt('The lead crosses the room','Wide',lead=True)
        self.assertNotIn('participants occupy the same space',prompt)
        self.assertIn('Exactly 1 visible characters',prompt)


if __name__ == '__main__':
    unittest.main()
