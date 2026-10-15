"""The sole browser-facing Auth API revision and pinned OAuth return boundary.

Authorization/resource policy versions are independent of the HTTP API major
version. Provider callback is a separately registered OAuth client redirect;
do not infer its URL from the BFF version or silently rewrite it on upgrade.
"""

API_V1_PREFIX = "/api/v1"
AUTH_API_PREFIX = API_V1_PREFIX + "/auth"
REGISTERED_RAUTHY_CALLBACK_PATH = "/api/auth/oidc/callback"
