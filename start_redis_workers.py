#!/usr/bin/env python3
"""
Redis Workers Background Service
This script runs Redis workers in the background to process tasks.
"""

import sys
import os
import signal
import time
import logging
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from xui_multi.redis_worker import start_redis_workers, stop_redis_workers

# Configure logging
logging.basicConfig(
    filename='redis_workers.log',
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info("Received shutdown signal, stopping Redis workers...")
    stop_redis_workers()
    sys.exit(0)

def main():
    """Main function to run Redis workers"""
    logger.info("Starting Redis Workers Background Service...")
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start Redis workers
        success = start_redis_workers()
        if success:
            logger.info("Redis workers started successfully")
            
            # Keep the process running
            while True:
                time.sleep(60)  # Check every minute
                # logger.info("Redis workers running...")  # Removed to reduce log noise
                
        else:
            logger.error("Failed to start Redis workers")
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
    finally:
        stop_redis_workers()
        logger.info("Redis workers stopped")

if __name__ == "__main__":
    main() 
"""
Redis Workers Background Service
This script runs Redis workers in the background to process tasks.
"""

import sys
import os
import signal
import time
import logging
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from xui_multi.redis_worker import start_redis_workers, stop_redis_workers

# Configure logging
logging.basicConfig(
    filename='redis_workers.log',
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info("Received shutdown signal, stopping Redis workers...")
    stop_redis_workers()
    sys.exit(0)

def main():
    """Main function to run Redis workers"""
    logger.info("Starting Redis Workers Background Service...")
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start Redis workers
        success = start_redis_workers()
        if success:
            logger.info("Redis workers started successfully")
            
            # Keep the process running
            while True:
                time.sleep(60)  # Check every minute
                # logger.info("Redis workers running...")  # Removed to reduce log noise
                
        else:
            logger.error("Failed to start Redis workers")
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
    finally:
        stop_redis_workers()
        logger.info("Redis workers stopped")

if __name__ == "__main__":
    main() 