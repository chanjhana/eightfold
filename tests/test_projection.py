"""Projection layer (PRD §11): config-driven output, assert-only normalize."""

import pytest

from candidate_pipeline.config.loader import DEFAULT_CONFIG, load_config
from candidate_pipeline.config.schema import FieldSpec, ProjectionConfig
from candidate_pipeline.project.projector import ProjectionError, project
from candidate_pipeline.project.validator import build_output_model, validate_output


# ---- default config --------------------------------------------------------

def test_default_config_shapes(built_profiles):
    profiles, _ = built_profiles
    out = project(profiles["Aisha Khan"], DEFAULT_CONFIG)
    assert out["full_name"] == "Aisha Khan"  # plain string
    assert out["emails"] == ["aisha.khan@example.com"]  # string[]
    assert isinstance(out["location"], dict) and out["location"]["country"] == "US"
    assert isinstance(out["years_experience"], (int, float))
    # skills as {name, confidence, sources[]}
    py = next(s for s in out["skills"] if s["name"] == "Python")
    # 3-source corroboration: ATS(0.90) + CSV(+0.025) + GitHub repo lang(+0.05)
    assert py["confidence"] == pytest.approx(0.975, abs=1e-6)
    assert "ats_json" in py["sources"] and "github_api" in py["sources"]
    # links assembled
    assert out["links"]["github"] == "https://github.com/aishakhan"
    # include_flags -> flags present
    assert any(f["kind"] == "conflict_resolved" for f in out["flags"])


def test_default_provenance_aggregate(built_profiles):
    profiles, _ = built_profiles
    out = project(profiles["Aisha Khan"], DEFAULT_CONFIG)
    assert isinstance(out["provenance"], list) and out["provenance"]
    entry = out["provenance"][0]
    assert set(entry) == {"field", "source", "method"}


# ---- custom config: renames, from-defaults, include flags ------------------

def test_custom_config_renames_and_inline_confidence(configs_dir, built_profiles):
    profiles, _ = built_profiles
    cfg = load_config(str(configs_dir / "custom_config.json"))
    out = project(profiles["Aisha Khan"], cfg)
    # renamed full_name -> name, include_confidence -> wrapped
    assert out["name"]["value"] == "Aisha Khan"
    assert out["name"]["confidence"] == pytest.approx(0.975, abs=1e-6)
    assert out["primary_email"] == "aisha.khan@example.com"  # emails[0]
    assert out["primary_phone"] == "+14155552671"
    # skills[].name -> plain string[]
    assert "Python" in out["skill_names"] and "C++" in out["skill_names"]
    # include_provenance on location
    assert "provenance" in out["location"]


def test_from_defaults_to_path(built_profiles):
    profiles, _ = built_profiles
    cfg = ProjectionConfig(fields=[FieldSpec(path="full_name", type="string")])
    out = project(profiles["Aisha Khan"], cfg)
    assert out["full_name"] == "Aisha Khan"


# ---- normalize is assert-only ---------------------------------------------

def test_unsatisfiable_normalize_treated_as_missing(built_profiles):
    profiles, _ = built_profiles
    # assert full_name is iso3166-a2 -> it isn't -> missing -> null
    cfg = ProjectionConfig(
        on_missing="null",
        fields=[FieldSpec(path="full_name", type="string", normalize="iso3166-a2")],
    )
    out = project(profiles["Aisha Khan"], cfg)
    assert out["full_name"] is None


def test_satisfiable_normalize_passes(built_profiles):
    profiles, _ = built_profiles
    cfg = ProjectionConfig(
        fields=[FieldSpec(path="phone", from_="phones[0]", type="string", normalize="E164")]
    )
    out = project(profiles["Aisha Khan"], cfg)
    assert out["phone"] == "+14155552671"


# ---- on_missing semantics --------------------------------------------------

def test_required_missing_raises(built_profiles):
    profiles, _ = built_profiles
    cfg = ProjectionConfig(
        fields=[FieldSpec(path="nope", from_="headline", type="string", required=True)]
    )
    # Jordan Lee has a headline; orphan/sparse without -> use a guaranteed-missing path
    cfg2 = ProjectionConfig(
        fields=[FieldSpec(path="ssn", from_="does_not_exist", type="string", required=True)]
    )
    with pytest.raises(ProjectionError):
        project(profiles["Aisha Khan"], cfg2)


def test_on_missing_omit_drops_key(built_profiles):
    profiles, _ = built_profiles
    cfg = ProjectionConfig(
        fields=[FieldSpec(path="x", from_="does_not_exist", type="string", on_missing="omit")]
    )
    out = project(profiles["Aisha Khan"], cfg)
    assert "x" not in out


def test_on_missing_null_emits_none(built_profiles):
    profiles, _ = built_profiles
    cfg = ProjectionConfig(
        fields=[FieldSpec(path="x", from_="does_not_exist", type="string", on_missing="null")]
    )
    out = project(profiles["Aisha Khan"], cfg)
    assert out["x"] is None


# ---- output validation -----------------------------------------------------

def test_build_model_and_validate(built_profiles):
    profiles, _ = built_profiles
    out = project(profiles["Aisha Khan"], DEFAULT_CONFIG)
    model = build_output_model(DEFAULT_CONFIG)
    validated = validate_output(out, model)  # should not raise
    assert validated["candidate_id"].startswith("cand_")


# ---- loader ----------------------------------------------------------------

def test_loader_rejects_malformed(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{ "fields": [ { "type": "string" } ] }', encoding="utf-8")  # field missing path
    with pytest.raises(Exception):
        load_config(str(bad))
