from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrPhoneBackend(ModelBackend):
    """Authenticate with email or phone number. Suspended accounts cannot sign in."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = (username or kwargs.get("email") or "").strip()
        if not identifier or not password:
            return None
        User = get_user_model()
        phone = identifier.replace(" ", "")
        if phone.startswith("07") and len(phone) == 10:
            phone = "+250" + phone[1:]
        try:
            user = User.objects.get(Q(email__iexact=identifier) | Q(phone=phone))
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            User().set_password(password)  # equalise timing with the found-user path
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def user_can_authenticate(self, user):
        return super().user_can_authenticate(user) and not getattr(user, "is_suspended", False)

    def get_user(self, user_id):
        # Suspended users still resolve here so SuspendedUserMiddleware can end the session with a message.
        User = get_user_model()
        try:
            user = User._default_manager.get(pk=user_id)
        except User.DoesNotExist:
            return None
        return user if user.is_active else None
