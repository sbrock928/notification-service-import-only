from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from notification_service import (
    AllowedEmailDomainsPolicy,
    Attachment,
    EmailNotification,
    NotificationTable,
    Recipient,
    TableRenderPolicy,
    TeamsNotification,
    ValidationError,
)
from notification_service.presentation.email import render_email
from notification_service.presentation.tables import bound_tables, reduce_largest_row_limit


def email(**changes: object) -> EmailNotification:
    values: dict[str, object] = {
        "to": (Recipient("ops@Contoso.COM"),),
        "subject": "Import exceptions",
        "text": "Inspect the records.",
    }
    values.update(changes)
    return EmailNotification(**values)  # type: ignore[arg-type]


def test_models_are_normalized_immutable_and_fingerprinted() -> None:
    mutable = bytearray(b"report")
    attachment = Attachment("cafe\u0301.txt", "text/plain", mutable)
    table = NotificationTable(columns=["ID", "Reason"], rows=[["1", "bad"]])  # type: ignore[arg-type]
    message = email(attachments=(attachment,), tables=(table,))
    mutable[:] = b"change"

    assert message.to[0].address == "ops@contoso.com"
    assert attachment.filename == "caf\u00e9.txt"
    assert attachment.content == b"report"
    assert len(message.fingerprint) == 64
    with pytest.raises(FrozenInstanceError):
        message.text = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "address",
    ["not-an-address", "name <a@b.com>", "t\u00e9st@example.com", "a@localhost", "a@-bad.com"],
)
def test_recipient_rejects_unsupported_mailboxes(address: str) -> None:
    with pytest.raises(ValidationError):
        Recipient(address)


@pytest.mark.parametrize(
    "filename",
    ["", ".", "../x", "a/b", "a\\b", "CON", "com1.txt", "bad. ", "bad?.txt", "x\n.txt"],
)
def test_attachment_rejects_unsafe_filenames(filename: str) -> None:
    with pytest.raises(ValidationError):
        Attachment(filename, "text/plain", b"x")


def test_attachment_from_path_is_bounded(tmp_path: object) -> None:
    path = tmp_path / "value.txt"  # type: ignore[operator]
    path.write_bytes(b"value")
    assert Attachment.from_path(path, "text/plain").content == b"value"


def test_email_validation_and_duplicate_recipient_policy() -> None:
    with pytest.raises(ValidationError, match="Duplicate"):
        email(cc=(Recipient("OPS@contoso.com"),))
    with pytest.raises(ValidationError, match=r"plain|text"):
        email(text="")
    with pytest.raises(ValidationError, match="Subject"):
        email(subject="bad\nsubject")
    with pytest.raises(ValidationError, match="20 MiB"):
        email(attachments=(Attachment("a", "x/y", b"x" * (10 * 1024**2)),) * 3)


def test_table_validation_limits_and_shape() -> None:
    with pytest.raises(ValidationError, match="1-50"):
        NotificationTable(columns=())
    with pytest.raises(ValidationError, match="column count"):
        NotificationTable(columns=("A", "B"), rows=(("only one",),))
    with pytest.raises(ValidationError, match="4096"):
        NotificationTable(columns=("A",), rows=(("x" * 4097,),))
    with pytest.raises(ValidationError, match="three"):
        email(tables=(NotificationTable(columns=("A",)),) * 4)


def test_email_renderer_escapes_cells_and_reports_exact_omissions() -> None:
    table = NotificationTable(
        caption="Exceptions <today>",
        columns=("A", "B", "C"),
        rows=(("<script>", "2", "3"), ("4", "5", "6")),
    )
    rendered = render_email(
        email(tables=(table,)),
        TableRenderPolicy(max_rows=1, max_columns=2),
    )

    assert rendered.html is not None
    assert "&lt;script&gt;" in rendered.html
    assert "<script>" not in rendered.html
    assert "1 row(s) and 1 column(s)" in rendered.text


def test_simple_messages_do_not_gain_table_markup() -> None:
    message = email()
    rendered = render_email(message)
    assert rendered.text == message.text
    assert rendered.html is None
    assert TeamsNotification(destination="ops", text="simple").tables == ()


def test_html_requires_plain_fallback_and_is_preserved_as_trusted_input() -> None:
    rendered = render_email(email(html="<p>Trusted</p>"))
    assert rendered.html == "<p>Trusted</p>"
    with pytest.raises(ValidationError):
        email(text="", html="<p>Only</p>")


def test_exact_domain_policy() -> None:
    policy = AllowedEmailDomainsPolicy({"Contoso.COM."})
    policy.validate(email())
    with pytest.raises(ValidationError):
        policy.validate(email(to=(Recipient("ops@sub.contoso.com"),)))
    with pytest.raises(ValueError):
        AllowedEmailDomainsPolicy({"com"})


def test_attachment_content_media_and_size_validation() -> None:
    with pytest.raises(ValidationError, match="media"):
        Attachment("x.txt", "invalid", b"x")
    with pytest.raises(ValidationError, match="bytes-like"):
        Attachment("x.txt", "text/plain", object())  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="10 MiB"):
        Attachment("x.txt", "text/plain", b"x" * (10 * 1024**2 + 1))


def test_remaining_email_collection_and_body_limits() -> None:
    with pytest.raises(ValidationError, match="recipient"):
        EmailNotification(to=(), subject="x", text="x")
    with pytest.raises(ValidationError, match="Recipient"):
        EmailNotification(to=("not-recipient",), subject="x", text="x")  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="1 MiB"):
        email(text="x" * (1024**2 + 1))
    with pytest.raises(ValidationError, match="HTML"):
        email(html="x" * (1024**2 + 1))
    small = Attachment("x.txt", "text/plain", b"x")
    with pytest.raises(ValidationError, match="10 attachments"):
        email(attachments=(small,) * 11)
    with pytest.raises(ValidationError, match="Attachment values"):
        email(attachments=(object(),))


def test_remaining_table_and_teams_validation() -> None:
    with pytest.raises(ValidationError, match="headings"):
        NotificationTable(columns=("",))
    with pytest.raises(ValidationError, match="captions"):
        NotificationTable(columns=("A",), caption="")
    with pytest.raises(ValidationError, match="1000"):
        NotificationTable(columns=("A",), rows=(("x",),) * 1001)
    with pytest.raises(ValidationError, match="NotificationTable"):
        email(tables=(object(),))
    with pytest.raises(ValidationError, match="5 MiB"):
        email(
            tables=(
                NotificationTable(
                    columns=("A", "B"),
                    rows=(("x" * 3000, "y" * 3000),) * 1000,
                ),
            )
        )
    with pytest.raises(ValidationError, match="destination"):
        TeamsNotification(destination="bad destination", text="x")
    with pytest.raises(ValidationError, match="1-28000"):
        TeamsNotification(destination="ops", text="")
    with pytest.raises(ValidationError, match="title"):
        TeamsNotification(destination="ops", text="x", title="")


@pytest.mark.parametrize(
    "arguments",
    [
        {"max_rows": 0},
        {"max_columns": 51},
        {"email_body_bytes": 0},
        {"teams_payload_bytes": 1024**2 + 1},
    ],
)
def test_render_policy_rejects_invalid_limits(arguments: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        TableRenderPolicy(**arguments)  # type: ignore[arg-type]


def test_table_helpers_default_limits_and_exhaustion() -> None:
    table = NotificationTable(columns=("A",), rows=(("1",), ("2",)))
    assert len(bound_tables((table,), TableRenderPolicy())[0].rows) == 2
    limits = [1, 0]
    assert reduce_largest_row_limit(limits)
    assert limits == [0, 0]
    assert reduce_largest_row_limit(limits) is False
    with pytest.raises(ValidationError, match="cannot fit"):
        render_email(email(text="base", tables=(table,)), TableRenderPolicy(email_body_bytes=1))
