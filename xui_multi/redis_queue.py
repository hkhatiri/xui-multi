import redis
import json
import threading
import time
import logging
from datetime import datetime
from typing import Dict, Any, Callable
import os

# Configure logging
logging.basicConfig(
    filename='xui_multi.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RedisQueue:
    def __init__(self, host='localhost', port=6379, db=0):
        """Initialize Redis queue system"""
        self.redis_client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self.workers = {}
        self.running = False
        
    def enqueue_task(self, task_name: str, task_id: str, task_data: Dict[str, Any], priority: int = 0):
        """Add task to queue"""
        try:
            task = {
                'id': task_id,
                'name': task_name,
                'data': task_data,
                'priority': priority,
                'created_at': datetime.now().isoformat(),
                'status': 'pending'
            }
            
            # Add to queue with priority
            self.redis_client.zadd(f"queue:{task_name}", {task_id: priority})
            
            # Store task data separately
            self.redis_client.hset(f"task:{task_id}", mapping={
                'name': task_name,
                'task_type': task_name,  # Store task type for filtering
                'data': json.dumps(task_data),
                'priority': str(priority),
                'created_at': task['created_at'],
                'status': 'pending'
            })
            
            return task_id
            
        except Exception as e:
            logger.error(f"Error enqueueing task {task_name}: {e}")
            raise
    
    def dequeue_task(self, task_name: str):
        """Get next task from queue"""
        try:
            # Get highest priority task
            tasks = self.redis_client.zrevrange(f"queue:{task_name}", 0, 0, withscores=True)
            if tasks:
                task_id, priority = tasks[0]
                
                # Get task data from hash
                task_data = self.redis_client.hgetall(f"task:{task_id}")
                if task_data:
                    try:
                        data_json = task_data.get('data', '{}')
                        if data_json:
                            task = {
                                'id': task_id,
                                'name': task_data.get('name', task_name),
                                'data': json.loads(data_json),
                                'priority': int(task_data.get('priority', 0)),
                                'created_at': task_data.get('created_at', ''),
                                'status': task_data.get('status', 'pending')
                            }
                            
                            # Remove from queue
                            self.redis_client.zrem(f"queue:{task_name}", task_id)
                            
                            return task
                        else:
                            # Remove invalid task from queue
                            self.redis_client.zrem(f"queue:{task_name}", task_id)
                            logger.warning(f"Removed invalid task {task_id} from queue")
                    except json.JSONDecodeError as e:
                        # Remove invalid task from queue
                        self.redis_client.zrem(f"queue:{task_name}", task_id)
                        logger.warning(f"Removed task {task_id} with invalid JSON: {e}")
            return None
            
        except Exception as e:
            logger.error(f"Error dequeuing task {task_name}: {e}")
            return None
    
    def register_worker(self, task_name: str, worker_func: Callable):
        """Register a worker function for a task type"""
        self.workers[task_name] = worker_func
        logger.info(f"Worker registered for task: {task_name}")
    
    def start_worker(self, task_name: str, worker_func: Callable = None):
        """Start a worker for a specific task type"""
        if worker_func:
            self.register_worker(task_name, worker_func)
        
        def worker_loop():
            logger.info(f"Starting worker for task: {task_name}")
            while self.running:
                try:
                    task = self.dequeue_task(task_name)
                    if task:
                        # logger.info(f"Processing task: {task['id']}")  # Removed to reduce log noise
                        
                        # Update task status
                        self.redis_client.hset(f"task:{task['id']}", mapping={
                            'status': 'processing',
                            'started_at': datetime.now().isoformat()
                        })
                        
                        # Execute task
                        if task_name in self.workers:
                            try:
                                result = self.workers[task_name](**task['data'])
                                
                                # Update task status
                                self.redis_client.hset(f"task:{task['id']}", mapping={
                                    'status': 'completed',
                                    'completed_at': datetime.now().isoformat(),
                                    'result': json.dumps(result) if result else ''
                                })
                                
                                # logger.info(f"Task {task['id']} completed successfully")  # Removed to reduce log noise
                                
                            except Exception as e:
                                logger.error(f"Error executing task {task['id']}: {e}")
                                
                                # Update task status
                                self.redis_client.hset(f"task:{task['id']}", mapping={
                                    'status': 'failed',
                                    'failed_at': datetime.now().isoformat(),
                                    'error': str(e)
                                })
                        else:
                            logger.warning(f"No worker registered for task: {task_name}")
                            
                    else:
                        # No tasks available, sleep for a bit
                        time.sleep(1)
                        
                except Exception as e:
                    logger.error(f"Worker error for {task_name}: {e}")
                    time.sleep(5)
        
        # Start worker in a separate thread
        worker_thread = threading.Thread(target=worker_loop, daemon=True)
        worker_thread.start()
        return worker_thread
    
    def start_all_workers(self):
        """Start workers for all registered task types"""
        self.running = True
        threads = []
        
        for task_name in self.workers:
            thread = self.start_worker(task_name)
            threads.append(thread)
        
        logger.info(f"Started {len(threads)} workers")
        return threads
    
    def stop_workers(self):
        """Stop all workers"""
        self.running = False
        logger.info("Stopping all workers")
    
    def get_task_status(self, task_id: str):
        """Get status of a specific task"""
        try:
            task_info = self.redis_client.hgetall(f"task:{task_id}")
            return task_info
        except Exception as e:
            logger.error(f"Error getting task status: {e}")
            return None
    
    def get_queue_stats(self):
        """Get statistics about all queues"""
        stats = {}
        try:
            # Get all queue keys
            queue_keys = self.redis_client.keys("queue:*")
            
            for queue_key in queue_keys:
                task_name = queue_key.split(":", 1)[1]
                queue_size = self.redis_client.zcard(queue_key)
                stats[task_name] = queue_size
            
            return stats
        except Exception as e:
            logger.error(f"Error getting queue stats: {e}")
            return {}
    
    def clear_queue(self, task_name: str):
        """Clear all tasks from a specific queue"""
        try:
            self.redis_client.delete(f"queue:{task_name}")
            logger.info(f"Cleared queue for task: {task_name}")
        except Exception as e:
            logger.error(f"Error clearing queue {task_name}: {e}")

# Global Redis queue instance
redis_queue = RedisQueue() 