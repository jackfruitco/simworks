from django.shortcuts import render

from apps.accounts.decorators import staff_required

from .services import get_staff_dashboard_links, get_staff_dashboard_status


@staff_required
def dashboard(request):
    links = get_staff_dashboard_links(request.user)
    grouped: dict[str, list] = {}
    for link in links:
        grouped.setdefault(link.group, []).append(link)
    return render(
        request,
        "staffhub/dashboard.html",
        {
            "groups": grouped,
            "status": get_staff_dashboard_status(),
        },
    )
