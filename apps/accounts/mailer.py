"""One way to send CiV's emails: the same clear design (heading, a few lines, one button) as HTML, with a plain-text
copy for mail apps that do not show HTML. Used by every email: invites, password links, insurer and staff invites,
connect requests."""
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send(to: list[str] | str, subject: str, *, name: str, heading: str, lines: list[str], button: str, link: str, note: str = '') -> None:
    to = [to] if isinstance(to, str) else to
    text = '\n\n'.join([f'Hello {name},', *lines, f'{button}: {link}', *([note] if note else [])])
    html = render_to_string('emails/base.html', {'name': name, 'heading': heading, 'lines': lines, 'button': button, 'link': link, 'note': note})
    message = EmailMultiAlternatives(subject, text, None, to)
    message.attach_alternative(html, 'text/html')
    message.send()

