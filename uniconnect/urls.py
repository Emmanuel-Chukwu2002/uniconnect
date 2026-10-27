from django.conf import settings
from django.contrib import admin
from django.urls import path, include, re_path

from .media_serve import serve_media

urlpatterns = [
    path('admin/', admin.site.urls),
    path('messages/', include('chat.urls')),
    path('bookshop/', include('bookshop.urls')),
    path('communities/', include('communities.urls')),
    path('opportunities/', include('opportunities.urls')),
    path('groups/', include('studygroups.urls')),
    path('courses/', include('courses.urls')),
    path('recommendations/', include('recommendations.urls')),
    path('staff/', include('adminpanel.urls')),
    path('', include('feed.urls')),
    path('', include('accounts.urls')),
]

if settings.SERVE_MEDIA:
    # Uploaded files, with Range support so videos can be seeked
    # (uniconnect/media_serve.py explains why Django's own view can't).
    # On while DEBUG is on; online, SERVE_MEDIA=1 turns it on (see settings.py).
    urlpatterns += [
        re_path(r'^%s(?P<path>.*)$' % settings.MEDIA_URL.lstrip('/'), serve_media, {'document_root': settings.MEDIA_ROOT}),
    ]
