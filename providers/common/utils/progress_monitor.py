"""
Progress Monitor - Monitor scan progress in real-time
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
import time


def _project_root() -> Path:
    """Repo root (relative to this file)."""
    return Path(__file__).resolve().parent.parent.parent.parent


class ProgressMonitor:
    """Monitor and display scan progress"""
    
    def __init__(self, scan_id: str, output_base_dir: Path = None):
        """
        Initialize progress monitor
        
        Args:
            scan_id: Scan identifier
            output_base_dir: Base output directory (default: engines-output/aws-configScan-engine/output)
        """
        self.scan_id = scan_id
        if output_base_dir is None:
            output_base_dir = _project_root() / "engine_output" / "engine_configscan_aws" / "output" / "configscan"
        self.output_base_dir = output_base_dir
        # Check rule_check and discoveries directories
        rule_check_dir = output_base_dir / "rule_check" / scan_id
        discoveries_dir = output_base_dir / "discoveries" / scan_id
        root_dir = output_base_dir / scan_id
        if rule_check_dir.exists():
            self.scan_dir = rule_check_dir
        elif discoveries_dir.exists():
            self.scan_dir = discoveries_dir
        else:
            self.scan_dir = root_dir  # Fallback to old location
    
    def get_progress(self, phase: str = 'discovery') -> Optional[Dict]:
        """
        Get current progress for a phase
        
        Args:
            phase: Phase name ('discovery', 'checks', etc.)
        
        Returns:
            Progress dictionary or None if not found
        """
        progress_file = self.scan_dir / phase / "progress.json"
        
        if not progress_file.exists():
            return None
        
        try:
            with open(progress_file) as f:
                return json.load(f)
        except Exception as e:
            print(f"Error reading progress file: {e}")
            return None
    
    def display_progress(self, phase: str = 'discovery'):
        """Display formatted progress information"""
        progress = self.get_progress(phase)
        
        if not progress:
            print(f"\n❌ Progress file not found for {phase} phase")
            return
        
        print(f"\n{'='*80}")
        print(f"Scan Progress: {progress.get('scan_id', 'unknown')} - {phase.upper()}")
        print(f"{'='*80}")
        print(f"Status: {progress.get('status', 'unknown')}")
        print(f"Total Records: {progress.get('total_records', 0):,}")
        print(f"Services Completed: {len(progress.get('services', {}))}")
        print(f"Regions: {len(progress.get('regions', {}))}")
        
        if progress.get('services'):
            print(f"\nCompleted Services:")
            for key, svc in sorted(progress['services'].items()):
                print(f"  ✅ {svc['service']} ({svc['region']}): "
                      f"{svc['item_count']:,} items, "
                      f"{svc['discovery_count']} discoveries")
        
        if progress.get('regions'):
            print(f"\nBy Region:")
            for region, region_info in sorted(progress['regions'].items()):
                print(f"  {region}: {region_info['total_records']:,} records, "
                      f"{len(region_info['services'])} services")
        
        print(f"\nLast Update: {progress.get('last_update', 'unknown')}")
        print(f"{'='*80}")
    
    def monitor_live(self, phase: str = 'discovery', interval: int = 5):
        """
        Monitor progress live with auto-refresh
        
        Args:
            phase: Phase to monitor
            interval: Refresh interval in seconds
        """
        import os
        
        print(f"\n🔍 Monitoring {phase} progress (refresh every {interval}s, Ctrl+C to stop)...\n")
        
        try:
            while True:
                # Clear screen (works on Unix/Mac, Windows may need different approach)
                os.system('clear' if os.name != 'nt' else 'cls')
                
                self.display_progress(phase)
                
                progress = self.get_progress(phase)
                if progress and progress.get('status') == 'completed':
                    print("\n✅ Scan completed!")
                    break
                
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n\n⏸️  Monitoring stopped by user")
    
    def get_summary(self, phase: str = 'discovery') -> Optional[Dict]:
        """
        Get summary for a phase
        
        Args:
            phase: Phase name
        
        Returns:
            Summary dictionary or None
        """
        summary_file = self.scan_dir / phase / "summary.json"
        
        if not summary_file.exists():
            return None
        
        try:
            with open(summary_file) as f:
                return json.load(f)
        except Exception as e:
            print(f"Error reading summary file: {e}")
            return None
    
    def display_summary(self, phase: str = 'discovery'):
        """Display formatted summary"""
        summary = self.get_summary(phase)
        
        if not summary:
            print(f"\n❌ Summary file not found for {phase} phase")
            return
        
        print(f"\n{'='*80}")
        print(f"Scan Summary: {summary.get('scan_id', 'unknown')} - {phase.upper()}")
        print(f"{'='*80}")
        print(f"Total Records: {summary.get('total_records', 0):,}")
        print(f"Total Services: {summary.get('total_services', 0)}")
        print(f"Services Scanned: {', '.join(summary.get('services_scanned', [])[:10])}")
        if len(summary.get('services_scanned', [])) > 10:
            print(f"  ... and {len(summary.get('services_scanned', [])) - 10} more")
        
        if summary.get('by_service'):
            print(f"\nBy Service:")
            for service, svc_info in sorted(summary['by_service'].items()):
                print(f"  {service}: {svc_info.get('total_records', 0):,} records, "
                      f"{len(svc_info.get('discovery_functions', []))} discovery functions")
        
        print(f"\nOutput Directory: {summary.get('output_directory', 'unknown')}")
        print(f"{'='*80}")

