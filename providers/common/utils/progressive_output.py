"""
Progressive Output Writer - Updates output after each service/region
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import threading
import logging

logger = logging.getLogger(__name__)

class ProgressiveOutputWriter:
    """Write output progressively as scan progresses"""
    
    def __init__(self, scan_id: str, output_dir: Path, phase: str = 'discovery'):
        """
        Initialize progressive output writer
        
        Args:
            scan_id: Scan identifier
            output_dir: Base output directory
            phase: Phase name ('discovery', 'checks', 'deviation', 'drift')
        """
        self.scan_id = scan_id
        self.phase = phase
        self.output_dir = output_dir / phase
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        
        # Track progress
        self.progress = {
            'scan_id': scan_id,
            'phase': phase,
            'start_time': datetime.now().isoformat(),
            'last_update': datetime.now().isoformat(),
            'services': {},
            'regions': {},
            'errors': {},
            'total_records': 0,
            'total_services': 0,
            'total_regions': 0,
            'total_errors': 0,
            'status': 'running'
        }
        
        # Service-specific output files (NDJSON)
        self.service_files = {}  # key: (account_id, region, service)
        
        # Write initial progress file
        self._write_progress()
    
    def update_service_progress(self, account_id: str, region: Optional[str], 
                                service: str, discovery_count: int, 
                                item_count: int, discovery_functions: List[str],
                                total_discoveries: Optional[int] = None):
        """
        Update progress after service completion
        
        Args:
            account_id: Account identifier
            region: Region (None for global)
            service: Service name
            discovery_count: Number of discovery functions executed (with items)
            item_count: Number of items discovered
            discovery_functions: List of discovery function IDs
            total_discoveries: Total number of discoveries configured (optional)
        """
        with self.lock:
            key = f"{account_id}_{region or 'global'}_{service}"
            
            service_info = {
                'account_id': account_id,
                'region': region or 'global',
                'service': service,
                'discovery_count': discovery_count,
                'item_count': item_count,
                'discovery_functions': discovery_functions,
                'completed_at': datetime.now().isoformat()
            }
            
            # Add total_discoveries if provided (for execution tracking)
            if total_discoveries is not None:
                service_info['total_discoveries'] = total_discoveries
                service_info['execution_rate'] = f"{discovery_count}/{total_discoveries}"
            
            self.progress['services'][key] = service_info
            
            self.progress['total_records'] += item_count
            self.progress['total_services'] = len(self.progress['services'])
            
            # Track regions
            region_key = region or 'global'
            if region_key not in self.progress['regions']:
                self.progress['regions'][region_key] = {
                    'services': [],
                    'total_records': 0
                }
            if service not in self.progress['regions'][region_key]['services']:
                self.progress['regions'][region_key]['services'].append(service)
            self.progress['regions'][region_key]['total_records'] += item_count
            self.progress['total_regions'] = len(self.progress['regions'])
            
            self.progress['last_update'] = datetime.now().isoformat()
            
            # Write progress file
            self._write_progress()
    
    def track_error(self, account_id: str, region: Optional[str], service: str,
                    error_type: str, error_message: str):
        """
        Track an error for a service/region
        
        Args:
            account_id: Account identifier
            region: Region (None for global)
            service: Service name
            error_type: Type of error (e.g., 'missing_file', 'exception', 'parameter_validation')
            error_message: Error message
        """
        with self.lock:
            key = f"{account_id}_{region or 'global'}_{service}"
            
            if key not in self.progress['errors']:
                self.progress['errors'][key] = []
            
            self.progress['errors'][key].append({
                'error_type': error_type,
                'error_message': error_message,
                'timestamp': datetime.now().isoformat()
            })
            
            self.progress['total_errors'] = sum(len(errors) for errors in self.progress['errors'].values())
            self.progress['last_update'] = datetime.now().isoformat()
            
            # Write progress file
            self._write_progress()
            
            # Also write to error log file
            error_log_file = self.output_dir / "errors.json"
            with open(error_log_file, 'a') as f:
                error_entry = {
                    'timestamp': datetime.now().isoformat(),
                    'account_id': account_id,
                    'region': region or 'global',
                    'service': service,
                    'error_type': error_type,
                    'error_message': error_message
                }
                f.write(json.dumps(error_entry, default=str) + "\n")
    
    def append_service_output(self, account_id: str, region: Optional[str], 
                             service: str, records: List[Dict]):
        """
        Append records to service-specific NDJSON file
        
        Args:
            account_id: Account identifier
            region: Region (None for global)
            service: Service name
            records: List of record dictionaries
        """
        with self.lock:
            key = (account_id, region or 'global', service)
            
            if key not in self.service_files:
                # Create new file
                filename = f"{account_id}_{region or 'global'}_{service}.ndjson"
                filepath = self.output_dir / filename
                self.service_files[key] = filepath
                logger.info(f"  📄 Created output file: {filename}")
            
            # Append records
            with open(self.service_files[key], 'a') as f:
                for record in records:
                    f.write(json.dumps(record, default=str) + "\n")
    
    def _write_progress(self):
        """Write progress JSON file"""
        progress_file = self.output_dir / "progress.json"
        with open(progress_file, 'w') as f:
            json.dump(self.progress, f, indent=2, default=str)
    
    def finalize(self, summary: Dict):
        """
        Finalize output with summary
        
        Args:
            summary: Final summary dictionary
        """
        with self.lock:
            self.progress['status'] = 'completed'
            self.progress['end_time'] = datetime.now().isoformat()
            self.progress['summary'] = summary
            
            # Write final summary
            summary_file = self.output_dir / "summary.json"
            with open(summary_file, 'w') as f:
                json.dump(summary, f, indent=2, default=str)
            
            self._write_progress()
            
            logger.info(f"  ✅ Finalized {self.phase} output: {summary_file}")
    
    def get_progress(self) -> Dict:
        """Get current progress"""
        with self.lock:
            return self.progress.copy()

