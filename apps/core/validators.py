import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext as _

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DOCUMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


def validate_image_upload(f):
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValidationError(_("Upload a JPG, PNG or WEBP image."))
    if f.size > settings.MAX_IMAGE_UPLOAD_MB * 1024 * 1024:
        raise ValidationError(_("Images must be %(mb)s MB or smaller.") % {"mb": settings.MAX_IMAGE_UPLOAD_MB})
    from PIL import Image

    try:
        pos = f.tell() if hasattr(f, "tell") else 0
        img = Image.open(f)
        img.verify()
        f.seek(pos)
    except Exception as exc:  # noqa: BLE001 - any decode failure means not a real image
        raise ValidationError(_("The file is not a valid image.")) from exc


def validate_document_upload(f):
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in DOCUMENT_EXTENSIONS:
        raise ValidationError(_("Upload a PDF, JPG or PNG file."))
    if f.size > settings.MAX_DOCUMENT_UPLOAD_MB * 1024 * 1024:
        raise ValidationError(_("Documents must be %(mb)s MB or smaller.") % {"mb": settings.MAX_DOCUMENT_UPLOAD_MB})
    head = f.read(8)
    f.seek(0)
    if ext == ".pdf" and not head.startswith(b"%PDF"):
        raise ValidationError(_("The file is not a valid PDF."))
    if ext in {".jpg", ".jpeg"} and not head.startswith(b"\xff\xd8"):
        raise ValidationError(_("The file is not a valid JPEG."))
    if ext == ".png" and not head.startswith(b"\x89PNG"):
        raise ValidationError(_("The file is not a valid PNG."))


@deconstructible
class RandomFilename:
    """upload_to callable: discards the client filename so it can never traverse paths or collide."""

    def __init__(self, folder):
        self.folder = folder

    def __call__(self, instance, filename):
        ext = os.path.splitext(filename)[1].lower()[:6]
        return f"{self.folder}/{uuid.uuid4().hex}{ext}"
