"""Review regressions use synthetic history; no live learner data."""
import unittest
import hashlib
import test_history as history

BASE='aec24c7'

class SmartReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): history.HistoryTests.setUpClass()
    @classmethod
    def tearDownClass(cls): history.HistoryTests.tearDownClass()
    def setUp(self):
        self.h=history.HistoryTests();self.h.setUp();self.h.open(history.fixture());self.page=self.h.page
        self.page.evaluate("s.mistakes={};s.reviews={};s.confidence={};s.q={};s.mastery={}")
    def tearDown(self): self.h.tearDown()
    def ids(self):return self.page.evaluate('sess.list.map(q=>q.id)')
    def test_boss_mistake_can_be_reviewed(self):
        self.page.evaluate("s.mistakes[101]={id:101,count:2,streak:0,overcome:false};start('weak')")
        self.assertEqual(self.ids(),[101])
    def test_due_boss_can_be_scheduled(self):
        self.page.evaluate("s.reviews[101]={stage:0,due:Date.now()-1000};start('scheduled')")
        self.assertEqual(self.ids(),[101])
    def test_due_is_not_displaced_by_fresh_target(self):
        ids=self.page.evaluate("s.reviews[1]={stage:0,due:Date.now()-1000};s.q[1]={n:1,wrong:0,correct:1,lastSeen:Date.now()-1000};pickTargetedList([qs[0],qs[1]],1).map(q=>q.id)")
        self.assertEqual(ids,[1])
    def test_mixed_keeps_required_reviews_before_new_work(self):
        ids=self.page.evaluate("for(const q of qs.slice(0,5))s.reviews[q.id]={stage:0,due:Date.now()-1000};learningMix(5).map(q=>q.id)")
        self.assertEqual(set(ids),{1,2,3,4,5})
    def test_recent_practice_is_rotated_among_needed_questions(self):
        self.page.evaluate("s.mistakes[1]={id:1,count:100,streak:0,overcome:false};s.mistakes[2]={id:2,count:1,streak:0,overcome:false};s.q[1]={n:100,correct:0,wrong:100,lastSeen:Date.now()};start('weak')")
        self.assertEqual(self.ids()[0],2)
    def test_due_question_beats_old_error_total(self):
        self.page.evaluate("s.mistakes[1]={id:1,count:100,streak:0,overcome:false};s.mistakes[2]={id:2,count:1,streak:0,overcome:false};s.reviews[2]={stage:0,due:Date.now()-3600000};start('weak')")
        self.assertEqual(self.ids()[0],2)
    def test_confirmed_recovery_reduces_priority(self):
        self.page.evaluate("s.mistakes[1]={id:1,count:10,streak:2,overcome:false};s.mistakes[2]={id:2,count:3,streak:0,overcome:false};start('weak')")
        self.assertEqual(self.ids()[0],2)
    def test_unrated_and_slow_answers_are_review_candidates(self):
        self.page.evaluate("s.confidence[1]='unrated';s.confidence[2]='slow';start('weak')")
        self.assertEqual(set(self.ids()),{1,2})
    def test_weak_test_does_not_add_unrelated_questions(self):
        self.page.evaluate("s.mistakes[1]={id:1,count:2,streak:0,overcome:false};test('weak')")
        self.assertEqual(self.ids(),[1])
    def test_weak_test_without_candidates_does_not_start_general_test(self):
        self.page.evaluate("test('weak')")
        self.assertTrue(self.page.locator('#quiz').evaluate("e=>e.classList.contains('hidden')"))
    def test_single_error_is_not_immediately_repeated(self):
        self.page.evaluate("start('choice',[qs[0]]);answer(false,'wrong');nextQ()")
        self.assertTrue(self.page.locator('#quiz').evaluate("e=>e.classList.contains('hidden')"))
        self.assertGreater(self.page.evaluate('s.reviews[1].due'),self.page.evaluate('Date.now()'))
    def test_last_error_is_deferred_if_next_question_is_identical(self):
        self.page.evaluate("start('choice',[qs[0],qs[1]]);sess.list=[qs[0],qs[1]];renderQ();answer(true,qs[0].a);nextQ();answer(false,'wrong');nextQ()")
        self.assertTrue(self.page.locator('#quiz').evaluate("e=>e.classList.contains('hidden')"))
    def test_spaced_in_set_retry_is_retained_and_does_not_raise_mastery(self):
        self.page.evaluate("start('choice',[qs[0],qs[1]]);sess.list=[qs[0],qs[1]];renderQ();answer(false,'wrong');nextQ();answer(true,qs[1].a);nextQ()")
        self.assertEqual(self.page.evaluate('sess.list[sess.i].id'),1)
        self.page.evaluate("answer(true,qs[0].a);sess.reasonExplanationViewed=true;rateReason(true)")
        self.assertEqual(self.page.evaluate("s.mastery['id:1']||0"),0)
    def test_one_success_does_not_master_unresolved_repeated_errors(self):
        self.page.evaluate("s.mastery['id:1']=2;s.mistakes[1]={id:1,count:10,streak:0,history:[],overcome:false};start('weak',[qs[0]]);answer(true,qs[0].a);sess.reasonExplanationViewed=true;rateReason(true)")
        self.assertLess(self.h.disk()['mastery']['id:1'],3)
        self.assertFalse(self.h.disk()['mistakes']['1']['overcome'])
    def test_reason_no_preserves_prior_mastery_and_recovery(self):
        self.page.evaluate("s.mastery['id:1']=2;s.mistakes[1]={id:1,count:10,streak:2,history:[],overcome:false};start('weak',[qs[0]]);answer(true,qs[0].a);rateReason(false)")
        self.assertEqual(self.h.disk()['mastery']['id:1'],2)
        self.assertEqual(self.h.disk()['mistakes']['1']['streak'],2)
        self.assertFalse(self.h.disk()['mistakes']['1']['overcome'])
    def test_ranking_does_not_mutate_existing_history(self):
        self.page.evaluate("s.mistakes[1]={id:1,count:2,streak:0,overcome:false};save()")
        old=self.h.disk()
        self.page.evaluate("learningMix(5);pickTargetedList(qs.slice(0,8),3)")
        self.assertEqual(self.h.disk(),old)
    def test_existing_mastery_is_not_reduced_by_a_correct_answer(self):
        self.page.evaluate("s.mastery['id:1']=3;s.mistakes[1]={id:1,count:10,streak:0,history:[],overcome:false};start('weak',[qs[0]]);answer(true,qs[0].a);sess.reasonExplanationViewed=true;rateReason(true)")
        self.assertEqual(self.h.disk()['mastery']['id:1'],3)
    def test_changing_mode_settles_unconfirmed_reason(self):
        self.page.evaluate("start('choice',[qs[0]]);answer(true,qs[0].a);start('choice',[qs[1]])")
        self.assertEqual(self.h.disk()['mastery'].get('id:1',0),0)
    def test_starting_test_settles_unconfirmed_reason(self):
        self.page.evaluate("start('choice',[qs[0]]);answer(true,qs[0].a);test('general')")
        self.assertEqual(self.h.disk()['mastery'].get('id:1',0),0)
    def test_due_boss_count_is_visible_on_home(self):
        self.page.evaluate("s.reviews[101]={stage:0,due:Date.now()-1000};refresh()")
        self.assertEqual(self.page.locator('#duecount').inner_text(),'1')
    def test_cooldown_expires_and_does_not_remove_questions(self):
        self.page.evaluate("s.mistakes[1]={id:1,count:6,streak:0,overcome:false};s.mistakes[2]={id:2,count:1,streak:0,overcome:false};s.q[1]={n:6,correct:0,wrong:6,lastSeen:Date.now()}")
        self.page.clock.fast_forward(5*60*1000+1)
        self.page.evaluate("start('weak')")
        self.assertEqual(self.ids(),[1,2])
    def test_targeted_review_stays_unique_and_in_scope(self):
        ids=self.page.evaluate("pickTargetedList([qs[0],qs[0],qs[1]],10).map(q=>q.id)")
        self.assertEqual(set(ids),{1,2});self.assertEqual(len(ids),2)
    def test_same_day_repeat_does_not_overcome_mistake(self):
        self.page.evaluate("s.mistakes[1]={id:1,count:5,streak:0,history:[],overcome:false}")
        for _ in range(4):
            self.page.evaluate("start('weak',[qs[0]]);answer(true,qs[0].a);sess.reasonExplanationViewed=true;rateReason(true);quitSession()")
        self.assertEqual(self.h.disk()['mistakes']['1']['streak'],1)
        self.assertFalse(self.h.disk()['mistakes']['1']['overcome'])
    def test_reason_no_at_mastery_cap_allows_later_confirmed_recovery(self):
        self.page.evaluate("s.mastery['id:1']=2;s.mistakes[1]={id:1,count:10,streak:0,history:[],overcome:false};start('weak',[qs[0]]);answer(true,qs[0].a);rateReason(false);quitSession();start('weak',[qs[0]]);answer(true,qs[0].a);sess.reasonExplanationViewed=true;rateReason(true)")
        self.assertEqual(self.h.disk()['mistakes']['1']['streak'],1)
    def test_answer_rules_are_byte_identical(self):
        def rules(t):return t[t.index('// Input grading rules'):t.index('const KISO300_TITLES=')]
        self.assertEqual(hashlib.sha256(rules(history.source('index.html')).encode()).digest(),hashlib.sha256(rules(history.source('index.html',BASE)).encode()).digest())

if __name__=='__main__':unittest.main()
