"""Offline security and quality-gate tests. Never calls GitHub or a live site."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock
import yaml

from scripts import automation_policy as policy
from scripts import prepare_pages_smoke as pages
from scripts import pages_smoke
from scripts import quality_gate

ROOT = Path(__file__).resolve().parents[1]
NOTE = 'docs/maintenance/editorial-notes.txt'
COMMIT = 'a'*40


class PolicyTests(unittest.TestCase):
    def change(self, **kwargs):
        return dict(dict(path=NOTE,status='M',mode='100644',content='編集メモ\n'.encode()),**kwargs)
    def test_only_exact_note_is_low_risk_but_never_merge_authorized(self):
        r=policy.classify([self.change()])
        self.assertTrue(r['low_risk_candidate']);self.assertFalse(r['auto_merge_authorized'])
        self.assertTrue(r['human_approval_required']);self.assertEqual(r['merge_state'],'STOPPED')
    def test_all_code_settings_and_tests_require_human_review(self):
        for path in ['index.html','new.js','data.json','requirements-test.txt',
                     '.github/workflows/history-tests.yml','.github/CODEOWNERS',
                     'scripts/automation_policy.py','quality/baseline.json',
                     'tests/test_history.py','README.md','docs/maintenance/other.txt',
                     '../'+NOTE,NOTE.upper(),NOTE+'/suffix']:
            with self.subTest(path=path):
                self.assertFalse(policy.classify([self.change(path=path)])['low_risk_candidate'])
    def test_mixed_note_and_code_cannot_be_eligible(self):
        self.assertFalse(policy.classify([self.change(),self.change(path='index.html')])['low_risk_candidate'])
    def test_add_delete_rename_copy_and_type_changes_are_not_allowed(self):
        for status in ['A','D','R100','C100','T','U']:
            with self.subTest(status=status):
                self.assertFalse(policy.classify([self.change(status=status)])['low_risk_candidate'])
    def test_symlinks_executables_and_submodules_are_not_allowed(self):
        for mode in ['120000','100755','160000',None]:
            self.assertFalse(policy.classify([self.change(mode=mode)])['low_risk_candidate'])
    def test_binary_oversized_links_and_active_content_are_not_allowed(self):
        for data in [b'\xff',b'x'*8193,b'\0',b'https://example.com',b'<script>',b'`cmd`',b'$(cmd)',b'data:text/html,x']:
            with self.subTest(data=data[:40]):
                self.assertFalse(policy.classify([self.change(content=data)])['low_risk_candidate'])
    def test_empty_or_unknown_change_set_cannot_authorize_merge(self):
        self.assertFalse(policy.classify([])['low_risk_candidate'])
        self.assertFalse(policy.classify([])['auto_merge_authorized'])
    def test_inspection_requires_full_existing_shas(self):
        for base in ['main','HEAD','a'*39,'--help','a'*40]:
            with self.subTest(base=base):
                with self.assertRaises((ValueError,subprocess.CalledProcessError)):
                    policy.inspect_changes(ROOT,base,'b'*40)
    def test_real_git_diff_and_rename_are_checked_without_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def git(*args):return subprocess.check_output(['git','-C',tmp,*args],stderr=subprocess.DEVNULL).decode().strip()
            git('init');git('config','user.email','synthetic@example.invalid');git('config','user.name','Synthetic')
            (root/NOTE).parent.mkdir(parents=True);(root/NOTE).write_text('before\n')
            git('add','.');git('commit','-m','fixture');before=git('rev-parse','HEAD')
            (root/NOTE).write_text('after\n');git('add','.');git('commit','-m','note');head=git('rev-parse','HEAD')
            self.assertTrue(policy.inspect_changes(root,before,head)['low_risk_candidate'])
            (root/NOTE).rename(root/'index.html');git('add','-A');git('commit','-m','rename');renamed=git('rev-parse','HEAD')
            self.assertFalse(policy.inspect_changes(root,head,renamed)['low_risk_candidate'])


class FrozenQualityTests(unittest.TestCase):
    def test_application_matches_reviewed_snapshot(self):
        baseline=json.loads((ROOT/'quality/baseline.json').read_text())
        self.assertEqual(quality_gate.app_snapshot(ROOT),baseline['application'])
        self.assertEqual(len(baseline['mandatory_tests']),82)
    def test_mutations_to_data_rules_or_schema_fail_snapshot(self):
        baseline=quality_gate.app_snapshot(ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in baseline['banks']:(root/name).write_bytes((ROOT/name).read_bytes())
            original=(root/'index.html').read_text()
            for before,after in [("q:'電気を帯びた原子", "q:'変更された原子"),
                                 ("case 'text':return", "case 'text': return"),
                                 ("schemaVersion:92", "schemaVersion:93"),
                                 ("const KEY='rikaTangoV2'", "const KEY='other'")]:
                with self.subTest(change=before):
                    self.assertIn(before,original)
                    (root/'index.html').write_text(original.replace(before,after,1))
                    self.assertNotEqual(quality_gate.app_snapshot(root),baseline)
    def test_zero_skipped_expected_failures_and_missing_runs_stop_gate(self):
        r=Mock();r.wasSuccessful.return_value=True;r.skipped=[];r.expectedFailures=[];r.unexpectedSuccesses=[];r.executed={'required'}
        self.assertTrue(quality_gate.result_is_ready(r,{'required'}))
        for attr in ['skipped','expectedFailures','unexpectedSuccesses']:
            setattr(r,attr,['one']);self.assertFalse(quality_gate.result_is_ready(r,{'required'}));setattr(r,attr,[])
        r.executed=set();self.assertFalse(quality_gate.result_is_ready(r,{'required'}))
        r.executed={'required'};r.wasSuccessful.return_value=False
        self.assertFalse(quality_gate.result_is_ready(r,{'required'}))


class WorkflowSafetyTests(unittest.TestCase):
    def workflows(self):
        return [yaml.load(p.read_text(),Loader=yaml.BaseLoader) for p in sorted((ROOT/'.github/workflows').glob('*.yml'))]
    def test_only_public_standard_linux_jobs_and_read_permissions(self):
        for workflow in self.workflows():
            self.assertTrue(all(v=='read' for v in workflow['permissions'].values()))
            for job in workflow['jobs'].values():
                self.assertEqual(job['runs-on'],'ubuntu-24.04')
                self.assertIn("visibility == 'public'",job['if'])
                self.assertIn('private == false',job['if'])
                self.assertLessEqual(int(job['timeout-minutes']),15)
                for step in job['steps']:
                    if 'uses' in step:
                        self.assertRegex(step['uses'],r'^actions/(checkout|setup-python)@[0-9a-f]{40}$')
                        if step['uses'].startswith('actions/checkout@'):
                            self.assertEqual(step['with']['persist-credentials'],'false')
    def test_no_schedules_privileged_pr_events_deployments_or_merge_actions(self):
        for path in (ROOT/'.github/workflows').glob('*.yml'):
            workflow=yaml.load(path.read_text(),Loader=yaml.BaseLoader)
            self.assertNotIn('schedule',workflow['on']);self.assertNotIn('pull_request_target',workflow['on'])
            for forbidden in ['workflow_run','secrets.','OPENAI','pulls.merge','gh pr merge','deploy-pages@','self-hosted','ubuntu-latest-m','write-all']:
                self.assertNotIn(forbidden,path.read_text())
    def test_token_binding_is_only_in_read_only_pages_preflight(self):
        workflow=yaml.load((ROOT/'.github/workflows/pages-readiness.yml').read_text(),Loader=yaml.BaseLoader)
        bound=[s for s in workflow['jobs']['verify']['steps'] if 'GITHUB_TOKEN' in s.get('env',{})]
        self.assertEqual(len(bound),1);self.assertIn('prepare_pages_smoke.py',bound[0]['run'])
    def test_required_gate_runs_full_suite_and_no_path_filters_hide_changes(self):
        workflow=yaml.load((ROOT/'.github/workflows/history-tests.yml').read_text(),Loader=yaml.BaseLoader)
        self.assertNotIn('paths',workflow['on']['pull_request'] or {})
        self.assertIn('python scripts/quality_gate.py',[s.get('run') for s in workflow['jobs']['history']['steps']])


class PagesPreflightTests(unittest.TestCase):
    def event(self):return {'repository':{'full_name':pages.REPO,'private':False},'build':{'status':'built','commit':COMMIT}}
    def api(self,path):
        return {'pages':{'html_url':pages.SITE,'cname':None,'public':True,'source':{'branch':'main','path':'/'},'status':'built','build_type':'legacy'},
                'commits/main':{'sha':COMMIT},'pages/builds/latest':{'commit':COMMIT,'status':'built'},
                'contents/index.html?ref='+COMMIT:{'type':'file','encoding':'base64','content':base64.b64encode(b'html').decode()}}[path]
    def test_verified_publication_and_exact_content_can_proceed(self):
        info,html=pages.prepare('page_build',self.event(),None,self.api,lambda url:b'html')
        self.assertEqual(html,b'html');self.assertEqual(info['sha'],COMMIT)
    def test_private_unknown_repository_and_unverified_trigger_stop_before_network(self):
        for event in [{}, {'repository':{'full_name':pages.REPO,'private':True}}, {'repository':{'full_name':'other/repo','private':False}}]:
            api=Mock()
            with self.assertRaises(ValueError):pages.prepare('page_build',event,None,api,Mock())
            api.assert_not_called()
        with self.assertRaises(ValueError):pages.deployment_sha('pull_request',self.event(),COMMIT)
    def test_custom_host_redirect_unknown_source_and_not_built_are_refused(self):
        site=self.api('pages')
        for update in [{'html_url':'https://attacker.invalid/'},{'cname':'attacker.invalid'}, {'source':None}, {'public':False},{'status':'building'}]:
            with self.subTest(update=update),self.assertRaises(ValueError):pages.validate_site(dict(site,**update))
        with self.assertRaises(ValueError):pages.NoRedirect().redirect_request(None,None,None,None,None,None)
    def test_stale_deployments_and_changed_public_html_stop(self):
        def stale(path):return {'sha':'b'*40} if path=='commits/main' else self.api(path)
        with self.assertRaises(ValueError):pages.prepare('page_build',self.event(),None,stale,lambda url:b'html')
        with self.assertRaises(ValueError):pages.prepare('page_build',self.event(),None,self.api,lambda url:b'wrong')
    def test_workflow_deployment_requires_bot_and_success(self):
        event=self.event();event['deployment_status']={'state':'success'}
        event['deployment']={'environment':'github-pages','sha':COMMIT,'creator':{'login':'attacker'}}
        with self.assertRaises(ValueError):pages.deployment_sha('deployment_status',event,None)
        event['deployment']['creator']['login']='github-actions[bot]'
        self.assertEqual(pages.deployment_sha('deployment_status',event,None),COMMIT)
    def test_manual_sha_is_required_and_must_be_full(self):
        for sha in ['',None,'main','a'*7,'https://attacker.invalid']:
            with self.subTest(sha=sha),self.assertRaises(ValueError):pages.deployment_sha('workflow_dispatch',self.event(),sha)
        self.assertEqual(pages.deployment_sha('workflow_dispatch',self.event(),COMMIT),COMMIT)
    def test_changed_download_metadata_cannot_launch_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'index.html').write_text('wrong')
            (root/'metadata.json').write_text(json.dumps({'url':pages.SITE,'sha':COMMIT,'sha256':'wrong'}))
            with self.assertRaises(ValueError):pages_smoke.smoke(root)
    def test_downloaded_application_smoke_in_isolated_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);html=(ROOT/'index.html').read_bytes()
            (root/'index.html').write_bytes(html)
            (root/'metadata.json').write_text(json.dumps({'url':pages.SITE,'sha':COMMIT,'sha256':hashlib.sha256(html).hexdigest()}))
            pages_smoke.smoke(root)


if __name__=='__main__':unittest.main()
