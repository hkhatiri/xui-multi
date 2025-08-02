import threading
import time
import logging
from datetime import datetime
import reflex as rx

from .redis_queue import redis_queue
from .tasks import sync_usage_task, build_configs_task, cleanup_deleted_panels_task, update_service_task, delete_service_task

# Configure logging
logging.basicConfig(
    filename='xui_multi.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RedisWorkerManager:
    def __init__(self):
        """Initialize Redis worker manager"""
        self.workers = {}
        self.running = False
        self.scheduler_thread = None
        
    def start_workers(self):
        """Start all Redis workers"""
        try:
            logger.info("Starting Redis workers...")
            
            # Set running flag first
            self.running = True
            
            # Register worker functions
            redis_queue.register_worker('sync_usage', sync_usage_task)
            redis_queue.register_worker('build_configs', build_configs_task)
            redis_queue.register_worker('cleanup_panels', cleanup_deleted_panels_task)
            redis_queue.register_worker('update_service', update_service_task)
            redis_queue.register_worker('delete_service', delete_service_task)
            
            # Start workers
            redis_queue.start_all_workers()
            
            # Start scheduler for periodic tasks
            self.start_scheduler()
            
            logger.info("Redis workers started successfully")
            
        except Exception as e:
            logger.error(f"Error starting Redis workers: {e}")
            self.running = False
            raise
    
    def start_scheduler(self):
        """Start scheduler for periodic tasks"""
        def scheduler_loop():
            logger.info("Starting Redis task scheduler...")
            last_cleanup_time = None
            last_sync_task_id = None
            
            while self.running:
                try:
                    current_time = datetime.now()
                    
                    # Check if previous sync_usage task is completed
                    if last_sync_task_id:
                        task_status = redis_queue.get_task_status(last_sync_task_id)
                        if task_status and task_status.get('status') in ['completed', 'failed']:
                            # Previous task is done, enqueue new one
                            from .tasks import enqueue_sync_usage
                            new_task_id = enqueue_sync_usage()
                            last_sync_task_id = new_task_id
                            logger.info(f"Enqueued new sync_usage task {new_task_id} after previous task completed")
                            print(f"🔄 Scheduler: Enqueued new sync_usage task {new_task_id}")
                    elif last_sync_task_id is None:
                        # First time, enqueue initial task
                        from .tasks import enqueue_sync_usage
                        new_task_id = enqueue_sync_usage()
                        last_sync_task_id = new_task_id
                        logger.info(f"Enqueued initial sync_usage task {new_task_id}")
                        print(f"🔄 Scheduler: Enqueued initial sync_usage task {new_task_id}")
                    
                    # Run cleanup every hour (time-based)
                    if (last_cleanup_time is None or 
                        (current_time - last_cleanup_time).total_seconds() >= 3600):
                        from .tasks import enqueue_cleanup_panels
                        enqueue_cleanup_panels()
                        last_cleanup_time = current_time
                        logger.info(f"Enqueued cleanup_panels task at {current_time}")
                        print(f"🧹 Scheduler: Enqueued cleanup_panels task at {current_time}")
                    
                    time.sleep(10)  # Check every 10 seconds for faster response
                    
                except Exception as e:
                    logger.error(f"Scheduler error: {e}")
                    time.sleep(5)
        
        self.scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
        self.scheduler_thread.start()
        logger.info("Redis task scheduler started")
    
    def stop_workers(self):
        """Stop all Redis workers"""
        try:
            logger.info("Stopping Redis workers...")
            self.running = False
            redis_queue.stop_workers()
            logger.info("Redis workers stopped successfully")
            
        except Exception as e:
            logger.error(f"Error stopping Redis workers: {e}")
    
    def get_queue_stats(self):
        """Get statistics about all queues"""
        return redis_queue.get_queue_stats()
    
    def get_task_status(self, task_id: str):
        """Get status of a specific task"""
        return redis_queue.get_task_status(task_id)

# Global worker manager instance
worker_manager = RedisWorkerManager()

def start_redis_workers():
    """Start Redis workers (called from main application)"""
    try:
        worker_manager.start_workers()
        return True
    except Exception as e:
        logger.error(f"Failed to start Redis workers: {e}")
        return False

def stop_redis_workers():
    """Stop Redis workers"""
    worker_manager.stop_workers()

def get_queue_statistics():
    """Get queue statistics"""
    return worker_manager.get_queue_stats() 