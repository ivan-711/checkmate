"""parse_action: validation into the tool models, canonical sha256, and the grounding check."""

from __future__ import annotations

import pytest

from backend.policy.args import MONTH_NAMES, fold, parse_action
from backend.tests.policy.factories import session
from contracts.models.policy import AttachArgs, InvalidArgs, ProposeArgs, SearchArgs

TEXT_ES = "Me llamo María-José González Rivera, nací el 3 de julio de 1985, mujer, teléfono (555) 010-0100, CP 54311"
TEXT_EN = "I'm Theodore Blackwood, born March 7, 1950. Male. Phone 555-999-0000"
EVIDENCE = {
    "givenName": "María-José",
    "familyName": "González Rivera",
    "birthDate": "3 de julio de 1985",
    "sex": "mujer",
    "phone": "(555) 010-0100",
    "postalCode": "CP 54311",
}
ARGS = {
    "givenName": "Maria Jose",
    "familyName": "Gonzalez Rivera",
    "birthDate": "1985-07-03",
    "sex": "FEMALE",
    "phone": "5550100100",
    "postalCode": "54311",
    "preferredLanguage": "ES",
    "evidence": EVIDENCE,
}


def parse(tool="propose_new_chart", args=ARGS, texts=(TEXT_ES,)):
    return parse_action(tool, args, user_texts=texts, session=session())


def test_fold_strips_accents_case_and_whitespace():
    assert fold("  María-José   GONZÁLEZ ") == "maria-jose gonzalez"


def test_month_table_has_24_entries():
    assert sum(len(v) for v in MONTH_NAMES.values()) == 24


def test_grounded_with_accent_case_and_punctuation_differences():
    act = parse()
    assert isinstance(act.args, ProposeArgs) and act.grounding_ok
    assert act.tool == "propose_new_chart" and len(act.args_sha256) == 64


def test_sha_is_canonical_over_validated_args():
    reordered = {k: ARGS[k] for k in reversed(list(ARGS))}
    assert parse(args=reordered).args_sha256 == parse().args_sha256
    assert parse(args={**ARGS, "phone": "5550100101"}).args_sha256 != parse().args_sha256


def test_english_month_name_and_numeric_month():
    en = {
        "givenName": "Theodore",
        "familyName": "Blackwood",
        "birthDate": "1950-03-07",
        "sex": "MALE",
        "phone": "5559990000",
        "preferredLanguage": "EN",
        "evidence": {
            "givenName": "Theodore",
            "familyName": "Blackwood",
            "birthDate": "March 7, 1950",
            "sex": "Male",
            "phone": "555-999-0000",
        },
    }
    assert parse(args=en, texts=(TEXT_EN,)).grounding_ok
    numeric_text = "Theodore Blackwood, 7/3/1950, Male, 555-999-0000"
    en_numeric = {**en, "evidence": {**en["evidence"], "birthDate": "7/3/1950"}}
    assert parse(args=en_numeric, texts=(numeric_text,)).grounding_ok


def test_wrong_month_or_year_is_ungrounded():
    assert not parse(args={**ARGS, "birthDate": "1985-08-03"}).grounding_ok
    assert not parse(args={**ARGS, "birthDate": "1986-07-03"}).grounding_ok


def test_value_without_quote_is_ungrounded():
    no_phone_quote = {**ARGS, "evidence": {k: v for k, v in EVIDENCE.items() if k != "phone"}}
    assert not parse(args=no_phone_quote).grounding_ok


def test_quote_not_in_user_text_is_ungrounded():
    assert not parse(texts=("hola, buenas tardes",)).grounding_ok


def test_name_not_in_quote_is_ungrounded():
    assert not parse(args={**ARGS, "givenName": "Mariana"}).grounding_ok


def test_phone_and_postal_compare_digits_only():
    assert not parse(args={**ARGS, "phone": "5550100199"}).grounding_ok
    assert not parse(args={**ARGS, "postalCode": "54312"}).grounding_ok


def test_quote_search_grounded_across_turns():
    texts = ("Me llamo María-José González Rivera", "nací el 3 de julio de 1985")
    args = {"givenName": "Maria Jose", "familyName": "Gonzalez Rivera", "birthDate": "1985-07-03", "evidence": EVIDENCE}
    act = parse("search_patients", args, texts)
    assert isinstance(act.args, SearchArgs) and act.grounding_ok


def test_invalid_arguments_become_invalid_args():
    act = parse(args={"givenName": "x" * 61, "unknown": 1})
    assert isinstance(act.args, InvalidArgs) and act.args.errors and not act.grounding_ok
    search = parse("search_patients", {"givenName": "Maria", "evidence": {}})
    assert isinstance(search.args, InvalidArgs)


def test_attach_history_quotes_must_appear_in_user_text():
    items = {"items": [{"kind": "ALLERGY", "text": "amoxicillin", "evidenceQuote": "alérgica a la amoxicilina"}]}
    assert parse("attach_history", items, ("Soy ALÉRGICA a la Amoxicilina",)).grounding_ok
    act = parse("attach_history", items, ("no tengo alergias",))
    assert isinstance(act.args, AttachArgs) and not act.grounding_ok


def test_unknown_tool_is_invalid_and_ungrounded():
    act = parse("create_patient", {"x": 1})
    assert isinstance(act.args, InvalidArgs) and not act.grounding_ok and act.tool == "create_patient"


@pytest.mark.parametrize("month", range(1, 13))
def test_every_month_name_grounds_a_date(month):
    for name in MONTH_NAMES[month]:
        text = f"born 15 {name} 1990"
        args = {**ARGS, "birthDate": f"1990-{month:02d}-15", "evidence": {**EVIDENCE, "birthDate": text}}
        assert parse(args=args, texts=(TEXT_ES + " " + text,)).grounding_ok


def test_sex_unknown_needs_no_quote():
    no_sex_quote = {k: v for k, v in EVIDENCE.items() if k != "sex"}
    assert parse(args={**ARGS, "sex": "UNKNOWN", "evidence": no_sex_quote}).grounding_ok
    # a quote given for UNKNOWN is ignored, even one that is not in the user text
    assert parse(args={**ARGS, "sex": "UNKNOWN", "evidence": {**no_sex_quote, "sex": "not typed"}}).grounding_ok


def test_stated_sex_needs_a_quote_with_a_sex_word():
    no_sex_quote = {k: v for k, v in EVIDENCE.items() if k != "sex"}
    assert not parse(args={**ARGS, "sex": "FEMALE", "evidence": no_sex_quote}).grounding_ok
    assert parse(
        args={**ARGS, "evidence": {**no_sex_quote, "sex": "soy mujer"}}, texts=(TEXT_ES + " soy mujer",)
    ).grounding_ok
    # the quote is in the text but names the other sex: ungrounded
    assert not parse(args={**ARGS, "sex": "MALE", "evidence": {**no_sex_quote, "sex": "mujer"}}).grounding_ok
