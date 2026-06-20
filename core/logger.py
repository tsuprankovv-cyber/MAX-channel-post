"""
Единый логгер для всех модулей
"""
import logging
import sys

_logger = None

def setup_logger(log_level='DEBUG', log_file=None):
    global _logger
    _logger = logging.getLogger('max_bot')
    _logger.setLevel(getattr(logging, log_level, logging.DEBUG))
    
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    if not _logger.handlers:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        _logger.addHandler(console)
        
        if log_file:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            _logger.addHandler(file_handler)
    
    return _logger

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f'max_bot.{name}')
