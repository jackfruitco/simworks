from django.db import models

class ApiAccessControl(models.Model):
    """Dummy Model to create API permissions"""

    class Meta:
        permissions = [
            ("read_api", "Can read API"),
            ("write_api", "Can write API"),
        ]
