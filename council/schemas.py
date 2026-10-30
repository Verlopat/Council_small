"""Typed validation of untrusted LLM outputs; malformed roles cannot mutate state."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

class ModelSchema(BaseModel):
    model_config=ConfigDict(extra="ignore",str_strip_whitespace=True)

class ProposedClaim(ModelSchema):
    id:str=Field(min_length=1,max_length=160)
    statement:str=Field(min_length=1,max_length=10000)
    source_span:str|None=None
    assumptions:list[str]=Field(default_factory=list)
    limitations:list[str]=Field(default_factory=list)
    depends_on:list[str]=Field(default_factory=list)
    dependency_argument:str|None=None

class Proposal(ModelSchema):
    approach:str=Field(min_length=1)
    answer:str|None=None
    claims:list[ProposedClaim]=Field(min_length=1)
    hypotheses:list[str]=Field(default_factory=list)
    experiments:list[str]=Field(default_factory=list)

class ReviewObjection(ModelSchema):
    claim_id:str=Field(min_length=1)
    issue:str=Field(min_length=1)
    consequence:str=Field(min_length=1)
    suggested_check:str=Field(min_length=1)

class Review(ModelSchema):
    objections:list[ReviewObjection]=Field(default_factory=list)

class AuthorResponseSchema(ModelSchema):
    objection_id:str=Field(min_length=1)
    disposition:Literal["accept","reject","partial","unresolved"]
    explanation:str=Field(min_length=1)

class RevisedClaim(ModelSchema):
    claim_id:str=Field(min_length=1)
    statement:str=Field(min_length=1)
    source_span:str|None=None
    assumptions:list[str]=Field(default_factory=list)

class Revision(ModelSchema):
    revised_approach:str|None=None
    responses:list[AuthorResponseSchema]=Field(default_factory=list)
    revised_claims:list[RevisedClaim]=Field(default_factory=list)

class Translation(ModelSchema):
    claim_kind:str|None=None
    scope:str|None=None
    artifact:dict=Field(default_factory=dict)

class Hunter(ModelSchema):
    found:bool=False
    counterexample:str=""
    check_artifact:dict=Field(default_factory=dict)
    tried:list[str]=Field(default_factory=list)

class Judge(ModelSchema):
    status:Literal["answer","unresolved"]
    answer:str|None=None
    partial_answer:str|None=None
    blocking:list[str]=Field(default_factory=list)
    basis:list[str]=Field(default_factory=list)

class Synthesis(ModelSchema):
    proposed_approach:str=Field(min_length=1)
    supported_findings:list[str]=Field(default_factory=list)
    hypotheses:list[str]=Field(default_factory=list)
    unresolved_objections:list[str]=Field(default_factory=list)
    proof_obligations:list[str]=Field(default_factory=list)
    proposed_experiments:list[str]=Field(default_factory=list)
    next_actions:list[str]=Field(default_factory=list)
    completion_status:Literal["partial","unresolved"]="partial"

class Audit(ModelSchema):
    issues:list[str]=Field(default_factory=list)
    suggested_checks:list[str]=Field(default_factory=list)

class Coverage(ModelSchema):
    missing_requirements:list[str]=Field(default_factory=list)

class Relevance(ModelSchema):
    entails:bool=False
    limitations:list[str]=Field(default_factory=list)
    missing_assumptions:list[str]=Field(default_factory=list)

class Repair(ModelSchema):
    revised_statement:str|None=None
    assumptions:list[str]=Field(default_factory=list)
    proof_obligations:list[str]=Field(default_factory=list)

SCHEMAS={
    "proposal":Proposal, "review":Review, "revision":Revision,
    "translate":Translation, "hunter":Hunter, "judge":Judge,
    "synthesis":Synthesis, "audit":Audit,
    "coverage":Coverage,"relevance":Relevance,"repair":Repair,
}

def validate(role:str,payload:dict)->dict:
    schema=SCHEMAS.get(role)
    if schema is None:return payload
    # Do not coerce arbitrary object types into a plausible JSON contract.
    try:
        obj=schema.model_validate(payload,strict=True)
    except ValidationError as error:
        raise ValueError("Invalid "+role+" output: "+
                         "; ".join(".".join(map(str,e["loc"]))+
                                   ": "+e["type"] for e in error.errors()[:5])) from None
    return obj.model_dump(exclude_none=True)
