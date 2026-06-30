"""Projection-config validation (PRD §11): a malformed config is a hard error
caught at load time, before any profile is processed — never silent data loss."""

import json

import pytest

from candidate_pipeline.config.loader import load_config
from candidate_pipeline.config.schema import ProjectionConfig


def _write(tmp_path, obj, *, bom=False):
    path = tmp_path / "cfg.json"
    data = json.dumps(obj).encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    path.write_bytes(data)
    return str(path)


def test_duplicate_output_path_is_rejected(tmp_path):
    cfg = {"fields": [
        {"path": "name", "from": "full_name"},
        {"path": "name", "from": "headline"},  # silently overwrote before -> now rejected
    ]}
    with pytest.raises(Exception, match="duplicate output path"):
        load_config(_write(tmp_path, cfg))


def test_empty_path_is_rejected(tmp_path):
    with pytest.raises(Exception, match="non-empty"):
        load_config(_write(tmp_path, {"fields": [{"path": "  "}]}))


def test_invalid_type_is_rejected(tmp_path):
    with pytest.raises(Exception):
        load_config(_write(tmp_path, {"fields": [{"path": "x", "type": "dict[]"}]}))


def test_invalid_on_missing_is_rejected(tmp_path):
    with pytest.raises(Exception):
        load_config(_write(tmp_path, {"on_missing": "skip", "fields": [{"path": "x"}]}))


def test_missing_fields_key_is_rejected(tmp_path):
    with pytest.raises(Exception):
        load_config(_write(tmp_path, {"on_missing": "null"}))


def test_bom_config_loads_cleanly(tmp_path):
    # A UTF-8 BOM must not break key matching (utf-8-sig).
    cfg = {"on_missing": "omit", "fields": [{"path": "name", "from": "full_name"}]}
    loaded = load_config(_write(tmp_path, cfg, bom=True))
    assert isinstance(loaded, ProjectionConfig)
    assert loaded.on_missing == "omit" and loaded.fields[0].path == "name"


def test_valid_config_still_loads(tmp_path):
    cfg = {"fields": [{"path": "a", "from": "full_name"}, {"path": "b", "from": "headline"}]}
    loaded = load_config(_write(tmp_path, cfg))
    assert [f.path for f in loaded.fields] == ["a", "b"]
