import json

from django.http import HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from apps.common.utils import Formatter
from apps.simcore.models import Simulation
from apps.simcore.tools import get_tool


def download_simulation_transcript(request, simulation_id, format_type="sim_transcript_txt"):
    sim = get_object_or_404(Simulation, id=simulation_id)
    formatter = Formatter(sim.history)
    return formatter.download(format_type=format_type, filename=f"Sim{sim.pk}_transcript")


@require_GET
def refresh_tool(request, tool_name, simulation_id):
    simulation = get_object_or_404(Simulation, id=simulation_id)

    tool_class = get_tool(tool_name)
    if not tool_class:
        return HttpResponseNotFound(f"Tool '{tool_name}' not found.")

    tool_instance = tool_class(simulation)
    tool = tool_instance.to_dict()

    # Try to load tool-specific partial from consolidated tools.html
    partial_name = f"tool_{tool_name}"
    try:
        # Django 6.0 partial syntax: template.html#partial_name
        template_name = f"simcore/tools.html#{partial_name}"
        get_template(template_name)
    except TemplateDoesNotExist:
        # Fallback to generic partial
        template_name = "simcore/tools.html#tool_generic"
        get_template(template_name)

    context = {"tool": tool, "simulation": simulation}
    return render(request, template_name, context)


def tool_checksum(request, tool_name, simulation_id):
    simulation = get_object_or_404(Simulation, id=simulation_id)
    tool_class = get_tool(tool_name)
    if not tool_class:
        return JsonResponse({"error": "Tool not found"}, status=404)

    tool_instance = tool_class(simulation)
    checksum = tool_instance.get_checksum()
    return JsonResponse({"checksum": checksum})


@csrf_exempt
async def sign_orders(request, simulation_id):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            submitted_orders = data.get("submitted_orders", None)

            if submitted_orders is None:
                try:
                    submitted_orders = data.lab_orders
                except AttributeError as err:
                    raise ValueError("submitted_orders not found in request body") from err

            from apps.simcore.orca.services import GenerateInitialFeedback

            await GenerateInitialFeedback.task.using(
                context={
                    "simulation_id": simulation_id,
                    "lab_orders": submitted_orders,
                }
            ).aenqueue()

            return JsonResponse({"status": "ok", "orders": submitted_orders})
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
    return JsonResponse({"error": "Method not allowed"}, status=405)
