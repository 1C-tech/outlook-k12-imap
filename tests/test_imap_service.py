from app.services.imap_service import build_xoauth2_string


def test_build_xoauth2_string():
    value = build_xoauth2_string("user@example.com", "token")
    assert value == "user=user@example.com\x01auth=Bearer token\x01\x01"
