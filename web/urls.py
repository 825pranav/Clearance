from django.contrib import admin
from django.urls import path

from console import views

admin.site.site_header = "Clearance console"
admin.site.site_title = "Clearance"
admin.site.index_title = "Access requests and catalogue"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("admin/", admin.site.urls),
]
