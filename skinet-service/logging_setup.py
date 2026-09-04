"""
Contains loggers to stdout and file and their helper functions
"""

import logging
import sys
from pathlib import Path
from typing import Optional

# Define default log file path
LOG_DIR = Path(__file__).resolve().parent
LOG_DIR.mkdir(exist_ok=True)  # Create logs directory if it doesn't exist
LOG_FILE = LOG_DIR / "skinetweb_logs.log"


class ColorFormatter(logging.Formatter):
    """
    Class that adds colour-coding to log messages for console logs
    """
    COLORS = {
        "DEBUG": "\033[92m",   # Green
        "INFO": "\033[94m",    # Blue
        "WARNING": "\033[93m", # Yellow
        "ERROR": "\033[91m",   # Red
        "CRITICAL": "\033[41m", # White on Red
    }
    RESET = "\033[0m"

    def format(self, record):
        """
        Apply color formatting to log messages based on their severity level.

        This method is automatically called by the logging system when a log record is
        processed by a handler that uses this formatter. It adds ANSI color codes to the
        message depending on the log level.

        :param record: The log record containing the message and metadata.
        :return: The formatted log message with color codes.
        """
        log_message = super().format(record)
        color = self.COLORS.get(record.levelname, self.RESET)
        return f"{color}{log_message}{self.RESET}"


# initialise stdout logging handler
stdout_logging_handler: Optional[logging.StreamHandler] = None
# initialise file logging handler
file_logging_handler: Optional[logging.FileHandler] = None


def stdout_logging(log_level: int = logging.INFO) -> None:
    """
    Configures logging to write log messages to stdout with the given log level.
    The messages will be formatted according to the formatter _set_up_formatter and the logging level is set by log_level

    :param log_level: The logging level to set for the logger, e.g., logging.INFO, logging.DEBUG.
    """

    # retrieve the default logger, the root logger instance
    logger = logging.getLogger()

    # global ensures that the stdout_logging_handler is shared across function calls and if it is already defined, we don't add another handler.
    global stdout_logging_handler
    if not stdout_logging_handler:
        # Remove any existing handlers attached to the root logger at start
        if len(logger.handlers) > 0:
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)

        # create a stream handler to output to stdout and format the messages
        stdout_logging_handler = logging.StreamHandler(stream=sys.stdout)
        _set_up_formatter(stdout_logging_handler)
        logger.addHandler(stdout_logging_handler)

    # set the logging levels for the logger and for the handler
    stdout_logging_handler.setLevel(log_level)
    logger.setLevel(log_level)


def file_logging(log_file: Path = LOG_FILE, files_log_level: Optional[int] = logging.INFO) -> None:
    """
    Configures logging to write log messages to a file at the log level of the set stdout log level.

    :param log_file: Log file to write logs to. Default is set by LOG_FILE variable defined in this module
    """

    # retrieve the default logger, the root logger instance
    logger = logging.getLogger()

    global file_logging_handler
    global stdout_logging_handler
    if not file_logging_handler:
        # use logging level of stdout, otherwise use user-given logging level
        log_level = stdout_logging_handler.level if stdout_logging_handler else files_log_level

        # create a file handler to output to the specified file and format the messages
        file_logging_handler = logging.FileHandler(filename=str(log_file))
        _set_up_formatter(file_logging_handler, colour_coding=False)
        logging.getLogger().addHandler(file_logging_handler)

        # set the logging levels for the logger and for the handler
        file_logging_handler.setLevel(log_level)
        logger.setLevel(log_level)


def _set_up_formatter(handler: logging.Handler, colour_coding: Optional[bool] = True) -> None:
    """
    Sets up a logging formatter for the given handler.

    :param handler: The logging handler to format, e.g., StreamHandler or FileHandler.
    :param colour_coding: If set to False, logs are not color-coded. Default is True. For file logging, colour_coding needs to be set to False.
    """
    if colour_coding:
        formatter = ColorFormatter(
            fmt="%(asctime)s - %(levelname)s [%(funcName)s (%(lineno)d) in %(name)s] - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S")
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(levelname)s [%(funcName)s (%(lineno)d) in %(name)s] - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S")

    handler.setFormatter(formatter)
