from apps.privacy import policies


def privacy_flags(_request):
    return {
        "privacy_enable_pii_warning": policies.pii_warning_enabled(),
    }
