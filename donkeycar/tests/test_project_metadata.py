from configparser import ConfigParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_text(path):
    return path.read_text(encoding="utf-8")


def read_setup_metadata():
    parser = ConfigParser()
    parser.read(PROJECT_ROOT / "setup.cfg", encoding="utf-8")
    return parser["metadata"]


def test_license_uses_apache_2_as_primary_project_license():
    license_text = read_text(PROJECT_ROOT / "LICENSE")

    assert "Apache License" in license_text
    assert "Version 2.0" in license_text


def test_upstream_donkeycar_mit_license_is_preserved():
    mit_license = PROJECT_ROOT / "LICENSES" / "MIT-donkeycar.txt"

    assert mit_license.exists()
    text = read_text(mit_license)
    assert "MIT License" in text
    assert "Copyright (c) 2017 Will Roscoe" in text


def test_notice_documents_donkeydrifter_fork_status():
    notice = PROJECT_ROOT / "NOTICE"

    assert notice.exists()
    text = read_text(notice)
    assert "DonkeyDrifter" in text
    assert "Donkeycar" in text
    assert "MIT License" in text
    assert "Apache License 2.0" in text
    assert "not affiliated" in text.lower()


def test_third_party_notices_document_upstream_donkeycar():
    notices = PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"

    assert notices.exists()
    text = read_text(notices)
    assert "Donkeycar" in text
    assert "https://github.com/autorope/donkeycar" in text
    assert "MIT License" in text


def test_setup_metadata_uses_donkeydrifter_identity():
    metadata = read_setup_metadata()

    assert metadata["name"] == "donkeydrifter"
    assert metadata["author"] == "Haobot"
    assert metadata["author_email"] == "haobot2018@gmail.com"
    assert metadata["url"] == "https://github.com/DonkeyDrift/DonkeyDrifter"
    assert metadata["license"] == "Apache-2.0"
    assert "DonkeyDrifter" in metadata["description"]
    assert "donkeydrifter" in metadata["keywords"]
    assert "License :: OSI Approved :: Apache Software License" in metadata[
        "classifiers"
    ]


def test_readme_documents_donkeydrifter_identity_and_compatibility():
    readme = read_text(PROJECT_ROOT / "README.md")

    assert readme.startswith("# DonkeyDrifter")
    assert "pip install donkeydrifter" in readme
    assert "import donkeydrifter as dk" in readme
    assert "import donkeycar as dk" in readme
    assert "CLI command remains `donkey`" in readme
    assert "not affiliated" in readme.lower()
    assert "LICENSES/MIT-donkeycar.txt" in readme


def test_docs_include_compatibility_and_attribution_guides():
    compatibility = PROJECT_ROOT / "docs" / "guide" / "donkeycar-compatibility.md"
    attribution = PROJECT_ROOT / "docs" / "guide" / "license-and-attribution.md"

    assert compatibility.exists()
    assert attribution.exists()

    compatibility_text = read_text(compatibility)
    assert "import donkeydrifter as dk" in compatibility_text
    assert "import donkeycar as dk" in compatibility_text
    assert "CLI command remains `donkey`" in compatibility_text

    attribution_text = read_text(attribution)
    assert "Apache License 2.0" in attribution_text
    assert "MIT License" in attribution_text
    assert "LICENSES/MIT-donkeycar.txt" in attribution_text
    assert "not affiliated" in attribution_text.lower()


def test_agent_docs_describe_donkeydrifter_migration_contract():
    for relative_path in ("AGENTS.md", "CLAUDE.md"):
        text = read_text(PROJECT_ROOT / relative_path)
        assert "DonkeyDrifter" in text
        assert "donkeydrifter" in text
        assert "兼容" in text or "compatibility" in text.lower()
        assert "donkeycar" in text
        assert "CLI" in text
        assert "donkey" in text
        assert "Apache" in text
        assert "MIT" in text


def test_makefile_package_uses_modern_build_backend():
    makefile = read_text(PROJECT_ROOT / "Makefile")

    assert "python -m build --sdist --wheel" in makefile
    assert "python setup.py sdist" not in makefile


def test_python_ci_checks_donkeydrifter_import_and_build():
    workflow = read_text(
        PROJECT_ROOT / ".github" / "workflows" / "python-package-conda.yml"
    )

    assert "Python package and test DonkeyDrifter" in workflow
    assert "Install DonkeyDrifter" in workflow
    assert "import donkeydrifter; from donkeydrifter import Vehicle" in workflow
    assert "import donkeycar; from donkeycar import Vehicle" in workflow
    assert "python -m build --sdist --wheel" in workflow


def test_super_linter_workflow_uses_donkeydrifter_name():
    workflow = read_text(PROJECT_ROOT / ".github" / "workflows" / "superlinter.yml")

    assert "Lint DonkeyDrifter" in workflow


def test_torch_extra_pins_fastai_below_incompatible_2_8_series():
    parser = ConfigParser()
    parser.read(PROJECT_ROOT / "setup.cfg", encoding="utf-8")

    torch_extra = parser["options.extras_require"]["torch"]
    assert "torch==2.1.*" in torch_extra
    assert "fastai<2.8" in torch_extra


def test_pypi_trusted_publishing_workflow_is_configured():
    workflow_path = PROJECT_ROOT / ".github" / "workflows" / "publish-pypi.yml"

    assert workflow_path.exists()
    workflow = read_text(workflow_path)
    assert "Publish DonkeyDrifter to PyPI" in workflow
    assert "tags:" in workflow
    assert '"v*"' in workflow
    assert "id-token: write" in workflow
    assert "environment: pypi" in workflow
    assert "pypa/gh-action-pypi-publish@release/v1" in workflow
    assert "python -m build --sdist --wheel" in workflow
    assert "python -m twine check dist/*" in workflow
