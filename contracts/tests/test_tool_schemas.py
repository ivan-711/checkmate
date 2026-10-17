"""The three tool JSON Schemas are valid and agree with the Pydantic argument models."""
import json
from pathlib import Path

import jsonschema
from jsonschema import Draft202012Validator

from contracts.models.policy import AttachArgs, ProposeArgs, SearchArgs

TOOLS = Path(__file__).parents[1] / "tools"


def _load(name: str) -> dict:
    return json.loads((TOOLS / f"{name}.json").read_text())


def test_schemas_are_valid_2020_12():
    for name in ("search_patients", "propose_new_chart", "attach_history"):
        Draft202012Validator.check_schema(_load(name)["parameters"])
    Draft202012Validator.check_schema(_load("tool_result.schema"))


def test_no_id_score_or_override_fields_anywhere():
    forbidden = {"recordId", "candidateId", "pairId", "entityId", "score", "p", "band", "override", "targetRecordId"}
    for name in ("search_patients", "propose_new_chart", "attach_history"):
        text = json.dumps(_load(name))
        for word in forbidden:
            assert f'"{word}"' not in text, (name, word)


def test_schema_properties_match_pydantic_fields():
    pairs = [("search_patients", SearchArgs), ("propose_new_chart", ProposeArgs), ("attach_history", AttachArgs)]
    for name, model in pairs:
        schema_props = set(_load(name)["parameters"]["properties"])
        model_props = {f.alias or n for n, f in model.model_fields.items()}
        model_props = {model.model_config["alias_generator"](n) for n in model.model_fields}
        assert schema_props == model_props, (name, schema_props ^ model_props)
        assert set(_load(name)["parameters"].get("required", [])) <= schema_props


def test_sample_calls_validate_both_ways():
    propose = _load("propose_new_chart")["parameters"]
    sample = {"givenName": "María", "familyName": "González Rivera", "birthDate": "1985-07-03", "sex": "FEMALE",
              "preferredLanguage": "ES", "evidence": {"givenName": "Me llamo María"}}
    jsonschema.validate(sample, propose)
    ProposeArgs.model_validate(sample)
    bad = dict(sample, recordId="abc")
    with __import__("pytest").raises(jsonschema.ValidationError):
        jsonschema.validate(bad, propose)
