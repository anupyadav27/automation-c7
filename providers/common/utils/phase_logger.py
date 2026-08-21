"""
Phase-specific logging for Discovery, Checks, Deviation, and Drift
"""
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict
import json

class PhaseLogger:
    """Dedicated logger for each scan phase"""
    
    def __init__(self, scan_id: str, phase: str, output_dir: Path):
        """
        Initialize phase logger
        
        Args:
            scan_id: Scan identifier
            phase: 'discovery', 'checks', 'deviation', 'drift'
            output_dir: Base output directory
        """
        self.scan_id = scan_id
        self.phase = phase
        self.output_dir = output_dir
        self.log_dir = output_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Create phase-specific logger
        logger_name = f'{phase}_{scan_id}'
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()  # Remove existing handlers
        
        # Phase-specific log file
        log_file = self.log_dir / f"{phase}.log"
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        self.logger.addHandler(fh)
        
        # Console handler with phase prefix
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter(
            f'[{phase.upper()}] %(asctime)s %(levelname)s %(message)s',
            datefmt='%H:%M:%S'
        ))
        self.logger.addHandler(ch)
        
        # Error log file
        error_file = self.log_dir / f"{phase}_errors.log"
        eh = logging.FileHandler(error_file)
        eh.setLevel(logging.ERROR)
        eh.setFormatter(logging.Formatter(
            '%(asctime)s [ERROR] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        self.logger.addHandler(eh)
    
    def info(self, message: str):
        """Log info message"""
        self.logger.info(message)
    
    def error(self, message: str, exc_info: bool = False):
        """Log error message"""
        self.logger.error(message, exc_info=exc_info)
    
    def warning(self, message: str):
        """Log warning message"""
        self.logger.warning(message)
    
    def progress(self, service: str, region: Optional[str], status: str, details: Dict):
        """
        Log progress with structured data
        
        Args:
            service: Service name
            region: Region (None for global)
            status: Status ('started', 'completed', 'failed')
            details: Additional details dictionary
        """
        region_str = f"region={region}" if region else "global"
        details_str = json.dumps(details) if details else "{}"
        self.logger.info(
            f"[PROGRESS] service={service} {region_str} status={status} "
            f"details={details_str}"
        )
    
    def debug(self, message: str):
        """Log debug message"""
        self.logger.debug(message)

