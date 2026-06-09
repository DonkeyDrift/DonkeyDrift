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
    assert metadata["author"] == "DonkeyDrifter contributors"
    assert metadata["url"] == "https://gitee.com/ffedu/donkeydrifter"
    assert metadata["license"] == "Apache-2.0"
    assert "DonkeyDrifter" in metadata["description"]
    assert "donkeydrifter" in metadata["keywords"]
    assert "License :: OSI Approved :: Apache Software License" in metadata[
        "classifiers"
    ]
