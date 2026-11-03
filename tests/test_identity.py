"""Identity and profile (M9 task 2): one key pair per Mac, made on first use, and a name, photo and colour."""

import base64
import stat

import pytest

from magpiary import identity
from magpiary.config import config_dir
from test_hub import page, post, request


def test_the_key_is_made_once_kept_private_and_signs():
    assert not identity.exists()
    public = identity.public_key()
    path = config_dir() / "identity.key"
    assert identity.exists() and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert identity.public_key() == public and len(public) == 64  # the same key every time
    sig = identity.sign(b"add a card")
    assert identity.verify(public, b"add a card", sig)
    assert not identity.verify(public, b"add another card", sig)
    assert not identity.verify("00" * 32, b"add a card", sig) and not identity.verify(public, b"x", "nonsense")
    assert identity.short_id(public).count("-") == 2


def test_a_damaged_key_is_never_replaced_silently():
    path = config_dir() / "identity.key"
    path.parent.mkdir(parents=True)
    path.write_text("not a key")
    with pytest.raises(RuntimeError):
        identity.public_key()
    assert path.read_text() == "not a key"


def test_the_profile_page_shows_the_card_and_saves_name_and_colour(mac):
    body = page(mac, "/settings/profile")[2]
    assert "Your profile" in body and "Your name" in body and 'id="photopick"' in body and "Your key" in body
    assert identity.short_id() in body  # the key is made when it is first needed
    post(mac, "/hub/profile", name="  Alex   Example  ", next="/settings/profile")
    post(mac, "/hub/profile", colour="#2f6bff", next="/settings/profile")
    post(mac, "/hub/profile", colour="javascript:alert(1)", next="/settings/profile")  # not one of ours: ignored
    me = identity.profile(mac.store)
    assert me["name"] == "Alex Example" and me["colour"] == "#2f6bff"
    body = page(mac, "/settings/profile")[2]
    assert "<span>AE</span>" in body and 'class="swatch on" style="--c:#2f6bff"' in body
    assert "Alex Example" in page(mac, "/settings/ai")[2]  # the section's status in the list


def test_a_photo_is_shrunk_on_the_mac_and_can_be_removed(mac):
    shrunk = []

    def fake_shrink(src, dst):
        shrunk.append(src.read_bytes())
        dst.write_bytes(b"\xff\xd8 a small jpeg")
        return True
    url = "data:image/png;base64," + base64.b64encode(b"\x89PNG picture").decode()
    assert identity.set_photo(url, fake_shrink) is None and shrunk == [b"\x89PNG picture"]
    assert identity.photo_path().read_bytes() == b"\xff\xd8 a small jpeg"
    assert identity.set_photo("data:text/html;base64,PGI+", fake_shrink) == "Pick a photo (JPEG, PNG or WebP)."
    assert identity.set_photo("data:image/jpeg;base64,???", fake_shrink) == "That photo could not be read."
    big = "data:image/jpeg;base64," + base64.b64encode(b"x" * (identity.PHOTO_MAX + 1)).decode()
    assert identity.set_photo(big, fake_shrink) == "That photo is too large."
    assert identity.set_photo(url, lambda s, d: False) == "That photo could not be read."

    status, headers, body = request(mac, "GET", "/profile/photo.jpg")
    assert status == 200 and body == b"\xff\xd8 a small jpeg"
    assert "/profile/photo.jpg?v=" in page(mac, "/settings/profile")[2]
    status, headers, _ = post(mac, "/hub/profile/photo/remove", next="/settings/profile")
    assert headers["Location"] == "/settings/profile?saved=nophoto" and not identity.photo_path().exists()
    assert request(mac, "GET", "/profile/photo.jpg")[0] == 404


def test_a_bad_photo_upload_comes_back_with_the_reason(mac):
    status, headers, _ = post(mac, "/hub/profile/photo", photo="data:text/plain;base64,aGk=", next="/settings/profile")
    assert status == 303 and "error=Pick%20a%20photo" in headers["Location"]
