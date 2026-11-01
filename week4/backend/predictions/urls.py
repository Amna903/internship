from django.urls import path

from . import views

urlpatterns = [
    path("predictions/no-show/", views.NoShowPredictionView.as_view(), name="predict-no-show"),
    path("models/no-show/", views.NoShowModelView.as_view(), name="model-no-show"),
    path("clusters/", views.ClustersView.as_view(), name="clusters"),
]
