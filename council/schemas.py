"""Typed validation of untrusted LLM outputs; malformed roles cannot mutate state."""
from __future__ import annotations
from typing import Literal, get_args, get_origin
from pydantic import (BaseModel, ConfigDict, Field, ValidationError,
                      field_validator, model_validator)

class ModelSchema(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def _coerce_string_lists(cls, data):
        """Repair harmless provider str-for-list[str] errors for every role.

        Keep integer lists and nested/structured values strict. Do not mutate
        the caller's object or reinterpret arbitrary JSON objects as strings.
        """
        if not isinstance(data,dict):
            return data
        clean=dict(data)
        for name,field in cls.model_fields.items():
            if (name in clean and isinstance(clean[name],str)
                    and get_origin(field.annotation) is list
                    and get_args(field.annotation)==(str,)):
                text=clean[name].strip()
                clean[name]=[text] if text else []
        return clean


def _as_string_list(value):
    # Only lossless container normalization. Arbitrary objects and nested
    # values must still fail strict validation.
    if value is None:
        return []
    if isinstance(value,str):
        return [value] if value.strip() else []
    return value


class ProposedClaim(ModelSchema):
    id:str=Field(min_length=1,max_length=160)
    statement:str=Field(min_length=1,max_length=10000)
    source_span:str|None=None
    sentence_ids:list[int]=Field(default_factory=list)
    assumptions:list[str]=Field(default_factory=list)
    limitations:list[str]=Field(default_factory=list)
    depends_on:list[str]=Field(default_factory=list)
    dependency_argument:str|None=None

    @field_validator("assumptions", "limitations", "depends_on", mode="before")
    @classmethod
    def _listify(cls, value):
        return _as_string_list(value)


class Proposal(ModelSchema):
    approach:str=Field(min_length=1)
    answer:str|None=None
    final_answer:str=Field(default="")
    artifact:dict=Field(default_factory=dict)
    claims:list[ProposedClaim]=Field(min_length=1)
    hypotheses:list[str]=Field(default_factory=list)
    experiments:list[str]=Field(default_factory=list)

    @field_validator("approach", mode="before")
    @classmethod
    def _join_approach(cls, value):
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            # Preserve numbered source-line boundaries for exact provenance.
            return "\n".join(value)
        return value

    @field_validator("hypotheses", "experiments", mode="before")
    @classmethod
    def _listify(cls, value):
        return _as_string_list(value)


class ReviewObjection(ModelSchema):
    claim_id:str=Field(min_length=1)
    issue:str=Field(min_length=1)
    consequence:str=Field(min_length=1)
    suggested_check:str=Field(min_length=1)

class Review(ModelSchema):
    objections:list[ReviewObjection]

class AuthorResponseSchema(ModelSchema):
    objection_id:str=Field(min_length=1)
    disposition:Literal["accept","reject","partial","unresolved"]
    explanation:str=Field(min_length=1)

class RevisedClaim(ModelSchema):
    claim_id:str=Field(min_length=1)
    statement:str=Field(min_length=1)
    source_span:str|None=None
    # [R#] numbers locate revised source text; they are NOT evidence.
    sentence_ids:list[int]=Field(default_factory=list)
    assumptions:list[str]=Field(default_factory=list)

class Revision(ModelSchema):
    revised_approach:str|None=None

    @field_validator("revised_approach", mode="before")
    @classmethod
    def _join_revised_approach(cls, value):
        if isinstance(value,list) and all(isinstance(item,str) for item in value):
            return "\n".join(value)
        return value

    responses:list[AuthorResponseSchema]=Field(default_factory=list)
    revised_claims:list[RevisedClaim]=Field(default_factory=list)

class Translation(ModelSchema):
    rung:int|None=None
    claim_kind:str|None=None
    scope:str|None=None
    artifact:dict=Field(default_factory=dict)

class Hunter(ModelSchema):
    found:bool
    counterexample:str=""
    check_artifact:dict=Field(default_factory=dict)
    tried:list[str]=Field(default_factory=list)

    @field_validator("counterexample", mode="before")
    @classmethod
    def _counterexample_string(cls, value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        # Preserve the exact JSON payload: don't claim it was a string
        # originally or invent a new counterexample.
        if isinstance(value, (list,dict)):
            import json
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return value

    @field_validator("tried", mode="before")
    @classmethod
    def _tried_strings(cls, value):
        if value is None:
            return []
        if not isinstance(value,list):
            value=[value]
        import json
        return [item if isinstance(item,str) else
                json.dumps(item,ensure_ascii=False,sort_keys=True)
                if isinstance(item,(dict,list)) else item
                for item in value]

class Judge(ModelSchema):
    status:Literal["answer","unresolved"]
    answer:str|None=None
    partial_answer:str|None=None
    blocking:list[str]=Field(default_factory=list)
    basis:list[str]=Field(default_factory=list)

class TopicVersion(ModelSchema):
    id:str=Field(min_length=1)
    status:Literal["matches","contradicts","incomplete"]
    reference_quote:str=""
    reason:str=Field(min_length=1)


class TopicPartialMatch(ModelSchema):
    id:str=Field(min_length=1)
    agrees:list[str]=Field(default_factory=list)
    conflicts:list[str]=Field(default_factory=list)
    reference_quote:str=""


class TopicJudge(ModelSchema):
    # The caller knows the topic; the model does not need to echo it.
    topic:str|None=None
    versions:list[TopicVersion]
    best_version_id:str|None=None
    missing:list[str]=Field(default_factory=list)
    partial_matches:list[TopicPartialMatch]=Field(default_factory=list)
    summary:str|None=None


class ObjectionJudgment(ModelSchema):
    id:str=Field(min_length=1)
    verdict:Literal["valid","contradicts_reference","already_in_claim","out_of_scope"]
    quote:str=""
    reason:str=""


class ObjectionJudge(ModelSchema):
    items:list[ObjectionJudgment]


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
    issues:list[str]
    suggested_checks:list[str]=Field(default_factory=list)

class Coverage(ModelSchema):
    missing_requirements:list[str]

class Relevance(ModelSchema):
    entails:bool
    limitations:list[str]=Field(default_factory=list)
    missing_assumptions:list[str]=Field(default_factory=list)

class Repair(ModelSchema):
    revised_statement:str|None=None
    assumptions:list[str]=Field(default_factory=list)
    proof_obligations:list[str]=Field(default_factory=list)

SCHEMAS={
    "proposal":Proposal, "review":Review, "revision":Revision,
    "topic_judge":TopicJudge, "objection_judge":ObjectionJudge,
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
