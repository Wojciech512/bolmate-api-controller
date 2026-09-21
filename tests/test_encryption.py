import pytest

from bolmate_api_controller import DecryptionError, decrypt
from bolmate_api_controller.bolmate_encryption import EncryptData

SECRET = 'test-secret'
ENCRYPTION_VALUE = 'test-value'
ITERATIONS = 7


def make_encryptor(**overrides) -> EncryptData:
    params = {'secret': SECRET, 'encryption_value': ENCRYPTION_VALUE, 'iterations': ITERATIONS}
    params.update(overrides)
    return EncryptData(**params)


def test_roundtrip_with_explicit_key_material():
    encryptor = make_encryptor()
    ciphertext = encryptor.encrypt(plaintext='Jan Jansen, Hoofdstraat 1')
    assert ciphertext is not None
    assert decrypt(encrypted_text=ciphertext, secret=SECRET,
                   encryption_value=ENCRYPTION_VALUE, iterations=ITERATIONS) == 'Jan Jansen, Hoofdstraat 1'


def test_decrypt_strict_rejects_the_wrong_secret():
    ciphertext = make_encryptor().encrypt(plaintext='confidential buyer data')
    with pytest.raises(DecryptionError):
        decrypt(encrypted_text=ciphertext, secret='wrong-secret',
                encryption_value=ENCRYPTION_VALUE, iterations=ITERATIONS)


def test_decrypt_strict_rejects_non_hex_input():
    with pytest.raises(DecryptionError):
        decrypt(encrypted_text='not hex at all', secret=SECRET,
                encryption_value=ENCRYPTION_VALUE, iterations=ITERATIONS)


def test_decrypt_strict_rejects_empty_input():
    with pytest.raises(DecryptionError):
        decrypt(encrypted_text='', secret=SECRET,
                encryption_value=ENCRYPTION_VALUE, iterations=ITERATIONS)


def test_decrypt_strict_rejects_truncated_input():
    ciphertext = make_encryptor().encrypt(plaintext='confidential buyer data')
    with pytest.raises(DecryptionError):
        decrypt(encrypted_text=ciphertext[:30], secret=SECRET,
                encryption_value=ENCRYPTION_VALUE, iterations=ITERATIONS)


def test_legacy_decrypt_still_returns_input_on_failure():
    encryptor = make_encryptor()
    assert encryptor.decrypt(encrypted_text='not hex at all') == 'not hex at all'


def test_legacy_decrypt_roundtrip_unchanged():
    encryptor = make_encryptor()
    ciphertext = encryptor.encrypt(plaintext='plain roundtrip')
    assert encryptor.decrypt(encrypted_text=ciphertext) == 'plain roundtrip'


def test_ambient_settings_are_untouched_when_key_material_is_explicit():
    ciphertext = make_encryptor().encrypt(plaintext='no config.ini needed')
    assert decrypt(encrypted_text=ciphertext, secret=SECRET,
                   encryption_value=ENCRYPTION_VALUE, iterations=ITERATIONS) == 'no config.ini needed'
