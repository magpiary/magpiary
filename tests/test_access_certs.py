"""Phone access: the certificate authority, the server certificate, paired phones and the log."""

import os
import ssl
import stat
from datetime import timedelta

import pytest
from cryptography import x509

from magpiary import access
from magpiary.store import Store


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_ca_is_private_name_constrained_and_a_ca(tmp_path):
    ca = access.ca_certificate(tmp_path)
    assert mode(tmp_path / "ca.key") == 0o600 and mode(tmp_path) == 0o700
    nc = ca.extensions.get_extension_for_class(x509.NameConstraints)
    assert nc.critical and [n.value for n in nc.value.permitted_subtrees] == [".local"]
    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is True
    assert access.ca_certificate(tmp_path).fingerprint(ca.signature_hash_algorithm) == ca.fingerprint(ca.signature_hash_algorithm)  # reused, not remade


def test_server_cert_under_398_days_only_local_names_and_verifies(tmp_path):
    cert_path, key_path = access.server_files(["Maniks-Mac.local", "evil.com"], tmp_path)
    assert mode(key_path) == 0o600
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    assert cert.not_valid_after_utc - cert.not_valid_before_utc < timedelta(days=398)
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    assert sorted(san) == ["magpiary.local", "maniks-mac.local"]  # a name outside .local is never put in
    ctx = ssl.create_default_context(cadata=access.ca_pem(tmp_path).decode())
    ctx.load_cert_chain(cert_path, key_path)  # key matches the certificate


def test_server_cert_kept_until_names_change(tmp_path):
    a, _ = access.server_files(["a.local"], tmp_path)
    before = a.read_bytes()
    access.server_files(["a.local"], tmp_path)
    assert a.read_bytes() == before
    access.server_files(["b.local"], tmp_path)
    assert a.read_bytes() != before


def test_fingerprint_shape(tmp_path):
    fp = access.ca_fingerprint(tmp_path)
    assert len(fp.split(" ")) == 32 and fp == fp.upper()


@pytest.fixture
def devices(tmp_path):
    return access.Devices(Store(tmp_path / "a.db"))


def test_pair_check_revoke_and_log(devices):
    did, key = devices.add("  My   iPhone ")
    assert devices.check(key)["name"] == "My iPhone"
    assert devices.check("wrong") is None and devices.check("") is None
    assert devices.touch(did, "192.168.1.9") is True and devices.touch(did, "192.168.1.9") is False
    assert devices.revoke(did) and devices.check(key) is None
    kinds = [r["kind"] for r in devices.recent()]
    assert kinds == ["revoked", "connected", "paired"]
    assert key not in repr(devices.recent())


def test_pair_token_single_use_and_expires(devices):
    t = devices.new_pair_token(clock=0)
    assert devices.pair_token_valid(t, clock=1)
    assert devices.spend_pair_token(t, clock=1) and not devices.spend_pair_token(t, clock=2)
    t2 = devices.new_pair_token(clock=0)
    assert not devices.spend_pair_token(t2, clock=access.PAIR_FOR + 1)


def test_private_addresses_only():
    assert access.is_private_address("192.168.1.5") and access.is_private_address("::ffff:10.0.0.2")
    assert access.is_private_address("fe80::1%en0")
    assert not access.is_private_address("8.8.8.8") and not access.is_private_address("nonsense")
