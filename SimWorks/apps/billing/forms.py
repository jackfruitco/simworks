from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from apps.billing.catalog import all_product_codes, get_product
from apps.billing.models import Entitlement, SeatAllocation, SeatAssignment


def _product_code_choices():
    return [(code, get_product(code).display_name) for code in all_product_codes()]


class EntitlementAdminForm(forms.ModelForm):
    product_code = forms.ChoiceField(choices=_product_code_choices())

    class Meta:
        model = Entitlement
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        feature_code = cleaned_data.get("feature_code") or getattr(
            self.instance, "feature_code", ""
        )
        limit_code = cleaned_data.get("limit_code") or getattr(self.instance, "limit_code", "")
        limit_value = cleaned_data.get("limit_value")
        if limit_value is None:
            limit_value = getattr(self.instance, "limit_value", None)

        errors = []
        if feature_code:
            errors.append("Feature grants are disabled for manual billing admin entry.")
        if limit_code or limit_value is not None:
            errors.append("Limit grants are disabled for manual billing admin entry.")
        if errors:
            raise ValidationError(errors)
        return cleaned_data


class SeatAllocationAdminForm(forms.ModelForm):
    product_code = forms.ChoiceField(choices=_product_code_choices())

    class Meta:
        model = SeatAllocation
        fields = "__all__"


class SeatAssignmentAdminForm(forms.ModelForm):
    product_code = forms.ChoiceField(choices=_product_code_choices())

    class Meta:
        model = SeatAssignment
        fields = "__all__"
