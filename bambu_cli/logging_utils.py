class LoggerProxy:
    def __getattr__(self, name):
        import logging

        try:
            from bambu_cli import bambu

            return getattr(getattr(bambu, "logger", None) or logging.getLogger("bambu"), name)
        except ImportError:
            return getattr(logging.getLogger("bambu"), name)


logger = LoggerProxy()


def mockable(func):
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        import sys

        bambu = sys.modules.get("bambu_cli.bambu")
        if bambu:
            bambu_func = getattr(bambu, func.__name__, None)
            if bambu_func and bambu_func is not wrapper and bambu_func is not func:
                return bambu_func(*args, **kwargs)
        return func(*args, **kwargs)

    return wrapper
