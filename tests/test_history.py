"""Browser regressions; only synthetic data on an intercepted, offline origin."""
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = "17c1acd7c27c6cedc58e8d2970f7544149d74cd6"
KEY = "rikaTangoV2"
LEGACY = ["rika-tango-v4.2.html", "rika-tango-v4.7.html",
          "rika-tango-v5.6.html", "rika-tango-v6.2.html"]


def source(name, ref=None):
    if ref:
        return subprocess.check_output(["git", "show", f"{ref}:{name}"], cwd=ROOT).decode()
    return (ROOT / name).read_text()


def fixture(version=92):
    return dict(schemaVersion=version, exp=42, life=4, streak=6, last="2026/10/28",
                todaydate="2026/10/29", today=0, total=7, correct=4,
                mastery={"イオン": 2, "id:1": 2, "id:retired": 1},
                mistakes={"1": dict(id=1, count=2, last="2026/10/28",
                                   history=[], streak=1, overcome=False)},
                reviews={"1": dict(stage=2, due=1900000000000)}, tests=[],
                confidence={}, q={"1": dict(n=3, correct=1, wrong=2)}, sessionLen=5,
                customLegacyField={"keep": True})


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        executable = os.environ.get("CHROMIUM_PATH") or shutil.which("chromium")
        cls.browser = cls.pw.chromium.launch(
            **({"executable_path": executable} if executable else {}),
            headless=True, args=["--no-sandbox"])
        ref = os.environ.get("RIKA_SOURCE_REF")
        cls.files = {n: source(n, ref) for n in ["index.html", *LEGACY]}

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context(timezone_id="Asia/Tokyo")
        def route(r):
            name = r.request.url.split("/")[-1].split("?")[0]
            r.fulfill(status=200, content_type="text/html", body=self.files.get(name, ""))
        self.context.route("**/*", route)
        self.page = self.context.new_page()
        self.page.clock.install(time=datetime(2026, 10, 29, tzinfo=timezone.utc))
        self.accept_dialog = lambda d: d.accept()
        self.page.on("dialog", self.accept_dialog)

    def tearDown(self):
        self.context.close()

    def open(self, data=None, name="index.html", extra=None):
        # Seed once on an empty document; reloads must read the app's saved data.
        self.page.goto("https://history.invalid/empty")
        if data is not None:
            self.page.evaluate("([k,v])=>localStorage.setItem(k,v)",
                               [KEY, data if isinstance(data, str) else json.dumps(data)])
        for k, v in (extra or {}).items():
            self.page.evaluate("([k,v])=>localStorage.setItem(k,v)", [k, v])
        self.page.goto("https://history.invalid/" + name)

    def disk(self):
        return self.page.evaluate("JSON.parse(localStorage.getItem('rikaTangoV2'))")

    def upload(self, data):
        self.page.locator("input[type=file]").set_input_files(dict(
            name="synthetic.json", mimeType="application/json",
            buffer=json.dumps(data).encode()))
        self.page.wait_for_timeout(50)

    def test_current_roundtrip_preserves_history_and_unknown_ids(self):
        x = fixture(); self.open(x); self.page.reload()
        for k in ["total", "correct", "streak", "last", "mastery", "reviews", "q", "customLegacyField"]:
            self.assertEqual(self.disk()[k], x[k])

    def test_all_legacy_formats_migrate_without_losing_term_mastery(self):
        for v in [42, 47, 56, 62]:
            with self.subTest(version=v):
                self.page.evaluate("localStorage.clear()") if v != 42 else None
                x = fixture(v); x["mastery"].pop("id:1")
                self.open(x)
                y = self.disk()
                self.assertEqual(y["schemaVersion"], 92)
                self.assertEqual(y["mastery"]["id:1"], 2)
                self.assertEqual(y["mastery"]["イオン"], 2)
                self.assertEqual(y["streak"], x["streak"])
                self.assertEqual(y["total"], x["total"])

    def test_legacy_id_migration_keeps_both_records(self):
        x = fixture(62); x["q"]["e135"] = dict(n=3, correct=2, wrong=1)
        self.open(x); y = self.disk()
        self.assertEqual(y["q"]["e141"], x["q"]["e135"])
        self.assertEqual(y["q"]["e135"], x["q"]["e135"])

    def test_legacy_boss_mastery_and_ambiguous_keys_are_preserved(self):
        x=fixture(56);x['mastery'].update({'ダニエル電池':2,'undefined':3})
        self.open(x);y=self.disk()
        self.assertEqual(y['mastery']['id:101'],2)
        self.assertEqual(y['mastery']['undefined'],3)
        self.assertNotIn('id:e01',y['mastery'])

    def test_legacy_urls_cannot_downgrade_current_history(self):
        self.open(fixture()); before = self.disk()
        for name in LEGACY:
            with self.subTest(name=name):
                self.page.goto("https://history.invalid/" + name)
                self.page.wait_for_url("**/index.html", timeout=1000)
                self.assertEqual(self.disk(), before)

    def test_legacy_url_migrates_existing_legacy_data(self):
        for name in LEGACY:
            with self.subTest(name=name):
                self.open(fixture(56),name=name)
                self.page.wait_for_url('**/index.html',timeout=1000)
                self.assertEqual(self.disk()['schemaVersion'],92)
                self.assertEqual(self.disk()['total'],7)
                self.assertEqual(self.disk()['streak'],6)

    def test_invalid_json_is_not_overwritten(self):
        self.open('{"broken":')
        self.assertEqual(self.page.evaluate("localStorage.getItem('rikaTangoV2')"), '{"broken":')

    def test_invalid_nested_saved_data_is_not_overwritten(self):
        x = fixture(); x["q"]["1"] = None; original = json.dumps(x)
        self.open(original)
        self.assertEqual(self.page.evaluate("localStorage.getItem('rikaTangoV2')"), original)

    def test_future_data_remains_byte_identical(self):
        x = fixture(100); original = json.dumps(x); self.open(original)
        self.page.evaluate("start('choice');test('general');persist()")
        self.assertEqual(self.page.evaluate("localStorage.getItem('rikaTangoV2')"), original)

    def test_future_export_preserves_uninterpreted_fields(self):
        x=fixture(100);x['mastery'].pop('id:1');self.open(x)
        self.page.evaluate("window.exported=null;URL.createObjectURL=b=>{window.exported=b;return 'blob:synthetic'};HTMLAnchorElement.prototype.click=function(){};exportData()")
        self.assertEqual(self.page.evaluate('exported.text().then(JSON.parse)'),x)

    def test_corrupt_storage_can_be_recovered_with_valid_import(self):
        broken='{"broken":';self.open(broken);self.upload(fixture())
        self.assertEqual(self.disk()['total'],7)
        self.assertEqual(self.page.evaluate("localStorage.getItem(KEY+'-preimport-backup')"),broken)

    def test_upgrade_backup_is_exact_and_not_replaced(self):
        original=json.dumps(fixture(56));self.open(original)
        self.assertEqual(self.page.evaluate("localStorage.getItem(KEY+'-preupgrade-v92')"),original)
        self.page.reload()
        self.assertEqual(self.page.evaluate("localStorage.getItem(KEY+'-preupgrade-v92')"),original)

    def test_upgrade_backup_failure_does_not_overwrite_legacy(self):
        original=json.dumps(fixture(56))
        self.page.add_init_script("""(()=>{const set=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k.endsWith('-preupgrade-v92'))throw new DOMException('full','QuotaExceededError');return set.call(this,k,v)}})()""")
        self.open(original)
        self.assertEqual(self.page.evaluate("localStorage.getItem(KEY)"),original)

    def test_prototype_keys_and_invalid_scores_are_rejected(self):
        self.open(fixture());old=self.disk()
        for field in [{'__proto__':{'polluted':True}},{'tests':[{'date':'x','score':101}]},
                      {'mastery':{'id:1':4}},{'q':{'1':{'n':'7'}}}]:
            with self.subTest(field=field):
                x=fixture();x.update(field);self.upload(x)
                self.assertEqual(self.disk(),old)

    def test_cancel_import_leaves_history_and_backup_unchanged(self):
        self.open(fixture());old=self.disk()
        self.page.remove_listener('dialog',self.accept_dialog);self.page.on('dialog',lambda d:d.dismiss())
        x=fixture();x['exp']=999;self.upload(x)
        self.assertEqual(self.disk(),old)
        self.assertIsNone(self.page.evaluate("localStorage.getItem(KEY+'-preimport-backup')"))

    def test_invalid_import_is_atomic(self):
        self.open(fixture()); before = self.disk()
        x = fixture(); x.update(exp=123, tests=[None]); self.upload(x)
        self.assertEqual(self.disk(), before)
        self.assertEqual(self.page.evaluate("s.exp"), before["exp"])

    def test_import_restore_and_redo(self):
        self.open(fixture()); old = self.disk(); x = fixture(56); x.update(exp=99,total=20)
        self.upload(x); self.assertEqual(self.disk()["exp"], 99)
        self.page.evaluate("restorePreImport()")
        self.assertEqual(self.disk(), old)
        self.page.evaluate("restorePreImport()")
        self.assertEqual(self.disk()["exp"], 99)

    def test_invalid_restore_is_atomic(self):
        self.open(fixture(), extra={KEY+"-preimport-backup": json.dumps(dict(exp=1,mastery={},tests=[None]))})
        old = self.disk(); self.page.evaluate("restorePreImport()")
        self.assertEqual(self.disk(), old)
        self.assertEqual(self.page.evaluate("s.exp"), old["exp"])

    def test_import_backup_failure_leaves_state_unchanged(self):
        self.open(fixture()); old = self.disk()
        self.page.evaluate("(()=>{Storage.prototype.setItem=function(){throw new DOMException('full','QuotaExceededError')}})()")
        x=fixture();x["exp"]=999;self.upload(x)
        self.assertEqual(self.page.evaluate("s.exp"),old["exp"])
        self.assertEqual(self.disk(),old)

    def test_normal_save_failure_preserves_disk_and_exportable_memory(self):
        self.open(fixture());old=self.disk()
        self.page.evaluate("(()=>{Storage.prototype.setItem=function(){throw new DOMException('full','QuotaExceededError')}})()")
        self.page.evaluate('s.total+=1;save()')
        self.assertEqual(self.disk(),old)
        self.assertEqual(self.page.evaluate('s.total'),8)
        self.assertTrue(self.page.locator('#storageWarning').is_visible())

    def test_storage_access_denial_shows_warning_without_crash(self):
        errors=[];self.page.on('pageerror',lambda e:errors.append(str(e)))
        self.page.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw new DOMException('denied','SecurityError')}})")
        self.open()
        self.assertTrue(self.page.locator('#storageWarning').is_visible())
        self.assertEqual(errors,[])

    def test_failed_main_write_leaves_import_state_unchanged(self):
        backup=json.dumps(fixture(56))
        self.open(fixture(),extra={KEY+'-preimport-backup':backup}); old = self.disk()
        self.page.evaluate("""(()=>{const set=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k==='rikaTangoV2')throw new DOMException('full','QuotaExceededError');return set.call(this,k,v)}})()""")
        x=fixture();x["exp"]=999;self.upload(x)
        self.assertEqual(self.page.evaluate("s.exp"),old["exp"])
        self.assertEqual(self.disk(),old)
        self.assertEqual(self.page.evaluate("localStorage.getItem(KEY+'-preimport-backup')"),backup)

    def test_export_matches_saved_history(self):
        self.open(fixture()); old = self.disk()
        self.page.evaluate("window.exported=null;URL.createObjectURL=b=>{window.exported=b;return 'blob:synthetic'};HTMLAnchorElement.prototype.click=function(){};exportData()")
        self.assertEqual(self.page.evaluate("exported.text().then(JSON.parse)"),old)

    def test_stale_tab_does_not_overwrite_new_history(self):
        self.open(fixture()); other=self.context.new_page()
        other.goto("https://history.invalid/index.html")
        self.page.evaluate("s.total+=1;save()")
        other.evaluate("s.exp+=5;save()")
        self.assertEqual(self.disk()["total"],8)

    def test_unrated_mastery_is_not_committed_on_reload(self):
        self.open(fixture()); self.page.evaluate("start('choice',[qs[1]]);answer(true,qs[1].a)")
        self.page.reload()
        self.assertEqual(self.page.evaluate("s.mastery['id:2']||0"),0)

    def test_confirmed_mastery_is_persisted(self):
        self.open(fixture());self.page.evaluate("start('choice',[qs[1]]);answer(true,qs[1].a);sess.reasonExplanationViewed=true;rateReason(true)")
        self.page.reload();self.assertEqual(self.page.evaluate("s.mastery['id:2']"),1)

    def test_unconfirmed_overcoming_does_not_survive_reload(self):
        x=fixture();x['mistakes']['1']['streak']=2;self.open(x)
        self.page.evaluate("start('choice',[qs[0]]);answer(true,qs[0].a)")
        self.page.reload()
        self.assertFalse(self.disk()['mistakes']['1']['overcome'])
        self.assertEqual(self.disk()['mistakes']['1']['streak'],2)

    def test_three_separate_days_confirm_mastery_and_overcoming(self):
        self.open(fixture())
        for day in range(3):
            self.page.evaluate("start('choice',[qs[0]]);answer(true,qs[0].a);sess.reasonExplanationViewed=true;rateReason(true);quitSession()")
            self.page.clock.fast_forward(24*60*60*1000)
        self.page.reload()
        self.assertEqual(self.disk()['mastery']['id:1'],3)
        self.assertTrue(self.disk()['mistakes']['1']['overcome'])
        self.assertEqual(self.disk()['streak'],9)

    def test_single_day_does_not_repeat_mastery_or_streak_credit(self):
        self.open(fixture())
        for _ in range(2):
            self.page.evaluate("start('choice',[qs[1]]);answer(true,qs[1].a);sess.reasonExplanationViewed=true;rateReason(true);quitSession()")
        self.assertEqual(self.disk()['mastery']['id:2'],1)
        self.assertEqual(self.disk()['streak'],7)

    def test_imported_test_date_is_text(self):
        self.open(fixture());x=fixture();x["tests"]=[dict(date='<img src=x onerror="window.injected=1">',score=80)]
        self.upload(x);self.page.evaluate("show('stats')");self.page.wait_for_timeout(50)
        self.assertFalse(self.page.evaluate("!!window.injected"))

    def test_learning_modes_and_streak_survive(self):
        self.open(fixture())
        self.page.evaluate("start('input',[qs[0]])")
        self.page.locator('#txt').fill('イオン');self.page.get_by_role('button',name='答える',exact=True).click()
        self.assertEqual(self.page.evaluate('s.total'),8)
        self.assertEqual(self.page.evaluate('s.streak'),7)
        self.page.evaluate("quitSession();start('weak')")
        self.assertIn(1,self.page.evaluate('sess.list.map(q=>q.id)'))
        self.page.evaluate("quitSession();start('choice',[qs[0]])")
        self.assertEqual(self.page.locator('.choice').count(),4)

    def test_all_question_data_unchanged(self):
        def bank_hash(html):
            start=html.index('const qs=');end=html.index("const KEY=",start)
            return hashlib.sha256(html[start:end].encode()).hexdigest()
        for name in ["index.html",*LEGACY]:
            with self.subTest(name=name):
                self.assertEqual(bank_hash(self.files[name]),bank_hash(source(name,BASE)))
        self.open();self.assertEqual(self.page.evaluate('[qs.length,bosses.length]'),[740,4])


if __name__ == '__main__':
    unittest.main()
