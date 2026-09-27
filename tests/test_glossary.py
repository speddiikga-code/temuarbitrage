import pytest

from arbitrage.errors import ConfigError
from arbitrage.glossary import DEFAULT, Glossary, load


def test_lookup_ignores_case_plural_and_hyphens():
    assert DEFAULT.lookup("Tongs") == ("집게",)
    assert DEFAULT.lookup("earbuds")[0] == "이어폰"
    assert DEFAULT.lookup("Phone-Case") == ("폰케이스", "휴대폰케이스")
    assert DEFAULT.lookup("dishes") == ("접시",)
    assert DEFAULT.lookup("frobnicator") == ()


def test_translate_prefers_longest_phrase_and_drops_unknown_words():
    forms = DEFAULT.translate("multifunctional silicone kitchen tongs xyz set".split())
    assert forms == [("다기능", "다용도"), ("실리콘",), ("주방집게", "집게"), ("세트",)]


def test_korean_query_uses_preferred_forms_in_title_order():
    assert DEFAULT.korean_query("Silicone Kitchen Tongs Set".lower().split()) == "실리콘 주방집게 세트"
    assert DEFAULT.korean_query("Wireless Bluetooth Earbuds Black".lower().split()) == "무선 블루투스 이어폰 블랙"
    assert DEFAULT.korean_query(["frobnicator"]) == ""


def test_brand_names_are_normalised_to_korean_spelling():
    assert DEFAULT.brand("Sony") == "소니"
    assert DEFAULT.brand("소니") == "소니"
    assert DEFAULT.brand("Unknown Co") == "Unknown Co"


def test_csv_extends_builtin_terms_and_brands(tmp_path):
    path = tmp_path / "terms.csv"
    path.write_text(
        "english,korean\n"
        "# comment\n"
        "frobnicator,프로브니케이터|프로브\n"
        "tongs,집게|통스\n"
        "brand:Acme,아크메\n",
        encoding="utf-8",
    )
    g = load(str(path))
    assert g.lookup("frobnicators") == ("프로브니케이터", "프로브")
    assert g.lookup("tongs") == ("집게", "통스")
    assert g.brand("ACME") == "아크메"
    assert g.lookup("silicone") == ("실리콘",)  # built-in kept
    assert DEFAULT.lookup("frobnicator") == ()  # built-in untouched
    assert load(str(path)) is g  # cached


def test_bad_glossary_rows_are_config_errors(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("english,korean\nonly-one-column\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        DEFAULT.extended(path)
    with pytest.raises(ConfigError):
        DEFAULT.extended(tmp_path / "missing.csv")


def test_custom_glossary_can_be_built_from_scratch():
    g = Glossary({"widget": ("위젯",)}, {})
    assert g.lookup("widgets") == ("위젯",)
    assert g.lookup("tongs") == ()
