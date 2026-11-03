"""Generate a local RS256 key pair for signing demo JWTs.

Output is gitignored - these keys are only meaningful to a locally running
instance of this project and sign nothing of any real value.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from banking_api.config import settings  # noqa: E402


def main() -> None:
    private_path = Path(settings.jwt_private_key_path)
    public_path = Path(settings.jwt_public_key_path)
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)

    if private_path.exists() and public_path.exists():
        print(f"Key pair already exists at {private_path} / {public_path}, leaving as is.")
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path.write_bytes(private_bytes)
    private_path.chmod(0o600)
    public_path.write_bytes(public_bytes)

    print(f"Generated RS256 key pair:\n  {private_path}\n  {public_path}")


if __name__ == "__main__":
    main()
