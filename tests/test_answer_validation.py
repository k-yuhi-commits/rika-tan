"""Answer grading through the real input UI, using synthetic browser history."""
import unittest

import test_history as history


class AnswerValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        history.HistoryTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        history.HistoryTests.tearDownClass()

    def setUp(self):
        self.harness = history.HistoryTests()
        self.harness.setUp()
        self.harness.open(history.fixture())
        self.page = self.harness.page

    def tearDown(self):
        self.harness.tearDown()

    def grade(self, question, value):
        """question is an existing ID or an explicit synthetic question object."""
        before = self.page.evaluate("""q=>{
            quitSession();
            const item=typeof q==='object'?q:qs.find(x=>String(x.id)===String(q));
            start('input',[item]);
            return s.correct;
        }""", question)
        self.page.locator('#txt').fill(value)
        self.page.get_by_role('button', name='答える', exact=True).click()
        return self.page.evaluate('s.correct') == before + 1

    def cases(self, question, accepted=(), rejected=()):
        for value in accepted:
            with self.subTest(question=question, value=value, expected=True):
                self.assertTrue(self.grade(question, value))
        for value in rejected:
            with self.subTest(question=question, value=value, expected=False):
                self.assertFalse(self.grade(question, value))

    def test_element_symbol_case_is_significant(self):
        self.cases('b039', ['Mg', 'Ｍｇ', ' Mg '], ['mg', 'MG', 'mG', 'M g'])
        self.cases('b009', ['O'], ['o', '0', 'O₂'])
        self.cases('b279', ['Cu'], ['CU', 'cu'])

    def test_cobalt_and_carbon_monoxide_are_distinct(self):
        q=dict(id='synthetic-Co', q='コバルトの元素記号は？', a='Co', c=['CO','C','O'])
        self.cases(q, ['Co'], ['CO', 'co', 'C O'])
        q=dict(id='synthetic-CO', q='一酸化炭素の化学式は？', a='CO', c=['Co','C','O'])
        self.cases(q, ['CO'], ['Co', 'co', 'C O'])

    def test_unit_case_is_significant(self):
        self.cases('b006', ['20J', '20 J'], ['20j', '20Ｊs'])
        self.cases('b096', ['20W'], ['20w', '20mW'])
        self.cases('b002', ['50Hz'], ['50hz', '50HZ'])

    def test_decimal_representation_is_not_the_value(self):
        self.cases('b123', ['0.30A', '0.3A', '.30 A'], ['0.03A', '3A'])
        self.cases('b131', ['10.0g', '10g', '10.00 g'], ['1g', '100g'])

    def test_number_tokens_are_not_joined(self):
        self.cases('b006', rejected=['2 0J', '2\n0J', '２０ ０Ｊ'])
        self.cases('b123', rejected=['0 .30A', '0.3 0A'])

    def test_units_required_unless_question_specifies_them(self):
        self.cases('b006', rejected=['20', '20N', '0.02kJ'])
        self.cases('b122', ['1020', '1020m'], ['1.02km', '1020M'])
        self.cases('b155', ['0.4', '0.4m/s'], ['40cm/s'])

    def test_degree_unit_and_fullwidth_numbers(self):
        self.cases('b001', ['40°', '40度', '４０°', '40'], ['40℃', '4 0°'])

    def test_density_unit_exponents_are_checked(self):
        self.cases('b007', ['3g/cm³', '3g/cm3', '3g/cm^3', '3.0 g / cm³'],
                   ['3g/cm²', '3g/cm', '3g/cm⁻³', '3G/cm³', '3g/c m³'])

    def test_probability_fraction_decimal_percent_are_equivalent(self):
        self.cases('b052', ['1/4', '2/8', '0.25', '25%', '25％', '1 / 4'],
                   ['1/0', '0.25%', '25', '3/4'])
        self.cases('b142', ['50%', '1/2', '0.5'], ['1/4', '0.5%'])

    def test_percentage_scale_is_not_ignored(self):
        self.cases('b008', ['10%', '10.0％'], ['0.1', '10', '100%'])
        self.cases('b128', ['16.7%', '16.7'], ['16.6667%', '17%', '0.167%'])

    def test_chemical_equations_accept_keyboard_notation(self):
        self.cases('b251', ['2H₂＋O₂→2H₂O', '2H2 + O2 -> 2H2O', 'O2+2H2→2H2O'],
                   ['2h2+o2->2h2o', '2H2+O2->H2O', '2H²+O²->2H²O'])
        self.cases('b280', ['C+O2->CO2', 'C ＋ O₂ → CO₂'],
                   ['C+O2->Co2', 'C+O2->C O2', 'C+O2<-CO2'])

    def test_ion_pairs_preserve_charge_and_case(self):
        self.cases('b012', ['Na⁺とCl⁻', 'Na+ と Cl-', 'Cl-とNa+'],
                   ['na+とcl-', 'Na-とCl+', 'Na²⁺とCl²⁻', 'Na₂⁺とCl₂⁻', 'N a+とCl-'])
        self.cases('b133', ['OH-とH+', 'H+とOH-'], ['H+とOh-', 'H+とO H-'])

    def test_superscripts_are_not_globally_folded_to_subscripts(self):
        q=dict(id='synthetic-water', q='水の化学式は？', a='H₂O', c=['HO','H²O','O'])
        self.cases(q, ['H₂O'], ['H²O', 'h₂o'])

    def test_genotype_and_named_labels_preserve_case(self):
        self.cases('b292', ['すべてAa', '全てAa', 'すべて Aa'], ['すべてaa', 'すべてAA', 'すべて A a'])
        self.cases('b202', ['Aまたはa', 'aまたはA', 'A または a'], ['aまたはa', 'AまたはA'])
        self.cases('b242', ['音B', '音 B'], ['音b', '音A'])

    def test_japanese_spaces_and_kana_do_not_change_terms(self):
        self.cases(1, [' イオン ', 'いおん', 'ｲｵﾝ', 'イ オン'], ['陰イオン'])
        self.cases('b099', ['マグネシウム', 'まぐねしうむ', 'ﾏｸﾞﾈｼｳﾑ'], ['マンガン'])
        self.cases('b138', ['アミラーゼ', 'あみらーぜ'], ['リパーゼ'])

    def test_reviewed_japanese_aliases(self):
        self.cases('b080', ['せきずい', '脊髄'], ['脳', '大脳'])
        self.cases('b200', ['脊髄', 'せきずい'], ['延髄'])
        self.cases('b076', ['ヨウ素液', 'ヨウ素溶液'], ['BTB溶液'])

    def test_integer_coefficient_and_signed_charge(self):
        self.cases('b100', ['1', '１'], ['1.0', '1/1', '1個', '−1'])
        self.cases('b252', ['−1', '-1', '－１'], ['+1', '1', '-1.0', '− 1'])

    def test_near_values_are_not_accepted_by_float_tolerance(self):
        self.cases('b123', rejected=['0.30000000000000004A', 'NaNA', 'InfinityA', '3e-1A'])
        self.cases('b007', rejected=['2.9999999999999999g/cm³'])

    def test_unreviewed_question_has_conservative_fallback(self):
        q=dict(id='synthetic-new', q='合成テスト', a='20A', c=['2A','20a','0A'])
        self.cases(q, ['20A'], ['20a', '20.0A', '2 0A', '20'])
        # An ID reused with a different canonical answer must not inherit its old policy.
        q['id']='b039'
        self.cases(q, ['20A'], ['20a', '20.0A', '2 0A', '20'])

    def test_explicit_accepted_answers_do_not_relax_case(self):
        q=dict(id='synthetic-alias', q='合成テスト', a='CO', c=['Co','C','O'],
               acceptedAnswers=['一酸化炭素'])
        self.cases(q, ['CO', '一酸化炭素'], ['Co', 'co', '二酸化炭素'])

    def test_blank_and_duplicate_submission_do_not_add_answers(self):
        self.page.evaluate("start('input',[qs[0]])")
        before=self.page.evaluate('s.total')
        self.page.locator('#txt').fill('　 ')
        self.page.get_by_role('button',name='答える',exact=True).click()
        self.assertEqual(self.page.evaluate('s.total'),before)
        self.page.locator('#txt').fill('イオン')
        self.page.get_by_role('button',name='答える',exact=True).click()
        self.page.evaluate('submitInput()')
        self.assertEqual(self.page.evaluate('s.total'),before+1)

    def test_enter_key_uses_the_same_grading(self):
        self.page.evaluate("start('input',[qs.find(q=>q.id==='b039')])")
        before=self.page.evaluate('s.correct')
        self.page.locator('#txt').fill('mg');self.page.locator('#txt').press('Enter')
        self.assertEqual(self.page.evaluate('s.correct'),before)

    def test_ime_confirmation_enter_does_not_submit(self):
        self.page.evaluate("start('input',[qs[0]])")
        self.page.locator('#txt').fill('いおん')
        before=self.page.evaluate('s.total')
        self.page.locator('#txt').dispatch_event('keydown',dict(key='Enter',isComposing=True,bubbles=True))
        self.assertEqual(self.page.evaluate('s.total'),before)
        self.page.locator('#txt').dispatch_event('keydown',dict(key='Enter',keyCode=229,bubbles=True))
        self.assertEqual(self.page.evaluate('s.total'),before)
        self.page.locator('#txt').press('Enter')
        self.assertEqual(self.page.evaluate('s.total'),before+1)

    def test_every_existing_input_distractor_is_rejected(self):
        result=self.page.evaluate("""()=>{
            let count=0;const bad=[];
            for(const q of qs.filter(q=>q.type!=='exam'&&String(q.a).length<=24)){
                for(const wrong of q.c.filter(c=>c!==q.a)){
                    quitSession();start('input',[q]);const before=s.correct;
                    document.getElementById('txt').value=wrong;submitInput();count++;
                    if(s.correct!==before)bad.push({id:q.id,wrong});
                }
            }
            return {count,bad};
        }""")
        self.assertEqual(result,dict(count=933,bad=[]))

    def test_every_canonical_input_answer_still_passes(self):
        result=self.page.evaluate("""()=>{
            const input=qs.filter(q=>q.type!=='exam'&&String(q.a).length<=24);
            const bad=[];
            for(const q of input){
                quitSession();start('input',[q]);const before=s.correct;
                document.getElementById('txt').value=q.a;submitInput();
                if(s.correct!==before+1)bad.push(q.id);
            }
            return {count:input.length,bad};
        }""")
        self.assertEqual(result,dict(count=311,bad=[]))


if __name__=='__main__':
    unittest.main()
