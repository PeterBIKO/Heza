from django.contrib.auth import get_user_model
from django.core import signing

SALT = "heza.email-verification"
MAX_AGE = 60 * 60 * 24 * 3


def make_email_token(user):
    return signing.dumps({"uid": user.pk, "email": user.email}, salt=SALT)


def read_email_token(token):
    """Returns the user if the token is valid, unexpired and still matches the user's current email."""
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature:
        return None
    User = get_user_model()
    user = User.objects.filter(pk=data.get("uid")).first()
    if user is None or user.email != data.get("email"):
        return None
    return user
