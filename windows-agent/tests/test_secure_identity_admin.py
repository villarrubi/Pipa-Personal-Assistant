import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from secure_identity_admin import _details, _firmware_snippet, main  # noqa: E402
from secure_session import SecureIdentity  # noqa: E402


class SecureIdentityAdminTests(unittest.TestCase):
    def test_public_details_and_firmware_snippet_never_contain_private_key(self):
        identity = SecureIdentity("pipa-agent-v2", Ed25519PrivateKey.generate())

        details = _details(identity)
        snippet = _firmware_snippet(identity)

        self.assertEqual(set(details), {"identity_id", "public_key", "fingerprint"})
        self.assertIn(details["public_key"], snippet)
        self.assertIn("PIPA_SECURE_SESSION_ENABLED 1", snippet)
        self.assertNotIn(identity.private_key.private_bytes_raw().hex(), snippet)

    @patch(
        "secure_identity_admin.default_secure_identity_path",
        return_value=Path("private-identity.json"),
    )
    @patch("secure_identity_admin.SecureIdentityStore")
    def test_show_output_does_not_include_the_local_storage_path(self, store_type, _path):
        identity = SecureIdentity("pipa-agent-v2", Ed25519PrivateKey.generate())
        store_type.return_value.load.return_value = identity
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(["show"])

        self.assertEqual(exit_code, 0)
        self.assertNotIn("private-identity.json", output.getvalue())
        self.assertIn('"identity_id": "pipa-agent-v2"', output.getvalue())


if __name__ == "__main__":
    unittest.main()
