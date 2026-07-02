from app.database import init_db
from app.services.account_service import import_accounts, list_accounts, parse_account_line


def test_parse_account_line():
    parsed = parse_account_line("User@Outlook.com----pwd----cid----rt")
    assert parsed == ("user@outlook.com", "pwd", "cid", "rt")


def test_import_accounts_counts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    init_db()
    raw = """
    # comment
    one@example.com----pwd----cid----rt
    bad-line
    one@example.com----pwd----cid----rt
    two@example.com----pwd----cid----rt
    """
    result = import_accounts(raw)
    assert result.count == 2
    assert result.duplicated == 1
    assert result.failed == 1
    assert list_accounts()["total"] == 2

