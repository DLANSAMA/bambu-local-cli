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
        bambu = sys.modules.get('bambu_cli.bambu')
        if bambu:
            bambu_func = getattr(bambu, func.__name__, None)
            print(f"[mockable] func={func.__name__} bambu_func={bambu_func} wrapper={wrapper}", file=sys.stderr)
            if bambu_func and bambu_func is not wrapper and bambu_func is not func:
                res = bambu_func(*args, **kwargs)
                print(f"[mockable] delegated call returned: {res}", file=sys.stderr)
                return res
        return func(*args, **kwargs)
    return wrapper
