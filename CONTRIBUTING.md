# Contributing

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check . && pytest
```

- Only `balesdk/_aiobale.py` may import `aiobale`. Everything else talks to the
  `Transport` protocol, so tests use `balesdk.testing.FakeTransport` and need
  no network.
- Errors carry a stable `code`; never put text received from Bale into one.
- Please do not paste a real `.bale` file, a login code, or a phone number into
  an issue.
