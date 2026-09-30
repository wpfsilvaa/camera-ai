from fastapi import HTTPException


def call_service(fn, *args):
    """Run domain code and translate its exceptions into HTTP errors."""
    try:
        return fn(*args)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
