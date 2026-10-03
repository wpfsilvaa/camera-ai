"""Rules for requests that reach the dashboard through a local HTTPS proxy such as Tailscale Serve."""
import os


LOCAL_ONLY = os.environ.get('HOST', '127.0.0.1') in ('127.0.0.1', 'localhost', '::1')


def behind_local_proxy(request):
    """True when the dashboard only listens locally, so requests arrive through a local proxy (Tailscale Serve)."""
    return LOCAL_ONLY and bool(request.headers.get('x-forwarded-for') or request.headers.get('x-forwarded-host'))


def allowed_origins(request):
    host = request.headers.get('host')
    origins = {f'{request.url.scheme}://{host}'}
    if behind_local_proxy(request):
        forwarded = request.headers.get('x-forwarded-host') or host
        origins |= {f'https://{forwarded}', f'http://{forwarded}'}
    # The address family members use, e.g. https://casa.tail1234.ts.net (set by scripts/setup-tailscale.sh).
    origins |= {url.strip().rstrip('/') for url in os.environ.get('PUBLIC_URL', '').split(',') if url.strip()}
    return origins


def is_https(request):
    return request.url.scheme == 'https' or (behind_local_proxy(request) and request.headers.get('x-forwarded-proto') == 'https')
