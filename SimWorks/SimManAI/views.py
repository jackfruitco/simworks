from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.utils.timezone import now
from django.http import HttpResponse
from .models import Response
from datetime import date
import csv

@staff_member_required
def usage_report(request):
    session = request.session
    today = now().date()

    # Handle query params and session fallbacks
    preset = request.GET.get("preset")
    start = request.GET.get("start_date") or session.get("start_date")
    end = request.GET.get("end_date") or session.get("end_date")
    group_by_sim = request.GET.get("group_by_sim")
    group_by_sim = group_by_sim == "1" if group_by_sim is not None else session.get("group_by_sim", False)

    # Handle preset overrides
    if preset == "this_month":
        start = today.replace(day=1)
        end = today
    elif preset == "this_year":
        start = today.replace(month=1, day=1)
        end = today
    elif preset == "today":
        start = end = today
    else:
        # Parse dates if strings
        if isinstance(start, str):
            start = date.fromisoformat(start)
        if isinstance(end, str):
            end = date.fromisoformat(end)

        if start and not end:
            end = today
        elif end and not start:
            earliest = Response.objects.order_by("created").values_list("created", flat=True).first()
            start = earliest.date() if earliest else today.replace(month=1, day=1)
        elif not start and not end:
            start = today.replace(day=1)
            end = today

    # Save back to session
    session["start_date"] = start.isoformat()
    session["end_date"] = end.isoformat()
    session["group_by_sim"] = group_by_sim

    # Run analytics
    analytics = Response.objects.analytics().range(start, end)
    report = analytics.by_user().by_month()
    if group_by_sim:
        report = report.by_simulation()
    tallied = report.as_list()

    # CSV Export
    if request.GET.get("export") == "csv":
        csv_content = report.as_csv()
        response = HttpResponse(csv_content, content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=token_usage.csv"
        return response

    # Final context and render
    context = {
        "report": tallied,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "group_by_sim": group_by_sim,
        "summary": analytics.summary(),
        "title": "Token Usage Report",
        "site_title": "Jackfruit Admin",
        "site_header": "Jackfruit Admin",
    }

    return render(request, "admin/analytics/usage.html", context)