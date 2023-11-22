from functools import wraps
import logging

def logged_call(func):
    """Decorator to add logging of function call entry and exit."""
    @wraps(func)
    def log_call(*args, **kwargs):
        arg_values = []
        for arg in args:
            arg_values.append(f"{arg=}")
        for arg_name, arg_value in kwargs.items():
            arg_values.append(f"{arg_name}: {arg_value}")
        arg_info = " ".join(arg_values)
        logging.debug(f"{func.__name__} called with: {arg_info}")
        return_val = func(*args, **kwargs)
        logging.debug(f"{func.__name__} done {return_val}")
        return return_val
    return log_call
