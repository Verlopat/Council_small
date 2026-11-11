"""Selection uses current scoped evidence, never benchmark reference answers."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from council.final_answers import select_candidate_answer, proposal_answers
from council.models import Claim, ClaimLedger, ClaimStatus, Evidence, EvidenceKind
from council.transport import CallResult
from eval.execute import run_task
from eval.code_tasks import public_case_output
from council.verify.sandbox import SandboxResult


class SelectionTests(unittest.TestCase):
    def test_contradicted_first_proposal_is_excluded_but_retained_as_candidate(self):
        claims=[Claim('p1:answer',1,'Reported final scalar result: 14','a',
                      status=ClaimStatus.CONTRADICTED),
                Claim('p2:answer',1,'Reported final scalar result: 13','b')]
        choice=select_candidate_answer({'p1':'14','p2':'13'},claims,[])
        self.assertEqual(choice['answer'],'13')
        self.assertIn('p1',choice['excluded'])
        self.assertIsNone(select_candidate_answer({'p1':'14'},claims,[])['answer'])

    def test_current_translator_answer_pass_preferred_but_never_verified(self):
        ledger=ClaimLedger()
        for pid in ('p1','p2'):
            ledger.add_claim(Claim(pid+':answer',2,'Reported final scalar result: 13',
                                   pid,needs_re_evaluation=True))
        ev=Evidence('e','p2:answer',2,EvidenceKind.TEST,'pass','scope','hash',
                    independently_checked=False,checker_kind='arithmetic')
        ledger.attach(ev)
        candidates={'p1':'14','p2':'13'}
        self.assertEqual(select_candidate_answer(candidates,ledger.claims.values(),
            ledger.evidence.values())['answer'],'13')
        proposals=[{'id':pid,'final_answer':v,'answer_claim_id':pid+':answer',
                    'claim_ids':[pid+':answer']} for pid,v in candidates.items()]
        verified,raw=proposal_answers(proposals,ledger)
        self.assertIsNone(verified)
        self.assertEqual(raw,candidates)

    def test_author_and_stale_pass_do_not_rank_a_candidate_higher(self):
        claim=Claim('p2:answer',2,'Reported final scalar result: 13','b')
        for version,checker in ((1,'arithmetic'),(2,'author_recompute')):
            ev=Evidence('e','p2:answer',version,EvidenceKind.TEST,'pass','x','h',
                        checker_kind=checker)
            chosen=select_candidate_answer({'p1':'14','p2':'13'},[claim],[ev])
            self.assertEqual(chosen['proposal_id'],'p1')

    def test_independent_failure_blocks_even_if_later_pass_overwrote_status(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim('p1:answer',1,'6*7 = 42','a'))
        for name,outcome in (('fail','fail'),('pass','pass')):
            ledger.attach(Evidence(name,'p1:answer',1,EvidenceKind.TEST,
                outcome,'6*7','hash',independently_checked=True))
        p={'id':'p1','final_answer':'42','answer_claim_id':'p1:answer',
           'claim_ids':['p1:answer']}
        self.assertEqual(proposal_answers([p],ledger),(None,{'p1':'42'}))


class CodeVotingTests(unittest.IsolatedAsyncioTestCase):
    async def test_distinct_program_texts_vote_on_public_execution_before_hidden_grade(self):
        class Council:
            def __init__(self,*args,**kwargs): pass
            async def run(self,*args,**kwargs):
                return {'research_result':{},'candidate_answers':{},
                        'verdict':{},'composition':{}}
        class Events:
            def replay(self): return [{'event':'model_call_started'}]*2
        programs=['def f(xs):\n    return sum(xs)',
                  'def f(xs):\n    return sum(x for x in xs)']
        class Transport:
            i=0
            async def complete(self,family,*args,**kwargs):
                text=programs[self.i]; self.i+=1
                return CallResult(family,'mock','mock',text,0,'hash')
        with patch('eval.execute.FullCouncilRunner',Council), \
             patch('eval.execute.public_case_output',return_value='3') as public, \
             patch('eval.execute.hidden_case_outcome',return_value='pass') as hidden:
            rows=await run_task({'id':'code','kind':'code',
                'prompt':'Implement f(xs). For xs=[1,2], give the output.',
                'expected':'3','hidden_spec':{'cases':[]}},
                Transport(),Events(),deadline=20,baseline_samples=2,skip_vote6=True)
        vote=next(r for r in rows if r['system']=='self_consistency')
        self.assertFalse(vote['unresolved'])
        self.assertEqual(vote['answer'],programs[0])
        self.assertEqual(vote['correct'],1)
        self.assertEqual(public.call_count,2)
        self.assertTrue(all('hidden_spec' not in c.kwargs for c in public.call_args_list))

    def test_public_input_is_literal_and_hidden_cases_are_never_used(self):
        with patch('eval.code_tasks.available',return_value=True), \
             patch('eval.code_tasks.run_python',return_value=SandboxResult(
                 'ok','done',stdout='{"result":3}')) as execute:
            self.assertEqual(public_case_output('def f(xs):\n    return sum(xs)',
                                               'Output for xs=[1,2].'),'3')
            self.assertIn('f([1, 2])',execute.call_args.args[0])
            self.assertIsNone(public_case_output('def f(xs):\n    return 1',
                                                'Implement f(xs).'))
            self.assertEqual(execute.call_count,1)


class EvaluationSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_evaluation_does_not_fall_back_to_contradicted_scalar(self):
        class Council:
            def __init__(self,*args,**kwargs): pass
            async def run(self,*args,**kwargs):
                return {'research_result':{},'candidate_answers':{'p1':'14','p2':'13'},
                        'claims':[{'id':'p1:answer','version':1,'status':'contradicted'}],
                        'verdict':{},'composition':{}}
        events=SimpleNamespace(replay=lambda:[])
        with patch('eval.execute.FullCouncilRunner',Council):
            rows=await run_task({'id':'n','prompt':'word problem','expected':'13'},
                object(),events,deadline=20,run_baselines=False)
        self.assertEqual(rows[0]['answer'],'13')
        self.assertEqual(rows[0]['verified'],0)
        self.assertEqual(rows[0]['candidate_answers']['p1'],'14')
