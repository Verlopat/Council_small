"""Final bounded change: executed answers, labeled scalars and literal identities."""
import asyncio
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from council.budget import RunBudget
from council.events import EventStore
from council.final_answers import (normalize_answer, proposal_answers,
                                   executed_answer_selection)
from council.full import FullCouncilRunner
from council.models import Claim, ClaimLedger, Evidence, EvidenceKind
from council.verify.sandbox import SandboxResult
from eval.execute import run_task

QUESTION=("For all real x, is (x+15)*(x+20) equal to x**2+35*x+300? "
          "Explain briefly, then finish with exactly 'Final answer: yes' "
          "or 'Final answer: no'.")
ARTIFACT={'left':'(x+15)*(x+20)','right':'x**2+35*x+300'}


def make_runner(events):
    return FullCouncilRunner(None,events,RunBudget.start(60,reserve=3),
        solvers=('gpt-oss',),hunter_cap=0,enable_coverage=False,enable_repairs=False)


def executed(pid,family,printed,stated,ledger):
    code='print('+repr(printed)+')'
    ledger.add_claim(Claim(pid+':answer',1,'Reported final scalar result: '+stated,family))
    return {'id':pid,'family':family,'final_answer':stated,
            'executed_answer':printed,'artifact':{'kind':'python','code':code},
            'answer_claim_id':pid+':answer','claim_ids':[pid+':answer'],
            'executed_claim_version':1,
            'executed_artifact_hash':hashlib.sha256(code.encode()).hexdigest()}


class ExecutedSelectionTests(unittest.TestCase):
    def test_two_families_recover_printed_answer_without_certifying_it(self):
        ledger=ClaimLedger()
        ps=[executed('p1','gpt-oss','13','14',ledger),
            executed('p2','command','13','17',ledger)]
        for p in ps:p['author_inconsistency']=True
        choice=executed_answer_selection(ps,ledger.claims.values(),[])
        self.assertEqual(choice['answer'],'13')
        self.assertEqual(choice['basis'],'executed_agreement_not_formal_proof')
        self.assertEqual(choice['families'],['command','gpt-oss'])
        self.assertIsNone(proposal_answers(ps,ledger)[0])

    def test_duplicate_family_does_not_create_agreement(self):
        ledger=ClaimLedger()
        ps=[executed('p1','glm','13','14',ledger),
            executed('p2','glm','13.0','17',ledger)]
        self.assertIsNone(executed_answer_selection(ps,ledger.claims.values(),[])['answer'])

    def test_self_consistency_is_third_tier_and_no_code_means_no_answer(self):
        ledger=ClaimLedger()
        p=executed('p1','gpt-oss','13','13.0',ledger)
        choice=executed_answer_selection([p],ledger.claims.values(),[])
        self.assertEqual(choice['answer'],'13')
        self.assertEqual(choice['basis'],'self_consistent_execution_unverified')
        p.pop('executed_answer')
        self.assertIsNone(executed_answer_selection([p],ledger.claims.values(),[])['answer'])

    def test_verified_answer_precedes_executed_agreement(self):
        ledger=ClaimLedger()
        ps=[executed('p1','a','13','14',ledger),executed('p2','b','13','17',ledger)]
        choice=executed_answer_selection(ps,ledger.claims.values(),[],verified='12')
        self.assertEqual(choice['answer'],'12')
        self.assertEqual(choice['basis'],'independently_verified_answer')

    def test_conflicting_agreements_abstain(self):
        ledger=ClaimLedger()
        ps=[executed('p'+str(i),family,value,value,ledger)
            for i,(family,value) in enumerate((('a','13'),('b','13'),('c','14'),('d','14')))]
        self.assertEqual(executed_answer_selection(ps,ledger.claims.values(),[])['basis'],
                         'conflicting_executed_agreements')

    def test_stale_code_or_claim_version_does_not_vote(self):
        for mutate in ('code','version'):
            ledger=ClaimLedger()
            ps=[executed('p1','a','13','14',ledger),executed('p2','b','13','17',ledger)]
            if mutate=='code':ps[1]['artifact']['code']='print(17)'
            else:ledger.revise('p2:answer','A changed claim')
            self.assertIsNone(executed_answer_selection(ps,ledger.claims.values(),[])['answer'])

    def test_label_stripping_is_anchored_and_does_not_accept_explanations(self):
        self.assertEqual(normalize_answer('Final answer: yes'),'yes')
        self.assertEqual(normalize_answer('**Final answer: 13**'),'13')
        self.assertIsNone(normalize_answer('Earlier final answer: yes'))
        self.assertIsNone(normalize_answer('Final answer: yes because it is equal'))


class AuthorCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_consistency_still_retains_executed_value(self):
        with TemporaryDirectory() as folder, EventStore(Path(folder),'capture') as events:
            r=make_runner(events)
            p={'id':'p1','family':'gpt-oss','approach':'Compute', 'final_answer':'14',
               'claim_ids':[], 'artifact':{'kind':'python','code':'print(13)'}}
            r._register_answer_claim(p,'A word problem')
            with patch('council.verify.author_check.run_python',return_value=SandboxResult(
                    'ok','sandbox completed',stdout='13\n')):
                await r._run_author_artifact(p)
            self.assertEqual(p['executed_answer'],'13')
            self.assertTrue(p['author_inconsistency'])
            self.assertIsNone(proposal_answers([p],r.ledger)[0])
            with patch('council.verify.author_check.run_python',return_value=SandboxResult(
                    'error','sandbox failed')):
                await r._run_author_artifact(p)
            self.assertNotIn('executed_answer',p)


class IdentityVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def verify_identity(self,artifact,*,family='glm',answer='Final answer: yes'):
        with TemporaryDirectory() as folder, EventStore(Path(folder),'identity') as events:
            r=make_runner(events)
            r._current_question=QUESTION
            p={'id':'p1','family':'gpt-oss','approach':'Identity', 'final_answer':answer,
               'claim_ids':[]}
            r._register_answer_claim(p,QUESTION)
            r._translator_candidates=lambda claim:[family]
            r._call=AsyncMock(return_value={'rung':1,'claim_kind':'identity',
                'scope':'identity','artifact':artifact})
            with patch('council.verify.ladder.identity',
                       return_value=SimpleNamespace(outcome='pass')):
                await r._translate_and_check(r.ledger.claims['p1:answer'])
            return proposal_answers([p],r.ledger)[0],list(r.ledger.evidence.values())

    async def test_literal_independent_sympy_pass_can_verify_yes(self):
        verified,evidence=await self.verify_identity(ARTIFACT)
        self.assertEqual(verified,'yes')
        self.assertTrue(evidence[-1].independently_checked)

    async def test_different_expression_same_family_and_wrong_polarity_cannot_verify(self):
        for artifact,family,answer in (({'left':'x','right':'x'},'glm','yes'),
                                     (ARTIFACT,'gpt-oss','yes'),
                                     (ARTIFACT,'glm','no')):
            verified,evidence=await self.verify_identity(artifact,family=family,answer=answer)
            self.assertIsNone(verified)
            self.assertFalse(evidence[-1].independently_checked)

    def test_restricted_or_nonpolynomial_questions_do_not_gain_literal_alignment(self):
        self.assertFalse(FullCouncilRunner._literal_identity_alignment(
            'For all real x>0, is x equal to x?',{'left':'x','right':'x'}))
        self.assertFalse(FullCouncilRunner._literal_identity_alignment(
            'For all real x, is sqrt(x**2) equal to x?',{'left':'sqrt(x**2)','right':'x'}))


class EvaluationTierTests(unittest.IsolatedAsyncioTestCase):
    async def test_executed_agreement_is_scored_without_becoming_verified(self):
        class Runner:
            def __init__(self,*args,**kwargs):pass
            async def run(self,*args,**kwargs):
                return {'research_result':{},'candidate_answers':{'p1':'14','p2':'17'},
                    'final_answer':None,'executed_agreement_answer':'13',
                    'answer_selection':{'answer':'13','proposal_id':'p1',
                        'basis':'executed_agreement_not_formal_proof','families':['a','b']},
                    'verdict':{},'composition':{}}
        with patch('eval.execute.FullCouncilRunner',Runner):
            rows=await run_task({'id':'n','prompt':'word problem','expected':'13'},
                object(),SimpleNamespace(replay=lambda:[]),deadline=30,run_baselines=False)
        self.assertEqual(rows[0]['answer'],'13')
        self.assertEqual(rows[0]['correct'],1)
        self.assertEqual(rows[0]['verified'],0)
        self.assertEqual(rows[0]['false_verified'],0)


class FinalBenchmarkScriptTests(unittest.TestCase):
    def test_baselines_are_explicitly_enabled_for_single_paired_run(self):
        import os
        import subprocess
        import sys
        with TemporaryDirectory() as folder:
            root=Path(folder)
            shim=root/'python'
            shim.write_text('#!'+sys.executable+'\n'+'''import json,os,sys
from pathlib import Path
args=sys.argv[1:]
with open(os.environ['CALL_LOG'],'a') as out:out.write(json.dumps(args)+'\\n')
if args[:2]==['-m','council.preflight']:
    print(json.dumps({key:{'status':'pass'} for key in ('execution','network_isolation','host_home_isolation','environment_isolation')}))
elif args[:2]==['-m','eval.execute']:
    dest=Path(args[args.index('--out')+1]);dest.mkdir(parents=True,exist_ok=True)
    mode=args[args.index('--mode')+1]
    (dest/'results.jsonl').write_text(json.dumps({'task_id':'one','system':'council','mode':mode,'correct':1})+'\\n')
''')
            shim.chmod(0o755)
            env=dict(os.environ,PATH=str(root)+os.pathsep+os.environ['PATH'],
                     CALL_LOG=str(root/'calls.jsonl'),RUN_DIR=str(root/'runs'),
                     COUNT='1',MAX_TASKS='1',PAUSE_SECONDS='0',BASELINES='1',
                     BASELINE_SAMPLES='2')
            process=subprocess.run(['bash','scripts/benchmark_phase_a_modes.sh'],
                env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(process.returncode,0,process.stderr)
            jobs=[json.loads(line) for line in (root/'calls.jsonl').read_text().splitlines()]
            jobs=[j for j in jobs if j[:2]==['-m','eval.execute']]
            self.assertEqual(len(jobs),2)
            for job in jobs:
                self.assertIn('--skip-vote6',job)
                self.assertNotIn('--no-baselines',job)
                self.assertEqual(job[job.index('--baseline-samples')+1],'2')
