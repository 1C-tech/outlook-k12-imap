# outlook-k12-imap

FastAPI + SQLite backend for importing Outlook OAuth2 mailbox accounts, running OpenAI registration tasks, polling OpenAI email OTP by IMAP, and submitting the configured K12 workspace invite.

## Start

```bash
pip install -r requirements.txt
python -m app.main
```

Open `http://127.0.0.1:8000`. The default admin password is `admin`.

## Account Import Format

```text
email----password----client_id----refresh_token
```

`client_id` and `refresh_token` are used to exchange an Outlook IMAP OAuth2 access token, then read the OpenAI verification email.

## Registration Providers

- `mock`: local test flow, no real OpenAI request.
- `openai`: real OpenAI email registration flow.

The `openai` provider requires `curl_cffi` and a compatible `utils.auth_core` binary from the referenced `openai-cpa` checkout. Configure it in `config.yaml`:

```yaml
registration:
  provider: openai
  proxy: ""
  auth_core_path: F:/game/openai-cpa/openai-cpa-main
```

The current bundled reference `auth_core.pyd` may not load under every Python version. If startup tasks fail with `OpenAI auth_core could not be loaded`, run this project with a Python version supported by that binary or provide a compatible `auth_core` build.

Phone verification is intentionally not integrated in this version. If OpenAI redirects to phone verification, the task is marked `failed` with `phone_verification_required`.
