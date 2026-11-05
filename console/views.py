"""The overview page: request counts, the requests waiting longest, recent ones and the latest eval scores."""

import json

from django.contrib import admin
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count
from django.shortcuts import render

from app import config, policy
from console.models import Request


def _counts(field, values):
    """Every possible value with its count, zeros included, plus its share of the largest for the bar width."""
    found = dict(Request.objects.order_by().values_list(field).annotate(n=Count("id")))
    top = max(found.values(), default=0)
    return [{"label": value.replace("_", " "), "count": found.get(value, 0),
             "percent": round(100 * found.get(value, 0) / top) if top else 0} for value in values]


def _eval_scores():
    path = config.ROOT / "evals" / "results.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@login_required
@permission_required("console.view_request", raise_exception=True)
def overview(request):
    requests = Request.objects.select_related("employee", "system")
    return render(request, "console/overview.html", {
        **admin.site.each_context(request),
        "title": "Overview",
        "by_status": _counts("status", policy.STATES),
        "by_risk": _counts("risk_tier", policy.RISKS),
        "waiting": requests.filter(status__in=policy.OPEN_STATES).order_by("created_at")[:10],
        "recent": requests.order_by("-id")[:10],
        "evals": _eval_scores(),
    })
