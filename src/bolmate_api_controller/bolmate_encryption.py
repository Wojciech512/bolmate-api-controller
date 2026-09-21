import binascii
import hashlib
import logging
import traceback

from Crypto import Random
from Crypto.Cipher import AES
from bolmate_api_controller.settings import get_settings


class DecryptionError(Exception):
    pass


class EncryptData:
    def __init__(self, *, secret: str | None = None, encryption_value: str | None = None,
                 iterations: int | None = None):
        self.logger = logging.getLogger(EncryptData.__name__)
        self._secret = secret
        self._encryption_value = encryption_value
        self._iterations = iterations

    def encrypt(self, *, plaintext: str):
        try:
            if plaintext is None:
                return plaintext
            salt = Random.get_random_bytes(16)
            key = self._generate_key(salt)
            cipher = AES.new(key, AES.MODE_ECB)
            padded_plaintext = self._pad_text(plaintext, 16)
            ciphertext = cipher.encrypt(self._encode(padded_plaintext))
            ciphertext_with_salt = salt + ciphertext
            if len(ciphertext_with_salt) % 16 != 0:
                raise ValueError(
                    "ciphertext_with_salt does not have a correct length")
            return binascii.hexlify(ciphertext_with_salt).decode()
        except:
            self.logger.error(
                "Could not encrypt reason: {}".format(traceback.format_exc()))
        return None

    def decrypt(self, *, encrypted_text: str):
        if not encrypted_text:
            return encrypted_text
        orig_cipher = encrypted_text
        if encrypted_text is not None:
            encrypted_text = encrypted_text.strip()
        try:
            encrypted_text = encrypted_text.encode()
            encrypted_text = binascii.unhexlify(encrypted_text)
            salt = encrypted_text[:16]
            ciphertext_sans_salt = encrypted_text[16:]
            key = self._generate_key(salt)
            cipher = AES.new(key, AES.MODE_ECB)
            padded_plaintext = cipher.decrypt(ciphertext_sans_salt)
            plaintext = self._unpad_text(padded_plaintext)
            return self._decode(plaintext)
        except binascii.Error:
            return orig_cipher
        except Exception:
            return orig_cipher

    def decrypt_strict(self, *, encrypted_text: str) -> str:
        if not encrypted_text:
            raise DecryptionError('No encrypted text given')
        try:
            raw = binascii.unhexlify(encrypted_text.strip().encode())
        except binascii.Error as exc:
            raise DecryptionError('Encrypted text is not valid hex') from exc
        if len(raw) < 32 or len(raw) % 16 != 0:
            raise DecryptionError('Encrypted text has an invalid length')
        salt = raw[:16]
        ciphertext_sans_salt = raw[16:]
        key = self._generate_key(salt)
        cipher = AES.new(key, AES.MODE_ECB)
        padded_plaintext = cipher.decrypt(ciphertext_sans_salt)
        padding_size = padded_plaintext[-1]
        if not 1 <= padding_size <= 16 or len(padded_plaintext) < padding_size:
            raise DecryptionError('Decryption produced invalid padding (wrong key material?)')
        padding = padded_plaintext[-padding_size:]
        if any(byte != padding[0] for byte in padding):
            raise DecryptionError('Decryption produced invalid padding (wrong key material?)')
        return self._decode(padded_plaintext[:-padding_size])

    def _generate_key(self, salt: bytes):
        if self._secret is not None and self._encryption_value is not None and self._iterations is not None:
            encryption_value = self._encryption_value
            secret_value = self._secret
            iterations = self._iterations
        else:
            settings = get_settings()
            encryption_value = settings.bolmate_encryption_value
            secret_value = settings.bolmate_encrypt_secret
            iterations = settings.bolmate_encryption_iterations
        key = encryption_value.encode('utf-8') + salt
        secret = secret_value.encode('utf-8')
        for i in range(iterations):
            key = hashlib.sha256(key + secret).digest()
        return key

    def _pad_text(self, text, multiple):
        extra_bytes = len(text.encode()) % multiple
        padding_size = multiple - extra_bytes
        padding = chr(padding_size) * padding_size
        padded_text = text + padding
        return padded_text

    def _unpad_text(self, padded_text):
        padding_size = padded_text[-1]
        text = padded_text[:-padding_size]
        return text

    def _encode(self, plaintext: str) -> bytes:
        try:
            return plaintext.encode('utf-8')
        except UnicodeEncodeError:
            return plaintext.encode('latin-1')

    def _decode(self, encoded: bytes) -> str:
        try:
            return encoded.decode('utf-8')
        except UnicodeDecodeError:
            return encoded.decode('latin-1')


def decrypt(*, encrypted_text: str, secret: str, encryption_value: str, iterations: int) -> str:
    encryptor = EncryptData(secret=secret, encryption_value=encryption_value, iterations=iterations)
    return encryptor.decrypt_strict(encrypted_text=encrypted_text)


enc_data = EncryptData()
