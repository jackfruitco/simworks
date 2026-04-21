import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def populate_invitation_uuid(apps, schema_editor):
    Invitation = apps.get_model("accounts", "Invitation")
    db_alias = schema_editor.connection.alias
    for invitation in Invitation.objects.using(db_alias).filter(uuid__isnull=True).iterator():
        invitation.uuid = uuid.uuid4()
        invitation.save(update_fields=["uuid"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_rename_membership_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="invitation",
            name="uuid",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_invitation_uuid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="invitation",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AddField(
            model_name="invitation",
            name="claimed_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="claimed_invitations",
                to="accounts.account",
            ),
        ),
        migrations.AddField(
            model_name="invitation",
            name="last_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="invitation",
            name="membership_role",
            field=models.CharField(
                choices=[
                    ("billing_admin", "Billing Admin"),
                    ("org_admin", "Org Admin"),
                    ("instructor", "Instructor"),
                    ("general_user", "General User"),
                ],
                default="general_user",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="invitation",
            name="metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="invitation",
            name="product_code",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="invitation",
            name="revoked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="invitation",
            name="send_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="invitation",
            name="sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="InvitationAuditEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("event_type", models.CharField(max_length=100)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="invitation_audit_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "invitation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="audit_events",
                        to="accounts.invitation",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="invitationauditevent",
            index=models.Index(
                fields=["invitation", "created_at"],
                name="idx_invite_audit_invite",
            ),
        ),
        migrations.AddIndex(
            model_name="invitationauditevent",
            index=models.Index(
                fields=["event_type", "created_at"],
                name="idx_invite_audit_type",
            ),
        ),
    ]
