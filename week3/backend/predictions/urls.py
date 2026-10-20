from django.urls import path

from . import views

urlpatterns = [
    path("predictions/no-show/", views.NoShowPredictView.as_view(), name="predict-no-show-v1"),
    path("models/no-show/", views.NoShowModelInfoView.as_view(), name="model-no-show-v1"),
]
