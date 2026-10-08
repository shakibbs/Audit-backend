"""GET /api/health: tells the portal the backend and database are up."""
from django.db import connection
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(['GET'])
def health(request):
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
    return Response({'status': 'ok'})
