"""SHA-256 of an uploaded file, so CiV can later show the file was not changed."""
import hashlib


def sha256_of(django_file) -> str:
    digest = hashlib.sha256()
    django_file.seek(0)
    for chunk in django_file.chunks():
        digest.update(chunk)
    django_file.seek(0)
    return digest.hexdigest()
