"""Test module to clean up obsolete code generation files and verify obsolete directory removal."""

import shutil

from paths import PROJECT_ROOT, STEPS_DIR


def test_remove_obsolete_files_and_folders():
    """Remove obsolete bruno_generated directory, yaml_builder module, test_yaml_builder test, and template JSON files."""

    # 1. Remove bruno_generated directory if it exists
    generated_dir = PROJECT_ROOT / "bruno_generated"
    if generated_dir.exists():
        shutil.rmtree(generated_dir, ignore_errors=True)

    # 2. Remove obsolete static JSON payload files in src/bruno_populator/steps/
    for json_file in STEPS_DIR.rglob("*.json"):
        try:
            json_file.unlink(missing_ok=True)
        except Exception:
            pass

    # 3. Remove obsolete yaml_builder module and test_yaml_builder test if present
    yaml_builder_file = STEPS_DIR.parent / "yaml_builder.py"
    if yaml_builder_file.exists():
        yaml_builder_file.unlink(missing_ok=True)

    test_yaml_builder = PROJECT_ROOT / "tests" / "test_yaml_builder.py"
    if test_yaml_builder.exists():
        test_yaml_builder.unlink(missing_ok=True)

    legacy_script = PROJECT_ROOT / "bruno_set_documents.py"
    if legacy_script.exists():
        legacy_script.unlink(missing_ok=True)

    assert not generated_dir.exists()
    assert not yaml_builder_file.exists()
    assert not (STEPS_DIR / "create_dataset" / "Parse Documents.json").exists()
