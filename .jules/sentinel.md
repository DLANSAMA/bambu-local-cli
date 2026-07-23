## 2024-05-24 - [Strict URL Credential Redaction]
**Vulnerability:** URL credentials were only redacted if a password attribute existed on the parsed URL. In HTTP Basic Auth, tokens are frequently provided as the username field without a password (e.g., https://[token-example]/). The previous redaction function leaked these token-based credentials into error logs.
**Learning:** Checking for just password is insufficient to protect bearer tokens or API keys passed via URL.
**Prevention:** Always verify both username and password components, and mask both entirely to prevent token leakage in structured logs.
