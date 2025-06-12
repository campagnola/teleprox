# ABOUTME: Public API for logviewer subpackage exposing only LogViewer
# ABOUTME: Maintains backward compatibility by re-exporting LogViewer as the sole public interface

from .core import LogViewer

__all__ = ['LogViewer']