from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView
from graphene_django.views import GraphQLView
from opentelemetry import trace

def index(request):
    # Number of visits to this view, as counted in the session variable.
    num_visits = request.session.get("num_visits", 0)
    num_visits += 1
    request.session["num_visits"] = num_visits

    return render(
        request,
        "core/index.html",
        # {"products": products},
    )


class PrivateGraphQLView(GraphQLView):
    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        user = request.user

        if not user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())

        if not (user.is_staff or user.has_perm("core.read_api")):
            raise PermissionDenied(
                "You do not have permission to access the GraphQL API."
            )

        return super().dispatch(request, *args, **kwargs)

def csrf_failure(request, reason=""):
    trace_id = None
    span = trace.get_current_span()
    if span and span.is_recording():
        ctx = span.get_span_context()
        trace_id = f"{ctx.trace_id:032x}"
        span.set_attribute("django.csrf.reason", reason)

    return render(request, "403_csrf.html", {"reason": reason, "trace_id": trace_id}, status=403)


class RobotsView(TemplateView):
    template_name = "robots.txt"
