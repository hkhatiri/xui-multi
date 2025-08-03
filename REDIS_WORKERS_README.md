# Redis Workers Management

## Overview
Redis workers run in the background to process tasks like volume management (`sync_usage`) and panel cleanup. They are now managed separately from the main Reflex application.

## Files
- `start_redis_workers.py` - Main script to run Redis workers
- `manage_redis_workers.sh` - Management script for Redis workers
- `check_redis.py` - Enhanced Redis status checker with task statistics
- `redis_workers.log` - Log file for Redis workers

## Commands

### Start Redis Workers
```bash
./manage_redis_workers.sh start
```

### Stop Redis Workers
```bash
./manage_redis_workers.sh stop
```

### Restart Redis Workers
```bash
./manage_redis_workers.sh restart
```

### Check Status (Enhanced)
```bash
./manage_redis_workers.sh status
```
This enhanced command now shows:
- Redis workers and server status
- Detailed task statistics by type
- Last 10 completed tasks for `build_configs` and `sync_usage`
- Recent task status for all types
- Redis memory usage

### View Logs
```bash
./manage_redis_workers.sh logs
```

### Direct Redis Status Check
```bash
python check_redis.py
```

## Background Process
Redis workers run as a background process using `nohup`. The process will continue running even if you close the terminal.

## Monitoring
- Use `./manage_redis_workers.sh status` to check if workers are running and see task statistics
- Use `python check_redis.py` to see detailed queue status and task history
- Check `redis_workers.log` for detailed logs

## Task Types
The system processes several types of tasks:
- `sync_usage` - Volume management and usage tracking
- `build_configs` - Service configuration building
- `cleanup_panels` - Panel cleanup tasks
- `delete_service` - Service deletion
- `sync_services_with_panels` - Service-panel synchronization

## Automatic Startup
To start Redis workers automatically on system boot, add to crontab:
```bash
@reboot cd /home/hk/xui-multi && ./manage_redis_workers.sh start
```

## Troubleshooting
1. If workers are not processing tasks, restart them:
   ```bash
   ./manage_redis_workers.sh restart
   ```

2. Check if Redis server is running:
   ```bash
   systemctl status redis
   ```

3. View detailed logs:
   ```bash
   ./manage_redis_workers.sh logs
   ```

4. Check task statistics and recent completed tasks:
   ```bash
   ./manage_redis_workers.sh status
   ``` 