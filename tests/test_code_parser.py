from app.services.code_parser import parse_verification_code, strip_html


def test_parse_openai_code():
    assert parse_verification_code("OpenAI verification code", "Your code is 123456", "noreply@openai.com") == "123456"


def test_sender_filter():
    assert parse_verification_code("OpenAI verification code", "123456", "other@example.com") is None


def test_strip_html():
    assert strip_html("<p>Hello&nbsp;123456</p>") == "Hello 123456"

