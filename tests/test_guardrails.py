import zipfile

from agent.guardrails import check_step, mask_secrets, resolve_placeholders, scrub_zip
from agent.models import Step, Target

BASE = "http://127.0.0.1:5055"


def test_destructive_click_is_refused():
    step = Step(action="click", target=Target(role="button", name="Delete post"))
    assert "destructive" in check_step(step, BASE)


def test_navigation_outside_stage_is_refused():
    assert "outside Stage" in check_step(Step(action="goto", path="https://prod.example.com/blogs"), BASE)
    assert check_step(Step(action="goto", path="/admin/reset"), BASE)


def test_normal_steps_are_allowed():
    assert check_step(Step(action="click", target=Target(role="button", name="Log in")), BASE) is None
    assert check_step(Step(action="goto", path="/blogs"), BASE) is None


def test_placeholders_and_masking():
    assert resolve_placeholders("${STAGE_USER}/${STAGE_PASSWORD}", "alice", "s3cret") == "alice/s3cret"
    assert "s3cret" not in mask_secrets("password=s3cret", ["s3cret"])


def test_scrub_zip_masks_raw_and_url_encoded(tmp_path):
    archive = tmp_path / "trace.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.trace", '{"value": "p@ss word"}')
        zf.writestr("b.network", "username=alice&password=p%40ss+word")
    scrub_zip(archive, ["p@ss word"])
    with zipfile.ZipFile(archive) as zf:
        blob = b"".join(zf.read(n) for n in zf.namelist())
    assert b"p@ss word" not in blob and b"p%40ss+word" not in blob
