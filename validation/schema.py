"""Validate the serialized contracts, independently of scheduling semantics."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parents[1]
VALIDATORS={}
for name in ('dataset','scenarios','result'):
    schema=json.loads((ROOT/'schemas'/f'{name}.schema.json').read_text())
    Draft202012Validator.check_schema(schema)
    VALIDATORS[name]=Draft202012Validator(schema)


def validate(name,value):
    VALIDATORS[name].validate(value)
