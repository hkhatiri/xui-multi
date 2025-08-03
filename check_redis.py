#!/usr/bin/env python3
"""
Redis Queue Status Checker - Terminal Tool
برای بررسی وضعیت صف‌های Redis و تسک‌های مدیریت حجم
"""

import redis
import json
from datetime import datetime
import sys
from collections import defaultdict

def check_redis_status():
    """Check Redis queue status"""
    try:
        # Connect to Redis
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        
        print("🔍 Redis Queue Status Check")
        print("=" * 50)
        
        # Check Redis connection
        r.ping()
        print("✅ Redis connected")
        
        # Get all queue keys
        queue_keys = r.keys("queue:*")
        print(f"\n📊 Number of queues: {len(queue_keys)}")
        
        if queue_keys:
            print("\n📋 Queue statistics:")
            for queue_key in queue_keys:
                task_name = queue_key.split(":", 1)[1]
                queue_size = r.zcard(queue_key)
                print(f"  - {task_name}: {queue_size} tasks")
                
                # Show details for sync_usage (volume management)
                if task_name == "sync_usage" and queue_size > 0:
                    print(f"    📈 Volume management tasks: {queue_size}")
                    # Show first few tasks
                    tasks = r.zrange(queue_key, 0, 2, withscores=True)
                    for i, (task_json, score) in enumerate(tasks):
                        try:
                            task = json.loads(task_json)
                            print(f"      {i+1}. Task {task.get('id', 'unknown')} (priority: {score})")
                        except:
                            print(f"      {i+1}. Unknown task (priority: {score})")
        else:
            print("  - No queues found")
        
        # Get task status keys and analyze them
        task_keys = r.keys("task:*")
        print(f"\n📋 Number of registered tasks: {len(task_keys)}")
        
        if task_keys:
            # Analyze tasks by type and status
            task_stats = defaultdict(lambda: defaultdict(int))
            completed_tasks = []
            
            for task_key in task_keys:
                task_id = task_key.split(":", 1)[1]
                task_info = r.hgetall(task_key)
                
                if task_info:
                    status = task_info.get('status', 'unknown')
                    task_type = task_info.get('task_type', 'unknown')
                    created_at = task_info.get('created_at', 'unknown')
                    completed_at = task_info.get('completed_at', '')
                    
                    # Count by type and status
                    task_stats[task_type][status] += 1
                    
                    # Collect completed tasks for detailed view
                    if status == 'completed' and completed_at:
                        completed_tasks.append({
                            'id': task_id,
                            'type': task_type,
                            'created_at': created_at,
                            'completed_at': completed_at,
                            'task_info': task_info
                        })
            
            # Show task statistics by type
            print("\n📊 Task Statistics by Type:")
            print("-" * 40)
            for task_type, status_counts in task_stats.items():
                total = sum(status_counts.values())
                print(f"\n🔹 {task_type}: {total} total tasks")
                for status, count in status_counts.items():
                    status_icon = {
                        'pending': '⏳',
                        'processing': '🔄',
                        'completed': '✅',
                        'failed': '❌'
                    }.get(status, '❓')
                    print(f"   {status_icon} {status}: {count}")
            
            # Show last 10 completed tasks for build_configs and sync_usage
            print("\n📋 Last 10 Completed Tasks (build_configs & sync_usage):")
            print("-" * 60)
            
            # Filter completed tasks for specific types
            target_tasks = [task for task in completed_tasks 
                          if task['type'] in ['build_configs', 'sync_usage']]
            
            # Sort by completion time (newest first) and take last 10
            target_tasks.sort(key=lambda x: x['completed_at'], reverse=True)
            recent_tasks = target_tasks[:10]
            
            if recent_tasks:
                for i, task in enumerate(recent_tasks, 1):
                    task_type_icon = "🔧" if task['type'] == 'build_configs' else "📊"
                    print(f"\n{i}. {task_type_icon} {task['type']} - Task ID: {task['id']}")
                    print(f"   📅 Created: {task['created_at']}")
                    print(f"   ✅ Completed: {task['completed_at']}")
                    
                    # Show additional task details if available
                    if 'service_uuid' in task['task_info']:
                        print(f"   🔗 Service UUID: {task['task_info']['service_uuid']}")
                    if 'result' in task['task_info']:
                        result = task['task_info']['result']
                        if result and result != 'None':
                            print(f"   📝 Result: {result[:100]}{'...' if len(result) > 100 else ''}")
            else:
                print("   No completed tasks found for build_configs or sync_usage")
            
            # Show recent task status (all types)
            print(f"\n📋 Recent task status (all types):")
            print("-" * 40)
            # Show last 10 tasks
            for task_key in task_keys[-10:]:
                task_id = task_key.split(":", 1)[1]
                task_info = r.hgetall(task_key)
                if task_info:
                    status = task_info.get('status', 'unknown')
                    task_type = task_info.get('task_type', 'unknown')
                    created_at = task_info.get('created_at', 'unknown')
                    completed_at = task_info.get('completed_at', '')
                    
                    # Color coding for status
                    status_icon = {
                        'pending': '⏳',
                        'processing': '🔄',
                        'completed': '✅',
                        'failed': '❌'
                    }.get(status, '❓')
                    
                    task_type_icon = {
                        'build_configs': '🔧',
                        'sync_usage': '📊',
                        'cleanup_panels': '🧹',
                        'update_service': '🔄',
                        'delete_service': '🗑️',
                        'sync_services_with_panels': '🔗'
                    }.get(task_type, '📋')
                    
                    print(f"  {status_icon} {task_type_icon} {task_id} ({task_type}): {status}")
                    if completed_at:
                        print(f"    └─ Completed: {completed_at}")
        
        # Check Redis memory usage
        info = r.info()
        print(f"\n💾 Redis memory usage:")
        print(f"  - Used memory: {info.get('used_memory_human', 'unknown')}")
        print(f"  - Total memory: {info.get('total_system_memory_human', 'unknown')}")
        
        print(f"\n⏰ Check time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
    except Exception as e:
        print(f"❌ Error connecting to Redis: {e}")
        return False
    
    return True

def check_specific_task(task_id):
    """Check status of a specific task"""
    try:
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        
        task_key = f"task:{task_id}"
        task_info = r.hgetall(task_key)
        
        if not task_info:
            print(f"❌ Task {task_id} not found")
            return
        
        print(f"🔍 Task details for {task_id}")
        print("=" * 30)
        
        for key, value in task_info.items():
            print(f"  {key}: {value}")
            
    except Exception as e:
        print(f"❌ خطا در بررسی تسک: {e}")

def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--task" and len(sys.argv) > 2:
            check_specific_task(sys.argv[2])
        elif sys.argv[1] == "--help":
            print("""
Usage:
  python3 check_redis.py              # Check overall Redis status
  python3 check_redis.py --task ID    # Check specific task status
  python3 check_redis.py --help       # Show help
            """)
        else:
            print("❌ Invalid command. Use --help for usage.")
    else:
        check_redis_status()

if __name__ == "__main__":
    main() 