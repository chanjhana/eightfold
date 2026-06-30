"""skill normalizer (PRD §6, edge case §15 #6).

The critical contract: C++ / C# / .NET survive intact (never collapse to "c"),
ReactJS -> React, unknown skills kept verbatim and flagged.
"""

import pytest

from candidate_pipeline.normalize.skills import canonicalize_skill, split_skills


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ReactJS", "React"),
        ("react.js", "React"),
        ("node.js", "Node.js"),
        ("nodejs", "Node.js"),
        ("py", "Python"),
        ("C++", "C++"),
        ("c++", "C++"),
        ("C#", "C#"),
        (".NET", ".NET"),
    ],
)
def test_canonicalization_table(raw, expected):
    r = canonicalize_skill(raw)
    assert r.value == expected
    assert r.is_canonical is True
    assert r.flag is None


def test_unknown_skill_kept_verbatim_and_flagged():
    r = canonicalize_skill("Wizardry")
    assert r.value == "Wizardry"
    assert r.is_canonical is False
    assert r.flag is not None
    assert r.flag.kind == "uncanonicalized_skill"


def test_cpp_does_not_collapse_to_c():
    assert canonicalize_skill("C++").value == "C++"
    assert canonicalize_skill("C#").value == "C#"


def test_split_handles_commas_and_semicolons():
    assert split_skills("ReactJS, node.js; C++ ") == ["ReactJS", "node.js", "C++"]
