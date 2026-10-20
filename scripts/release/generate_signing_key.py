# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""One-time: create the Ed25519 key pair used to sign update manifests.

Writes the PUBLIC key to assets/update_public_key.txt (ships inside the app) and prints the
PRIVATE key — store it as the GitHub Actions secret VERBATIM_SIGNING_KEY and nowhere else.
Once a public key is bundled, the app refuses any update manifest not signed with it.
"""
import base64
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

k = Ed25519PrivateKey.generate()
priv = base64.b64encode(k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                        serialization.NoEncryption())).decode()
pub = base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
Path(__file__).resolve().parents[2].joinpath("assets", "update_public_key.txt").write_text(pub + "\n")
print("Public key written to assets/update_public_key.txt")
print("\nPRIVATE KEY (add as GitHub secret VERBATIM_SIGNING_KEY, never commit it):\n" + priv)
