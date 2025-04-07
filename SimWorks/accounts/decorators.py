def is_inviter(user):
    return user.groups.filter(name="Inviters").exists() or user.is_superuser
