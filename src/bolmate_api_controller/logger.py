from logging import getLogger

_logger = getLogger('bolmate_api_controller')
_exceptions_logger = getLogger('bolmate_api_controller_exceptions')
_auth_logger = getLogger('bolmate_api_controller_auth')


def info(msg: str, *args, **kwargs):
    _logger.info(msg, *args, **kwargs)


def warning(msg: str, *args, **kwargs):
    _logger.warning(msg, *args, **kwargs)


def debug(msg: str, *args, **kwargs):
    _logger.debug(msg, *args, **kwargs)


def error(msg: str, *args, **kwargs):
    _logger.error(msg, *args, **kwargs)


def auth_error(msg: str, *args, **kwargs):
    _auth_logger.error(msg, *args, **kwargs)


def auth_exception(msg: str, *args, **kwargs):
    _auth_logger.exception(msg, *args, **kwargs)


def exception(msg: str, *args, **kwargs):
    _exceptions_logger.exception(msg, *args, **kwargs)
